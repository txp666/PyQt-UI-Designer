# coding: utf-8
"""Code generator — export project as standalone runnable Python project."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Any

from app.core.project import LINK_CARD_TYPES, ProjectData
from app.common.runtime_sources import runtime_source
from app.core.i18n import tr


def _runtime(name):
    """A runtime source as an export embeds it: it imports its translations from the export's i18n.py."""
    return runtime_source(name).replace("from .i18n import ", "from i18n import ")


def generate_project(project: ProjectData, output_dir: str, theme_mode=None, theme_color=None, language=None):
    """Generate a complete standalone Python project from project data.

    The application starts with the given theme mode and colour, by default the designer's current ones,
    and in the given language setting ("Auto", "zh_CN" or "en_US"), by default the designer's."""
    from PyQt5.QtGui import QColor
    from qfluentwidgets import Theme, qconfig
    from app.common.config import english_table, language_setting
    if language is None:
        language = language_setting()
    if theme_mode is None:
        theme_mode = qconfig.get(qconfig.themeMode)
    theme_mode = Theme(theme_mode).value
    if theme_color is None:
        theme_color = qconfig.get(qconfig.themeColor)
    color = QColor(theme_color)
    if not color.isValid():
        raise ValueError(tr("无效的主题色: %1", theme_color))
    theme_color = color.name()
    widgets, assets = _prepare_export_widgets(project)
    icons = _project_icons(project)
    bindings = _extract_bindings(widgets)

    def collect_types(items):
        return {w["type"] for w in items} | set().union(
            *(collect_types(w.get("children", [])) for w in items))

    widget_types = collect_types(widgets)
    # Finish generation and syntax validation before replacing a usable export.
    # A late configuration error must not leave old and new modules mixed.
    files = {
        "requirements.txt": (
            "PyQt5>=5.15.11,<5.16\n"
            'PyQt5-Qt5>=5.15.19; sys_platform == "darwin" and platform_machine == "arm64"\n'
            "PyQt-Fluent-Widgets>=1.5.5\npyserial>=3.5\npaho-mqtt>=1.6\ntruststore>=0.10\n"
            "pyqtgraph>=0.13.3\n"
        ),
        "main.py": _gen_main(theme_mode, theme_color, language),
        "theme_support.py": (_runtime("signal_lifetime.py") + "\n"
                             + _runtime("theme_runtime.py").replace(
                                 "from .signal_lifetime import SignalConnections", "")),
        "ui.py": _gen_ui(widgets, project.canvas_width, project.canvas_height,
                        project.app_name),
        "serial_handler.py": _gen_serial_handler(project.serial),
        "tcp_handler.py": _gen_tcp_handler(project.serial),
        "udp_handler.py": _gen_udp_handler(project.serial),
        "mqtt_handler.py": _gen_mqtt_handler(project.serial),
        "comm_hub.py": _gen_comm_hub(),
        "data_binding.py": _gen_data_binding(bindings, widget_types, _link_card_ids(widgets)),
    }
    files["i18n.py"] = _gen_i18n(files, {} if language == "zh_CN" else english_table())
    for name, source in files.items():
        if name.endswith(".py"):
            compile(source, name, "exec")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for relative_path, content in assets.items():
        target = out / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for name, source in files.items():
        (out / name).write_text(source, encoding="utf-8")

    # Keep icons beside main.py in both source exports and compiled apps.
    if icons:
        for name, content in icons.items():
            (out / name).write_bytes(content)
        # The macOS build prefers logo.icns, which an earlier export may have left with the designer's logo.
        (out / "logo.icns").unlink(missing_ok=True)
    else:
        import shutil
        _root = Path(__file__).resolve().parent.parent.parent
        for name in ("logo.ico", "logo.png", "logo.icns"):
            source = _root / name
            if source.exists() and source.resolve() != (out / name).resolve():
                shutil.copy2(str(source), str(out / name))


def _project_icons(project):
    """The project's icon as logo.png (window, Dock and macOS app icon) and logo.ico (Windows .exe), by
    file name; None for the designer's own icon."""
    if not project.icon:
        return None
    from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PyQt5.QtGui import QImage, QImageReader, QPainter

    path = project.icon_file()
    reader = QImageReader(path)
    image = QImage()
    for index in range(max(reader.imageCount(), 1)):
        reader.jumpToImage(index)
        frame = reader.read()
        # An .ico holds several sizes; the window icon takes the largest.
        if frame.width() * frame.height() > image.width() * image.height():
            image = frame
    try:
        content = Path(path).read_bytes()
    except OSError:
        content = None
    if content is None or image.isNull():
        raise ValueError(tr("图标不存在或不可读: %1", path))

    def encoded(kind):
        picture = image
        if kind == "ICO" and image.width() != image.height():
            # Windows stretches an icon to a square, so a wide image is centred on a transparent one.
            side = max(image.width(), image.height())
            picture = QImage(side, side, QImage.Format_ARGB32)
            picture.fill(Qt.transparent)
            painter = QPainter(picture)
            painter.drawImage((side - image.width()) // 2, (side - image.height()) // 2, image)
            painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        if not picture.save(buffer, kind):
            raise ValueError(tr("无法把图标转换为 %1: %2", kind, path))
        return bytes(data)

    suffix = Path(path).suffix.lower()
    return {"logo.png": content if suffix == ".png" else encoded("PNG"),
            "logo.ico": content if suffix == ".ico" else encoded("ICO")}


def _prepare_export_widgets(project):
    """Resolve project images before writing, without changing the source project."""
    widgets = copy.deepcopy(project.widgets)
    base_dir = (Path(project.file_path).expanduser().resolve().parent
                if project.file_path else Path.cwd())
    assets = {}

    def walk(items):
        for widget in items:
            props = widget.get("properties", {})
            image_path = props.get("imagePath")
            if widget["type"] == "ImageDisplay" and image_path:
                try:
                    source = Path(image_path).expanduser()
                    if not source.is_absolute():
                        source = base_dir / source
                    source = source.resolve()
                    content = source.read_bytes()
                except (OSError, TypeError, ValueError) as exc:
                    raise ValueError(
                        tr("无法导出图片（控件 %1）: %2；%3", widget["id"], image_path, exc)
                    ) from exc
                # Content names avoid collisions between equally named files.
                name = hashlib.sha256(content).hexdigest() + source.suffix.lower()
                relative_path = f"assets/{name}"
                assets[relative_path] = content
                props["imagePath"] = relative_path
            walk(widget.get("children", []))

    walk(widgets)
    return widgets, assets


def _gen_i18n(files, table):
    """The export's i18n.py: the runtime's translation module and the English texts of ``table`` whose
    Chinese source appears as a string in the generated modules."""
    used = set()
    for name, source in files.items():
        if name.endswith(".py"):
            used.update(node.value for node in ast.walk(ast.parse(source))
                        if isinstance(node, ast.Constant) and isinstance(node.value, str))
    entries = {key: table[key] for key in sorted(used) if key in table}
    return (runtime_source("i18n.py")
            + "\n\n# The English texts of this application, by their Chinese source text.\n"
            + f"TABLE = {json.dumps(entries, ensure_ascii=False, indent=4)}\n")


def _gen_main(theme_mode="Auto", theme_color="#009faa", language="Auto") -> str:
    return '''\
# coding: utf-8
"""Auto-generated by PyQt UI Designer."""
import sys
import os
import ctypes
from pathlib import Path

from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

app = QApplication(sys.argv)
from qfluentwidgets import qconfig, setThemeColor
if sys.platform == "darwin" and hasattr(qconfig, "fontFamilies"):
    qconfig.set(qconfig.fontFamilies, ["PingFang SC", "Helvetica Neue"], save=False)

setThemeColor(_THEME_COLOR_)
from theme_support import ThemeController
theme_controller = ThemeController(app, _THEME_MODE_)

# The interface language, set before the interface exists: "Auto" follows the system.
from i18n import TABLE, language, set_language
set_language(_LANGUAGE_, TABLE)
if language() == "zh_CN":  # the Fluent widgets' own texts are English in their source
    from PyQt5.QtCore import QLocale
    from qfluentwidgets import FluentTranslator
    translator = FluentTranslator(QLocale(QLocale.Chinese, QLocale.China))
    app.installTranslator(translator)

from ui import MainUI
from comm_hub import CommHub
from data_binding import DataBinding

window = MainUI()
comm_hub = CommHub()  # every link card registers its own link here, behind one set of signals
binding = DataBinding(window, comm_hub)

if sys.platform == "win32":
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("pyqt.ui.app")
_ico = Path(__file__).resolve().parent / "logo.png"
if _ico.exists():
    _icon = QIcon(str(_ico))
    app.setWindowIcon(_icon)
    window.setWindowIcon(_icon)

app.aboutToQuit.connect(comm_hub.disconnect)
window.show()
exit_code = app.exec()
window.deleteLater()
comm_hub.deleteLater()
theme_controller.deleteLater()
app.sendPostedEvents(None, QEvent.DeferredDelete)
sys.exit(exit_code)
'''.replace("_THEME_MODE_", repr(theme_mode)).replace("_THEME_COLOR_", repr(theme_color)).replace(
        "_LANGUAGE_", repr(language))


def _gen_ui(widgets: List[Dict], canvas_w: int, canvas_h: int, app_name: str = "上位机") -> str:  # i18n: value
    lines = [
        '# coding: utf-8',
        '"""Auto-generated UI module."""',
        'import struct, math, json',
        'from html import escape as _html_escape',
        '',
        'def _log_html(text):',
        '    return _html_escape(str(text)).replace("\\n", "<br>")',
        'from pathlib import Path',
        '',
        'from PyQt5.QtCore import Qt, QTimer, QRectF',
        'from PyQt5.QtWidgets import (',
        '    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,',
        '    QFrame, QGroupBox, QTabWidget, QTextEdit, QCheckBox,',
        '    QSizePolicy, QHeaderView, QAbstractItemView, QTableWidget, QTableWidgetItem,',
        '    QSpinBox, QPushButton, QFileDialog, QLineEdit,',
        ')',
        'from PyQt5.QtGui import QColor, QPainter, QFont, QPen, QConicalGradient',
        '',
        'from qfluentwidgets import (',
        '    PushButton, PrimaryPushButton, BodyLabel, StrongBodyLabel,',
        '    CaptionLabel, LineEdit, ComboBox, TextEdit, CheckBox,',
        '    SwitchButton, Slider, SpinBox, ProgressBar, ProgressRing,',
        '    CardWidget, TableWidget, ToolButton, ScrollArea,',
        '    FluentWindow, NavigationItemPosition,',
        '    FluentIcon as FIF, InfoBar, InfoBarPosition, isDarkTheme,',
        '    qconfig, setCustomStyleSheet, themeColor,',
        ')',
        '',
        'from i18n import tr, N_',
        'from serial_handler import _list_all_ports',
        '',
        'try:',
        '    import serial',
        '    import serial.tools.list_ports',
        '    HAS_SERIAL = True',
        'except ImportError:',
        '    HAS_SERIAL = False',
        '',
        'try:',
        '    import pyqtgraph as pg',
        '    HAS_PYQTGRAPH = True',
        'except ImportError:',
        '    HAS_PYQTGRAPH = False',
        '',
        '',
    ]

    lines.append(_runtime("signal_lifetime.py"))
    lines.append(_runtime("qt_window_lifetime.py"))
    lines.append(_runtime("command_runtime.py").replace(
        "from .modbus_master import (", "from serial_handler import (").replace(
        "from .modbus_slave import AREA_TABLES", "from serial_handler import AREA_TABLES"))

    # custom widget classes needed (recursive)
    def _collect_types(items):
        types = set()
        for w in items:
            types.add(w["type"])
            types |= _collect_types(w.get("children", []))
        return types
    widget_types = _collect_types(widgets)

    if "TabWidget" in widget_types:
        lines.append(_runtime("tab_geometry.py"))
    if "Slider" in widget_types:
        lines.append(_runtime("slider_release.py"))
        lines.append(_runtime("slider_limits.py"))
    if "LEDIndicator" in widget_types:
        lines.append(_led_class())
    if "NumericDisplay" in widget_types:
        lines.append(_numeric_display_class())
    if "RealtimeChart" in widget_types:
        lines.append(_realtime_chart_class())
    if "GaugeMeter" in widget_types:
        lines.append(_gauge_class())
    if "SerialTerminal" in widget_types:
        lines.append(_serial_terminal_class())
    if "DataTable" in widget_types or "DataTable" in widget_types:
        lines.append(_data_table_class())
    if "ImageDisplay" in widget_types:
        lines.append(_image_display_class())
    if widget_types & {"HBoxLayout", "VBoxLayout", "FlexLayout", "CardContainer"}:
        lines.append(_titled_container_classes())
    if "ProgressRingDisplay" in widget_types:
        lines.append(_progress_ring_display_class())
    if "LogBox" in widget_types or "LogDisplayBox" in widget_types:
        lines.append(_log_display_class())
    if widget_types & set(LINK_CARD_TYPES):
        lines.append(_link_polling_source())  # every link card's Modbus polling settings and status
    if "SerialConfigCard" in widget_types:
        lines.append(_serial_config_card_class())
    if widget_types & {"TcpConfigCard", "UdpConfigCard", "MqttConfigCard"}:
        lines.append(_link_card_class())
    if "TcpConfigCard" in widget_types:
        lines.append(_tcp_config_card_class())
    if "UdpConfigCard" in widget_types:
        lines.append(_udp_config_card_class())
    if "MqttConfigCard" in widget_types:
        lines.append(_mqtt_config_card_class())
    if "DataSendCard" in widget_types:
        lines.append(_data_send_card_class())
    if "DataRecvCard" in widget_types:
        lines.append(_data_recv_card_class())
    if "ModbusSlaveTable" in widget_types:
        lines.append(_slave_table_class())

    # MainUI class
    lines.append(f'''
class MainUI(TitleBarLifecycleMixin, FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle({app_name!r})
        self.resize({canvas_w + 100}, {canvas_h + 100})

        self._page = QWidget()
        self._page.setObjectName("mainPage")
        self._page.setFixedSize({canvas_w}, {canvas_h})

        self.widgets = {{}}
        self._theme_containers = []
        self._create_widgets()

        scroll = ScrollArea()
        scroll.setObjectName("scrollPage")
        scroll.enableTransparentBackground()  # before the page is in it: it would also clear the page's
        scroll.setWidget(self._page)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignCenter)

        self.addSubInterface(scroll, FIF.HOME, tr("主界面"))
        self.apply_theme()
        self._external_connections = SignalConnections(self)
        self._external_connections.connect(
            qconfig.themeChangedFinished, self.apply_theme)

''')
    lines.append('''
    def apply_theme(self):
        dark = isDarkTheme()
        background = "#2b2b2b" if dark else "#ffffff"
        border = "#606060" if dark else "#c8c8c8"
        foreground = "#f3f3f3" if dark else "#202020"
        self._page.setStyleSheet(
            f"QWidget#mainPage {{ background: {background}; "
            f"border: 1px solid {'#444' if dark else '#ddd'}; }}")
        for widget, kind in self._theme_containers:
            if kind == "layout":
                line = "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.06)"
                fill = "rgba(255,255,255,0.03)" if dark else "rgba(0,0,0,0.02)"
                widget.setStyleSheet(
                    f"QFrame#layoutContainer {{ border: 2px dashed {line}; "
                    f"background: {fill}; border-radius: 6px; }}")
            elif kind == "group":
                widget.setStyleSheet(
                    f"QGroupBox#groupContainer {{ color: {foreground}; "
                    f"border: 1px solid {border}; border-radius: 6px; margin-top: 10px; }}"
                    "QGroupBox#groupContainer::title { subcontrol-origin: margin; "
                    "subcontrol-position: top left; left: 10px; padding: 0 4px; }")
            elif kind == "tabs":
                fill = "#292929" if dark else "#ededed"
                selected = "#3c3c3c" if dark else "#ffffff"
                widget.setStyleSheet(
                    f"QTabWidget#tabContainer::pane {{ border: 1px solid {border}; border-radius: 4px; }}"
                    "QTabWidget#tabContainer > QTabBar::tab {"
                    f"color: {foreground}; background: {fill}; "
                    "padding: 6px 12px; margin-right: 2px; "
                    "border-top-left-radius: 4px; border-top-right-radius: 4px; }"
                    "QTabWidget#tabContainer > QTabBar::tab:selected {"
                    f"background: {selected}; }}")
        self._page.update()

    def _create_widgets(self):
''')

    _gen_widgets_recursive(widgets, lines, "self._page")
    if not widgets:
        lines.append("        pass")

    def _has_commands(items):
        for w in items:
            p = w.get("properties", {})
            if (p.get("command") or p.get("onCommand") or p.get("offCommand")
                    or p.get("commandMode") == "Modbus"
                    or p.get("sendOnEnter") or p.get("sendOnSelect")
                    or p.get("sendOnChange")):
                return True
            if _has_commands(w.get("children", [])):
                return True
        return False

    if _has_commands(widgets):
        lines.append('''
    def _send_text_command(self, cmd, suffix="\\r\\n"):
        if hasattr(self, '_comm_hub') and self._comm_hub.is_connected:
            self._comm_hub.send_text(cmd + suffix)

    def _command_error(self, error):
        InfoBar.error(title=tr("提示"), content=str(error), duration=2000, parent=self)

    def _send_hex_command(self, cmd, header="", tail=""):
        if hasattr(self, '_comm_hub') and self._comm_hub.is_connected:
            try:
                frame = command_hex_frame(cmd, header, tail)
            except ValueError as exc:
                self._command_error(exc)
                return
            self._comm_hub.send(frame)

    def _send_modbus(self, slave, func, address, value=1, data_type="uint16", reg_order="大端(AB CD)"):  # i18n: value
        # A write goes into the data table of every link card in the 从站 role, connected or not; then one
        # request per connected link, framed as it parses: RTU, MBAP (modbus_tcp) or ASCII (modbus_ascii).
        devices = slave_devices(self.widgets.values())
        if devices:
            try:
                slave_command_write(devices, modbus_request(slave, func, address, value, data_type, reg_order))
            except ValueError as exc:
                self._command_error(exc)
                return
        if hasattr(self, '_comm_hub') and self._comm_hub.is_connected:
            try:
                send_modbus_command(self._comm_hub, slave, func, address, value, data_type, reg_order)
            except ValueError as exc:
                self._command_error(exc)

    def _send_json_command(self, value, template="{value}", newline="无"):  # i18n: value
        if hasattr(self, '_comm_hub') and self._comm_hub.is_connected:
            try:
                frame = json_command({"commandTemplate": template, "commandJsonNewline": newline}, value)
            except ValueError as exc:
                self._command_error(exc)
                return
            self._comm_hub.send(frame)

    def _send_packed_value(self, value, fmt, cast=int, tpl="{value}", header="", tail=""):
        if hasattr(self, '_comm_hub') and self._comm_hub.is_connected:
            try:
                frame = command_packed_frame(value, fmt, cast, tpl, header, tail)
            except ValueError as exc:
                self._command_error(exc)
                return
            self._comm_hub.send(frame)
''')

    if _has_slave_writes(widgets):
        lines.append('''
    def _slave_write(self, area, address, value, data_type="uint16", reg_order="大端(AB CD)"):  # i18n: value
        # A user's change of a control with a Modbus binding, into every 从站 card's data table.
        slave_control_write(slave_devices(self.widgets.values()), area, address, value, data_type, reg_order)
''')

    return "\n".join(lines)


def _slave_write_binding(wtype, binding):
    """The Modbus binding a control's changes write into the slaves' data tables, or None: a switch,
    slider or spin box bound in Modbus mode without an expression (its value cannot be worked back)."""
    if (wtype not in ("ToggleSwitch", "Slider", "SpinBox") or not binding
            or binding.get("parseMode") != "Modbus" or binding.get("expression")):
        return None
    return binding


def _has_slave_writes(widgets):
    return any(_slave_write_binding(w["type"], w.get("binding")) is not None
               or _has_slave_writes(w.get("children", [])) for w in widgets)


def _gen_slave_write_connection(wid, wtype, binding):
    """Lines that write a control's changes into the slaves' data tables, when a command would go out."""
    binding = _slave_write_binding(wtype, binding)
    if binding is None:
        return []
    from app.core.command_runtime import MODBUS_ORDERS
    args = (binding.get("mbArea", "保持寄存器"), int(binding.get("mbRegIndex", 0)))  # i18n: value
    typed = (binding.get("mbDataType", "uint16"), binding.get("mbRegOrder", MODBUS_ORDERS[0]))
    head, tail = f"{args[0]!r}, {args[1]}", f", {typed[0]!r}, {typed[1]!r}"
    w_ref = f"self.widgets[{wid!r}]"
    if wtype == "ToggleSwitch":
        return [f"        {w_ref}._switch.checkedChanged.connect("
                f"lambda c: self._slave_write({head}, 1 if c else 0{tail}))"]
    if wtype == "Slider":
        return [f"        SendOnRelease(slider_of({w_ref}), lambda v: self._slave_write({head}, v{tail}))"]
    return [f"        {w_ref}.valueChanged.connect(lambda v: self._slave_write({head}, v{tail}))"]


def _gen_widgets_recursive(widgets: list, lines: list, parent_var: str, tab_var=None):
    """Recursively generate widget creation code, handling nested children."""
    for w in widgets:
        wid = w["id"]
        wtype = w["type"]
        props = w.get("properties", {})
        geo = w.get("geometry", {})
        x, y = int(geo.get("x", 0)), int(geo.get("y", 0))
        width, height = int(geo.get("w", 120)), int(geo.get("h", 40))

        create_code = _widget_create_code(wid, wtype, props, parent_var)
        lines.append(f"        {create_code}")
        if tab_var:
            lines.append(f"        place_tab_child({tab_var}, self.widgets[{wid!r}], "
                         f"{x}, {y}, {width}, {height})")
        else:
            lines.append(f"        self.widgets[{wid!r}].setGeometry({x}, {y}, {width}, {height})")
        lines.append(f"        self.widgets[{wid!r}].show()")

        cmd_lines = _gen_command_connection(wid, wtype, props)
        if cmd_lines:
            lines += cmd_lines
        lines += _gen_slave_write_connection(wid, wtype, w.get("binding"))

        if props.get("notify"):
            lines += _gen_notify_connection(wid, wtype, props)

        lines.append("")

        children = w.get("children", [])
        if children:
            if wtype == "TabWidget":
                from collections import defaultdict
                from app.widgets.layout import tab_names, clamp_tab_index
                tabs = defaultdict(list)
                page_count = len(tab_names(props.get("tabNames", "标签1\n标签2")))  # i18n: value
                for c in children:
                    tabs[clamp_tab_index(c.get("tabIndex", 0), page_count)].append(c)
                for ti, tab_children in sorted(tabs.items()):
                    page_var = f"self.widgets[{wid!r}].widget({ti})"
                    _gen_widgets_recursive(tab_children, lines, page_var,
                                           tab_var=f"self.widgets[{wid!r}]")
            else:
                child_parent = f"self.widgets[{wid!r}]"
                _gen_widgets_recursive(children, lines, child_parent)


_NEWLINE_CODE_MAP = {"无": "", "\\r\\n": "\r\n", "\\n": "\n", "\\r": "\r"}  # i18n: value
_NOTIFY_TYPE_MAP = {"成功": "success", "信息": "info", "警告": "warning", "错误": "error"}  # i18n: value


def _gen_command_connection(wid: str, wtype: str, props: dict) -> list:
    """Generate command connection lines for a widget (sent over the communication hub)."""
    mode = props.get("commandMode", "文本")  # i18n: value
    newline = props.get("commandNewline", "\\r\\n")
    suffix = _NEWLINE_CODE_MAP.get(newline, "\r\n")
    tpl = props.get("commandTemplate", "{value}")
    tpl_repr = repr(tpl)
    fh = props.get("frameHeader", "").strip()
    ft = props.get("frameTail", "").strip()
    dtype = props.get("dataType", "HEX字符串")  # i18n: value
    border = props.get("byteOrder", "大端(BE)")  # i18n: value
    w_ref = f"self.widgets[{wid!r}]"
    result = []

    _FMT_MAP = {"uint8": "B", "int8": "b", "uint16": "H",
                "int16": "h", "uint32": "I", "int32": "i",
                "float32": "f"}
    is_struct = dtype in _FMT_MAP

    def _tpl_send(val_expr: str) -> str:
        """Generate a template-aware send expression."""
        if mode == "JSON":
            json_newline = props.get("commandJsonNewline", "无")  # i18n: value
            return f"self._send_json_command(str({val_expr}), {tpl_repr}, {json_newline!r})"
        if mode == "HEX" and is_struct:
            fmt = _FMT_MAP[dtype]
            bo = ">" if border == "大端(BE)" else "<"  # i18n: value
            cast = "float" if dtype == "float32" else "int"
            return (f"self._send_packed_value({val_expr}, "
                    f"{repr(bo + fmt)}, {cast}, {tpl_repr}, {repr(fh)}, {repr(ft)})")
        if tpl == "{value}":
            raw_expr = f"str({val_expr})"
        else:
            raw_expr = f"{tpl_repr}.replace('{{value}}', str({val_expr}))"
        if mode == "HEX":
            return f"self._send_hex_command({raw_expr}, {repr(fh)}, {repr(ft)})"
        return f"self._send_text_command({raw_expr}, {repr(suffix)})"

    def _modbus_send(val_expr: str, default_func="06 写单寄存器") -> str:  # i18n: value
        from app.core.command_runtime import MODBUS_FUNCTIONS, MODBUS_ORDERS
        slave = int(props.get("mbSlave", 1))
        fc = MODBUS_FUNCTIONS.get(props.get("mbFunc", default_func), MODBUS_FUNCTIONS[default_func])
        addr = int(props.get("mbAddress", 0))
        typed = (props.get("mbDataType", "uint16"), props.get("mbRegOrder", MODBUS_ORDERS[0]))
        extra = "" if typed == ("uint16", MODBUS_ORDERS[0]) else f", {typed[0]!r}, {typed[1]!r}"
        return f"self._send_modbus({slave}, {fc}, {addr}, {val_expr}{extra})"

    if wtype == "PushButton":
        cmd = props.get("command", "").strip()
        if mode == "Modbus":
            from app.widgets.basic import button_modbus_value
            send = _modbus_send(repr(button_modbus_value(props)), "03 读保持寄存器")  # i18n: value
            result.append(f"        {w_ref}.clicked.connect(lambda: {send})")
        elif cmd:
            result.append(
                f"        {w_ref}.clicked.connect("
                f"lambda: {_tpl_send(repr(cmd))})")

    elif wtype == "ToggleSwitch":
        switch_ref = f"{w_ref}._switch"
        on_cmd = props.get("onCommand", "").strip()
        off_cmd = props.get("offCommand", "").strip()
        if mode == "Modbus":
            slave = int(props.get("mbSlave", 1))
            addr = int(props.get("mbAddress", 0))
            result.append(
                f"        {switch_ref}.checkedChanged.connect("
                f"lambda c: self._send_modbus({slave}, 5, {addr}, "
                f"0xFF00 if c else 0x0000))")
        elif on_cmd or off_cmd:
            result.append(
                f"        {switch_ref}.checkedChanged.connect("
                f"lambda c: {_tpl_send(repr(on_cmd)) if on_cmd else 'None'} "
                f"if c else {_tpl_send(repr(off_cmd)) if off_cmd else 'None'})")

    elif wtype == "LineEdit" and (props.get("sendOnEnter") or mode == "Modbus"):
        if mode == "Modbus":
            result.append(
                f"        {w_ref}.returnPressed.connect("
                f"lambda: {_modbus_send(f'{w_ref}.text().strip()')})")
        else:
            result.append(
                f"        {w_ref}.returnPressed.connect("
                f"lambda: {_tpl_send(f'{w_ref}.text().strip()')} "
                f"if {w_ref}.text().strip() else None)")

    elif wtype == "ComboBox" and (props.get("sendOnSelect") or mode == "Modbus"):
        commands = [s.strip() for s in props.get("commands", "").split("\n")]
        val_expr = f"(_cmds[i] if i < len(_cmds) and _cmds[i] else {w_ref}.currentText())"
        send_expr = _modbus_send(val_expr) if mode == "Modbus" else _tpl_send(val_expr)
        result.append(
            f"        {w_ref}.currentIndexChanged.connect("
            f"lambda i, _cmds={commands!r}: {send_expr} "
            f"if i >= 0 and {val_expr} else None)")

    elif wtype in ("Slider", "SpinBox") and (props.get("sendOnChange") or mode == "Modbus"):
        send = _modbus_send('v') if mode == "Modbus" else _tpl_send('v')
        if wtype == "Slider":  # a drag sends once, when it lets go (slider_release.py)
            result.append(f"        SendOnRelease(slider_of({w_ref}), lambda v: {send})")
        else:
            result.append(f"        {w_ref}.valueChanged.connect(lambda v: {send})")

    return result


def _gen_notify_connection(wid: str, wtype: str, props: dict) -> list:
    """Generate notification connection lines for a widget."""
    title = repr(props.get("notifyTitle", "提示"))  # i18n: value
    content = repr(props.get("notifyContent", ""))
    ntype = _NOTIFY_TYPE_MAP.get(props.get("notifyType", "信息"), "info")  # i18n: value
    duration = int(props.get("notifyDuration", 3000))
    w_ref = f"self.widgets[{wid!r}]"
    cb = (f"lambda: InfoBar.{ntype}(title={title}, content={content}, "
          f"orient=Qt.Horizontal, isClosable=True, "
          f"position=InfoBarPosition.TOP, duration={duration}, parent=self)")
    result = []
    if wtype == "PushButton":
        result.append(f"        {w_ref}.clicked.connect({cb})")
    elif wtype == "ToggleSwitch":
        result.append(f"        {w_ref}._switch.checkedChanged.connect({cb})")
    return result


def _widget_create_code(wid: str, wtype: str, props: dict, parent_var: str = "self._page") -> str:
    """Return Python code line(s) to create a widget."""
    from app.widgets.base import normalized_range_properties
    props = normalized_range_properties(wtype, props)
    p = lambda k, d="": repr(props.get(k, d))
    pv = parent_var

    # A property missing from the file gets its default, the same in every language.
    if wtype == "PushButton":
        text = p("text", "按钮")  # i18n: value
        return (f"self.widgets[{wid!r}] = PushButton({text}, {pv}); "
                f"self.widgets[{wid!r}].setEnabled({p('enabled', True)})")
    if wtype == "Label":
        alignment = {"Left": "Qt.AlignLeft | Qt.AlignVCenter",
                     "Center": "Qt.AlignCenter",
                     "Right": "Qt.AlignRight | Qt.AlignVCenter"}.get(
                         props.get("alignment", "Left"), "Qt.AlignLeft | Qt.AlignVCenter")
        text = p("text", "标签")  # i18n: value
        return (f"self.widgets[{wid!r}] = BodyLabel({text}, {pv}); "
                f"_font = self.widgets[{wid!r}].font(); "
                f"_font.setPointSize({int(props.get('fontSize', 14))}); "
                f"_font.setBold({bool(props.get('bold', False))!r}); "
                f"self.widgets[{wid!r}].setFont(_font); "
                f"self.widgets[{wid!r}].setAlignment({alignment})")
    if wtype == "LineEdit":
        return (f"self.widgets[{wid!r}] = LineEdit({pv}); "
                f"self.widgets[{wid!r}].setPlaceholderText({p('placeholderText', '')}); "
                f"self.widgets[{wid!r}].setText({p('text', '')}); "
                f"self.widgets[{wid!r}].setReadOnly({p('readOnly', False)})")
    if wtype == "ComboBox":
        items = [s.strip() for s in props.get("items", "").split("\n") if s.strip()]
        code = (f"self.widgets[{wid!r}] = ComboBox({pv}); "
                f"self.widgets[{wid!r}].addItems({repr(items)})")
        index = props.get("currentIndex", 0)
        if 0 <= index < len(items):
            code += f"; self.widgets[{wid!r}].setCurrentIndex({index})"
        return code
    if wtype == "ToggleSwitch":
        lbl = props.get("label", "开关")  # i18n: value
        return (f"_tw = QWidget({pv}); _tl = QHBoxLayout(_tw); _tl.setContentsMargins(0,0,0,0); "
                f"_sw = SwitchButton(); _sw.setChecked({props.get('checked', False)}); "
                f"_tl.addWidget(BodyLabel({repr(lbl)})); _tl.addStretch(); _tl.addWidget(_sw); "
                f"_tw._switch = _sw; self.widgets[{wid!r}] = _tw")
    if wtype == "Slider":
        # Without the limits the widget is the Slider itself, as it always was.
        if props.get("showRange"):
            return (f"self.widgets[{wid!r}] = SliderWithLimits({pv}); "
                    f"self.widgets[{wid!r}].set_show_range(True); "
                    f"slider_of(self.widgets[{wid!r}]).setRange({props.get('minimum', 0)}, {props.get('maximum', 100)}); "
                    f"slider_of(self.widgets[{wid!r}]).setValue({props.get('value', 50)})")
        return (f"self.widgets[{wid!r}] = Slider(Qt.Horizontal, {pv}); "
                f"self.widgets[{wid!r}].setRange({props.get('minimum', 0)}, {props.get('maximum', 100)}); "
                f"self.widgets[{wid!r}].setValue({props.get('value', 50)})")
    if wtype == "SpinBox":
        code = (f"self.widgets[{wid!r}] = SpinBox({pv}); "
                f"self.widgets[{wid!r}].setRange({props.get('minimum', 0)}, {props.get('maximum', 100)}); "
                f"self.widgets[{wid!r}].setValue({props.get('value', 0)})")
        if props.get("suffix"):
            code += f"; self.widgets[{wid!r}].setSuffix({(' ' + props['suffix'])!r})"
        return code
    if wtype == "LEDIndicator":
        label = p("label", "状态")  # i18n: value
        return (f"self.widgets[{wid!r}] = LEDIndicator({pv}); "
                f"self.widgets[{wid!r}].set_color({repr(props.get('color', 'green'))}); "
                f"self.widgets[{wid!r}].set_label({label}); "
                f"self.widgets[{wid!r}].set_on({bool(props.get('on', True))!r})")
    if wtype == "NumericDisplay":
        title = p("title", "温度")  # i18n: value
        return (f"self.widgets[{wid!r}] = NumericDisplay({pv}); "
                f"self.widgets[{wid!r}].set_title({title}); "
                f"self.widgets[{wid!r}].set_unit({repr(props.get('unit', ''))}); "
                f"self.widgets[{wid!r}].set_value({repr(props.get('value', '0.00'))}); "
                f"self.widgets[{wid!r}].set_font_size({int(props.get('fontSize', 28))})")
    if wtype == "ProgressBar":
        return (f"self.widgets[{wid!r}] = ProgressBar({pv}); "
                f"self.widgets[{wid!r}].setMaximum({props.get('maximum', 100)}); "
                f"self.widgets[{wid!r}].setValue({props.get('value', 50)})")
    if wtype == "RealtimeChart":
        from app.widgets.chart import build_cfgs_from_props
        disp_pts = int(props.get("displayPoints", 200))
        cfgs = build_cfgs_from_props(props)
        title = p("title", "实时曲线")  # i18n: value
        return (f"self.widgets[{wid!r}] = RealtimeLineChart({pv}); "
                f"self.widgets[{wid!r}].configure({json.dumps(cfgs, ensure_ascii=False)!r}, {disp_pts}); "
                f"self.widgets[{wid!r}].set_title({title})")
    if wtype == "GaugeMeter":
        title = p("title", "仪表")  # i18n: value
        return (f"self.widgets[{wid!r}] = GaugeMeter({pv}); "
                f"self.widgets[{wid!r}].set_range({props.get('minimum', 0)}, {props.get('maximum', 100)}); "
                f"self.widgets[{wid!r}].set_title({title}); "
                f"self.widgets[{wid!r}].set_unit({p('unit', '')}); "
                f"self.widgets[{wid!r}].set_value({props.get('value', 0)})")
    if wtype == "SerialTerminal":
        return f"self.widgets[{wid!r}] = SerialTerminal({pv})"
    if wtype == "DataTable":
        columns = [name.strip() for name in props.get("columns", "字段\n值").split("\n")  # i18n: value
                   if name.strip()]
        record_mode = p("recordMode", "最新值")  # i18n: value
        return (f"self.widgets[{wid!r}] = DataTableWidget({pv}); "
                f"self.widgets[{wid!r}].set_columns({columns!r}); "
                f"self.widgets[{wid!r}].set_record_mode({record_mode}); "
                f"self.widgets[{wid!r}].set_max_rows({p('maxRows', 500)})")

    # Layout containers
    if wtype in ("HBoxLayout", "VBoxLayout", "FlexLayout"):
        title = {"HBoxLayout": "水平布局", "VBoxLayout": "垂直布局", "FlexLayout": "弹性布局"}[wtype]  # i18n: value
        return (f"self.widgets[{wid!r}] = TitledLayoutContainer({pv}); "
                f"self.widgets[{wid!r}].set_title({p('title', title)}); "
                f"self.widgets[{wid!r}].setObjectName('layoutContainer'); "
                f"self._theme_containers.append((self.widgets[{wid!r}], 'layout'))")
    if wtype == "GroupBox":
        title = p("title", "分组")  # i18n: value
        return (f"self.widgets[{wid!r}] = QGroupBox({title}, {pv}); "
                f"self.widgets[{wid!r}].setObjectName('groupContainer'); "
                f"self._theme_containers.append((self.widgets[{wid!r}], 'group'))")
    if wtype == "TabWidget":
        from app.widgets.layout import tab_names, clamp_tab_index
        names = tab_names(props.get("tabNames", "标签1\n标签2"))  # i18n: value
        parts = [f"self.widgets[{wid!r}] = QTabWidget({pv})",
                 f"self.widgets[{wid!r}].setObjectName('tabContainer')",
                 f"self._theme_containers.append((self.widgets[{wid!r}], 'tabs'))"]
        for name in names:
            parts.append(f"self.widgets[{wid!r}].addTab(QWidget(), {repr(name)})")
        ct = clamp_tab_index(props.get("currentTab", 0), len(names))
        if ct > 0:
            parts.append(f"self.widgets[{wid!r}].setCurrentIndex({ct})")
        return "; ".join(parts)
    if wtype == "Separator":
        orient = props.get("orientation", "horizontal")
        shape = "QFrame.HLine" if orient == "horizontal" else "QFrame.VLine"
        fixed_axis = "setFixedHeight" if orient == "horizontal" else "setFixedWidth"
        return (f"self.widgets[{wid!r}] = QFrame({pv}); "
                f"self.widgets[{wid!r}].setFrameShape({shape}); "
                f"self.widgets[{wid!r}].{fixed_axis}(2); "
                f"self.widgets[{wid!r}].setStyleSheet('color: rgba(128,128,128,0.3);')")
    if wtype == "CardContainer":
        return (f"self.widgets[{wid!r}] = TitledCardContainer({pv}); "
                f"self.widgets[{wid!r}].set_title({p('title', '')}); "
                f"self.widgets[{wid!r}].setBorderRadius({max(0, int(props.get('radius', 8)))})")

    # Display / Composite widgets
    if wtype == "ImageDisplay":
        from app.core.image_runtime import ImageDisplay
        code = [f"self.widgets[{wid!r}] = ImageDisplay({pv})"]
        for prop, method, default in ImageDisplay.PROPERTY_SETTERS:
            value = props.get(prop, default)
            if value != default:
                argument = (f"str(Path(__file__).resolve().parent / {value!r})" if prop == "imagePath"
                            else repr(value))
                code.append(f"self.widgets[{wid!r}].{method}({argument})")
        return "; ".join(code)
    if wtype == "ProgressRingDisplay":
        label = p("label", "进度")  # i18n: value
        return (f"self.widgets[{wid!r}] = ProgressRingDisplay({pv}); "
                f"self.widgets[{wid!r}].set_label({label}); "
                f"self.widgets[{wid!r}].set_maximum({props.get('maximum', 100)}); "
                f"self.widgets[{wid!r}].set_value({props.get('value', 0)})")
    if wtype in ("LogBox", "LogDisplayBox"):
        return (f"self.widgets[{wid!r}] = LogDisplayBox({pv}); "
                f"self.widgets[{wid!r}].set_max_lines({p('maxLines', 500)})")
    if wtype in LINK_CARD_TYPES:
        from app.core.serial_card import SerialConfigCard
        from app.core.tcp_card import TcpConfigCard
        from app.core.udp_card import UdpConfigCard
        from app.core.mqtt_card import MqttConfigCard
        card = {"SerialConfigCard": SerialConfigCard, "TcpConfigCard": TcpConfigCard,
                "UdpConfigCard": UdpConfigCard, "MqttConfigCard": MqttConfigCard}[wtype]
        code = [f"self.widgets[{wid!r}] = {wtype}({pv})"]
        for prop, method, default in card.PROPERTY_SETTERS:
            code.append(f"self.widgets[{wid!r}].{method}({props.get(prop, default)!r})")
        return "; ".join(code)
    if wtype == "DataSendCard":
        title = p("title", "数据发送")  # i18n: value
        placeholder = p("placeholder", "输入要发送的数据...")  # i18n: value
        return (f"self.widgets[{wid!r}] = DataSendCard({pv}); "
                f"self.widgets[{wid!r}].set_title({title}); "
                f"self.widgets[{wid!r}].set_placeholder({placeholder})")
    if wtype == "DataRecvCard":
        title = p("title", "数据接收")  # i18n: value
        return (f"self.widgets[{wid!r}] = DataRecvCard({pv}); "
                f"self.widgets[{wid!r}].set_title({title}); "
                f"self.widgets[{wid!r}].set_max_lines({p('maxLines', 1000)})")
    if wtype == "ModbusSlaveTable":
        area = p("mbArea", "保持寄存器")  # i18n: value
        display_format = p("displayFormat", "无符号")  # i18n: value
        return (f"self.widgets[{wid!r}] = ModbusSlaveTable({pv}); "
                f"self.widgets[{wid!r}].set_area({area}); "
                f"self.widgets[{wid!r}].set_display_format({display_format})")

    return f"self.widgets[{wid!r}] = QLabel(tr('未知控件: %1', {wtype!r}), {pv})"


def _gen_serial_handler(serial_config: dict) -> str:
    # The parsers, the Modbus master every link owns, the Modbus slave a serial, TCP or UDP link may answer
    # with, then the serial link.
    master = _runtime("modbus_master.py").replace(
        "from .protocol_parser import build_modbus_ascii_frame, build_modbus_frame, build_modbus_tcp_frame", "")
    slave = _runtime("modbus_slave.py").replace(
        "from .protocol_parser import BaseParser, modbus_crc", "")
    slave_link = _runtime("slave_runtime.py").replace(
        "from .modbus_slave import DEFAULT_AREA, TABLES, ModbusSlave, SlaveStore, request_framer", "")
    runtime = _runtime("serial_runtime.py").replace(
        "from .protocol_parser import BaseParser, ModbusRequests, create_parser, text_encoding", "").replace(
        "from .modbus_master import ModbusMaster", "").replace(
        "from .modbus_slave import SLAVE_PARSERS", "")
    return (_runtime("protocol_parser.py") + "\n" + master + "\n" + slave + "\n" + slave_link + "\n"
            + runtime + f"\nSerialHandler.DEFAULT_CONFIG = {serial_config!r}\n")


def _link_config(serial_config: dict) -> dict:
    """TCP, UDP and MQTT share the project's frame format; the port settings are serial-only."""
    from app.core.comm_runtime import shared_link_config
    return shared_link_config(serial_config)


def _gen_tcp_handler(serial_config: dict) -> str:
    runtime = _runtime("tcp_runtime.py").replace(
        "from .protocol_parser import ModbusRequests, create_parser, text_encoding",
        "from serial_handler import ModbusRequests, create_parser, text_encoding").replace(
        "from .modbus_master import ModbusMaster", "from serial_handler import ModbusMaster").replace(
        "from .modbus_slave import SLAVE_PARSERS", "from serial_handler import SLAVE_PARSERS")
    return runtime + f"\nTcpHandler.DEFAULT_CONFIG = {_link_config(serial_config)!r}\n"


def _gen_udp_handler(serial_config: dict) -> str:
    runtime = _runtime("udp_runtime.py").replace(
        "from .protocol_parser import ModbusRequests, create_parser, text_encoding",
        "from serial_handler import ModbusRequests, create_parser, text_encoding").replace(
        "from .modbus_master import ModbusMaster", "from serial_handler import ModbusMaster").replace(
        "from .modbus_slave import SLAVE_PARSERS", "from serial_handler import SLAVE_PARSERS")
    return runtime + f"\nUdpHandler.DEFAULT_CONFIG = {_link_config(serial_config)!r}\n"


def _gen_mqtt_handler(serial_config: dict) -> str:
    runtime = _runtime("mqtt_runtime.py").replace(
        "from .protocol_parser import ModbusRequests, create_parser, text_encoding",
        "from serial_handler import ModbusRequests, create_parser, text_encoding",
    ).replace("from .tls_runtime import system_ssl_context", "").replace(
        "from .modbus_master import ModbusMaster", "from serial_handler import ModbusMaster")
    return (_runtime("tls_runtime.py") + "\n" + runtime
            + f"\nMqttHandler.DEFAULT_CONFIG = {_link_config(serial_config)!r}\n")


def _gen_comm_hub() -> str:
    return _runtime("comm_runtime.py")


def _link_card_ids(widgets: list) -> list:
    """The ids of the link cards, in document order (as the preview creates them): the first whose
    link is connected and parses Modbus sets the Modbus poller's settings."""
    ids = []

    def walk(items):
        for w in items:
            if w["type"] in LINK_CARD_TYPES:
                ids.append(w["id"])
            walk(w.get("children", []))
    walk(widgets)
    return ids


def _extract_bindings(widgets: list) -> list:
    bindings = []
    def _walk(items):
        for w in items:
            b = w.get("binding")
            if b:
                pm = b.get("parseMode", "键值匹配")  # i18n: value
                has_config = (
                    (pm == "键值匹配" and b.get("key"))  # i18n: value
                    or (pm == "JSON路径" and b.get("jsonPath"))  # i18n: value
                    or (pm == "HEX字节提取")  # i18n: value
                    or (pm == "Modbus")
                )
                if has_config:
                    props = w.get("properties", {})
                    entry = {
                        "widget_id": w["id"],
                        "type": w["type"],
                        "parseMode": pm,
                        "key": b.get("key", ""),
                        "jsonPath": b.get("jsonPath", ""),
                        "byteOffset": int(b.get("byteOffset", 0)),
                        "dataType": b.get("dataType", "uint16"),
                        "byteOrder": b.get("byteOrder", "大端(BE)"),  # i18n: value
                        "expression": b.get("expression"),
                        "displayFormat": props.get("displayFormat", "自动"),  # i18n: value
                        "decimals": str(props.get("decimals", "自动")),  # i18n: value
                        "frameHeader": b.get("frameHeader", ""),
                        "frameTail": b.get("frameTail", ""),
                        "mbRegIndex": int(b.get("mbRegIndex", 0)),
                        "mbDataType": b.get("mbDataType", "uint16"),
                        "mbRegOrder": b.get("mbRegOrder", "大端(AB CD)"),  # i18n: value
                        "mbFcFilter": int(b.get("mbFcFilter", -1)),
                        "mbSlaveFilter": int(b.get("mbSlaveFilter", -1)),
                        "mbArea": b.get("mbArea", "保持寄存器"),  # i18n: value
                        "mbPeriod": int(b.get("mbPeriod", 0)),
                    }
                    if w["type"] == "LEDIndicator":
                        entry["onValue"] = str(props.get("onValue", "1"))
                        entry["offValue"] = str(props.get("offValue", "0"))
                    bindings.append(entry)
            _walk(w.get("children", []))
    _walk(widgets)
    return bindings


def _gen_data_binding(bindings: list, widget_types: set = None, link_cards: list = ()) -> str:
    has_parsed = any(b["parseMode"] in ("键值匹配", "JSON路径", "Modbus") for b in bindings)  # i18n: value
    has_hex = any(b["parseMode"] == "HEX字节提取" for b in bindings)  # i18n: value
    has_chart = widget_types and "RealtimeChart" in widget_types

    lines = [
        '# coding: utf-8',
        '"""Auto-generated data binding."""',
        'import struct',
        'from PyQt5.QtCore import QSignalBlocker',
    ]
    if has_chart:
        lines.append('from ui import RealtimeLineChart')
    if widget_types and "Slider" in widget_types:
        lines.append('from ui import slider_of')
    if has_hex:
        lines.append('from serial_handler import RawFrameBuffer')
    lines.append('')
    lines.append(_runtime("binding_values.py"))
    lines.append(_runtime("signal_lifetime.py"))
    lines.append(_runtime("modbus_poller.py").replace(
        "from .modbus_master import", "from serial_handler import").replace(
        "from .signal_lifetime import SignalConnections", ""))

    lines += [
        '',
        'def _format_display(value, fmt):',
        '    if fmt == "' + "自动" + '": return value',  # i18n: value
        '    try:',
        '        num = int(float(value)) if not isinstance(value, int) else value',
        '    except (ValueError, TypeError, OverflowError): return value',
        '    if fmt == "' + "十六进制(HEX)" + '":',  # i18n: value
        '        return f"0x{num:02X}" if num >= 0 else f"-0x{abs(num):02X}"',
        '    if fmt == "' + "二进制(BIN)" + '":',  # i18n: value
        '        return f"0b{num:08b}" if num >= 0 else f"-0b{abs(num):08b}"',
        '    if fmt == "' + "十进制" + '": return str(num)',  # i18n: value
        '    return value',
        '',
        '',
        'def _resolve_path(data, path):',
        '    for part in path.split("."):',
        '        if data is None: return None',
        '        if isinstance(data, dict): data = data.get(part)',
        '        elif isinstance(data, (list, tuple)):',
        '            try: data = data[int(part)]',
        '            except (ValueError, IndexError): return None',
        '        else: return None',
        '    return data',
        '',
        '',
        '_STRUCT_FMT = {',
        '    "uint8": ("B", 1), "int8": ("b", 1),',
        '    "uint16": ("H", 2), "int16": ("h", 2),',
        '    "uint32": ("I", 4), "int32": ("i", 4),',
        '    "float32": ("f", 4),',
        '}',
        '',
        '',
        'class DataBinding:',
        '    """Wire the hub (the link cards\' links) to bound widgets and command senders."""',
        '    def __init__(self, ui, hub):',
        '        self.ui = ui',
        '        self.hub = hub',
        '        self._connections = SignalConnections(ui)',
        '        ui._comm_hub = hub',
        '        # Reads what the Modbus bindings and chart curves show; the link cards, in document',
        '        # order, register their own links on the hub, hand it their settings and show its status.',
        '        self.modbus_poller = ModbusPoller(hub, self.modbus_needs, ui)',
    ]
    if link_cards:
        lines += [
            f'        for widget_id in {list(link_cards)!r}:',
            '            ui.widgets[widget_id].set_serial_handler(hub)',
            '            ui.widgets[widget_id].set_modbus_poller(self.modbus_poller)',
        ]
    lines += [
        '        for w in ui.widgets.values():',
        '            if hasattr(w, "set_serial_handler"):',
        '                w.set_serial_handler(hub)  # the receive card, log box and data table listen to it',
    ]
    if has_chart:
        lines += [
            '            if isinstance(w, RealtimeLineChart):',
            '                w._serial_connections.clear()',
            '                w._serial_connections.connect(hub.dataReceived, w.on_parsed)',
            '                w._serial_connections.connect(hub.rawReceived, w.on_raw)',
            '                w._serial_connections.connect(hub.disconnected, w.reset_stream)',
        ]

    if has_hex:
        from app.core.data_binding import BindingEntry
        lines.append('        self._raw_frames = {}')
        for binding in bindings:
            if binding["parseMode"] == "HEX字节提取":  # i18n: value
                header = BindingEntry._hex_to_bytes(binding.get("frameHeader", ""))
                footer = BindingEntry._hex_to_bytes(binding.get("frameTail", ""))
                lines.append(f'        self._raw_frames[{binding["widget_id"]!r}] = '
                             f'RawFrameBuffer({header!r}, {footer!r})')
    if has_parsed:
        lines.append('        self._connections.connect(self.hub.dataReceived, self._on_data)')
    if has_hex:
        lines.append('        self._connections.connect(self.hub.rawReceived, self._on_raw)')
        lines.append('        self._connections.connect(self.hub.disconnected, self._reset_stream)')
    lines.append('        self.modbus_poller.start()  # reads once a link that parses Modbus can send')
    if widget_types and widget_types & {"SerialConfigCard", "TcpConfigCard", "UdpConfigCard", "ModbusSlaveTable"}:
        lines += [
            '        # The slaves of the link cards in the slave role: a register table shows the first one\'s, and',
            '        # each publishes its whole data table now that the bindings are up.',
            '        slaves = [w.slave_device for w in ui.widgets.values() if getattr(w, "slave_device", None)]',
            '        for w in ui.widgets.values():',
            '            if hasattr(w, "set_slave_device"):',
            '                w.set_slave_device(slaves[0] if slaves else None)',
            '        for device in slaves:',
            '            device.publish_start()',
        ]
    lines.append('')

    # -- _on_data for 键值匹配 / JSON路径 --
    if has_parsed:
        lines.append('    def _on_data(self, data: dict):')
        parsed_bindings = [b for b in bindings if b["parseMode"] in ("键值匹配", "JSON路径", "Modbus")]  # i18n: value
        for b in parsed_bindings:
            fragment = []
            _gen_binding_apply(fragment, b, source="parsed")
            lines.append('        try:')
            lines.extend('    ' + line if line else '' for line in fragment)
            lines.append('        except (TypeError, ValueError, OverflowError, struct.error):')
            lines.append('            pass')
        if not parsed_bindings:
            lines.append('        pass')
        lines.append('')

    # -- _on_raw for HEX字节提取 --
    if has_hex:
        lines += [
            '    def _reset_stream(self):',
            '        for frames in self._raw_frames.values(): frames.reset()',
            '',
        ]
        lines.append('    def _on_raw(self, raw: bytes):')
        hex_bindings = [b for b in bindings if b["parseMode"] == "HEX字节提取"]  # i18n: value
        for index, b in enumerate(hex_bindings):
            lines.append(f'        for frame in self._raw_frames[{b["widget_id"]!r}].feed(raw):')
            lines.append('            try:')
            lines.append(f'                self._raw_binding_{index}(frame)')
            lines.append('            except (TypeError, ValueError, OverflowError, struct.error):')
            lines.append('                pass')
        if not hex_bindings:
            lines.append('        pass')
        lines.append('')
        for index, b in enumerate(hex_bindings):
            lines.append(f'    def _raw_binding_{index}(self, raw):')
            _gen_binding_apply(lines, b, source="raw")

    lines += _gen_modbus_needs(bindings)
    return "\n".join(lines).rstrip() + "\n"


def _gen_modbus_needs(bindings: list) -> list:
    """DataBinding.modbus_needs: what the Modbus poller reads, as data_binding's engine lists it."""
    from app.core.binding_values import modbus_need
    needs = []
    for b in bindings:
        if b["parseMode"] == "Modbus":
            need = modbus_need(b["mbArea"], b["mbRegIndex"], b["mbDataType"], b["mbSlaveFilter"], b["mbPeriod"])
            if need is not None:
                needs.append((b["widget_id"], *need))
    return [
        '    # (widget id, slave, table, address, count, period) of each Modbus binding',
        f'    _MODBUS_NEEDS = {needs!r}',
        '',
        '    def modbus_needs(self):',
        '        """Bindings count while their widget is on screen; chart curves always."""',
        '        needs = []',
        '        for widget_id, *need in self._MODBUS_NEEDS:',
        '            w = self.ui.widgets.get(widget_id)',
        '            needs.append((widget_id, *need, w is not None and w.isVisible()))',
        '        for widget_id, w in self.ui.widgets.items():',
        '            curves = getattr(w, "modbus_needs", None)  # charts read their own curves',
        '            if callable(curves):',
        '                needs.extend((widget_id, *need, True) for need in curves())',
        '        return needs',
        '',
    ]


def _gen_binding_apply(lines: list, b: dict, source: str):
    """Generate the value extraction + widget apply code for one binding."""
    wid = b["widget_id"]
    wtype = b["type"]
    expr = b.get("expression")
    dfmt = b.get("displayFormat", "自动")  # i18n: value
    pm = b["parseMode"]

    if source == "parsed":
        if pm == "键值匹配":  # i18n: value
            key = b["key"]
            lines.append(f"        if {key!r} in data and data[{key!r}] is not None:")
            lines.append(f"            value = data[{key!r}]")
        elif pm == "JSON路径":  # i18n: value
            jp = b["jsonPath"]
            lines.append(f"        value = _resolve_path(data, {repr(jp)})")
            lines.append(f"        if value is not None:")
        elif pm == "Modbus":
            args = (b.get("mbRegIndex", 0), b.get("mbDataType", "uint16"),
                    b.get("mbRegOrder", "大端(AB CD)"), b.get("mbFcFilter", -1),  # i18n: value
                    b.get("mbSlaveFilter", -1), b.get("mbArea", "保持寄存器"))  # i18n: value
            lines.append(f"        value = modbus_value(data, {', '.join(map(repr, args))})")
            lines.append(f"        if value is not None:")
    elif source == "raw":
        off = b["byteOffset"]
        dt = b["dataType"]
        bo_str = b.get("byteOrder", "大端(BE)")  # i18n: value
        from app.core.data_binding import BindingEntry
        fh = BindingEntry._hex_to_bytes(b.get("frameHeader", ""))
        ft = BindingEntry._hex_to_bytes(b.get("frameTail", ""))
        raw_var = "raw"
        if fh or ft:
            lines.append(f"        _payload = raw")
            if fh:
                lines.append(f"        _hdr = {fh!r}")
                lines.append(f"        _hi = _payload.find(_hdr)")
                lines.append(f"        if _hi < 0: return")
                lines.append(f"        _payload = _payload[_hi + len(_hdr):]")
            if ft:
                lines.append(f"        _tlr = {ft!r}")
                lines.append(f"        _ti = _payload.find(_tlr)")
                lines.append(f"        if _ti < 0: return")
                lines.append(f"        _payload = _payload[:_ti]")
            raw_var = "_payload"
        if dt == "ASCII":
            lines.append(f"        if 0 <= {off} <= len({raw_var}):")
            lines.append(f"            value = {raw_var}[{off}:{raw_var}.find(0, {off}) if {raw_var}.find(0, {off}) >= 0 else len({raw_var})].decode('ascii', errors='replace')")
        else:
            fmt_info = {"uint8": ("B", 1), "int8": ("b", 1), "uint16": ("H", 2),
                        "int16": ("h", 2), "uint32": ("I", 4), "int32": ("i", 4),
                        "float32": ("f", 4)}.get(dt, ("H", 2))
            bo = ">" if bo_str == "大端(BE)" else "<"  # i18n: value
            lines.append(f"        if len({raw_var}) >= {off + fmt_info[1]}:")
            lines.append(f"            value = struct.unpack('{bo}{fmt_info[0]}', {raw_var}[{off}:{off + fmt_info[1]}])[0]")

    indent = "            " if source == "parsed" else "            "

    if expr:
        lines.append(f"{indent}try:")
        lines.append(f"{indent}    value = eval({repr(expr)}, {{'__builtins__': {{}}}}, {{'value': value}})")
        lines.append(f"{indent}except Exception: pass")

    need_format = dfmt != "自动" and wtype in ("Label", "LineEdit", "NumericDisplay")  # i18n: value
    if need_format:
        lines.append(f"{indent}value = _format_display(value, {repr(dfmt)})")
    places = b.get("decimals", "自动")  # i18n: value
    if not need_format and places != "自动" and wtype in ("Label", "NumericDisplay"):  # i18n: value
        lines.append(f"{indent}value = binding_decimals(value, {places!r})")

    lines.append(f"{indent}w = self.ui.widgets.get({wid!r})")
    lines.append(f"{indent}if w:")

    if wtype in ("Label", "LineEdit"):
        lines.append(f"{indent}    w.setText(str(value))")
    elif wtype == "NumericDisplay":
        lines.append(f"{indent}    w.set_value(str(value))")
    elif wtype == "LEDIndicator":
        on_val = b.get("onValue", "1")
        off_val = b.get("offValue", "0")
        lines.append(f"{indent}    w.set_on(binding_led(value, {on_val!r}, {off_val!r}))")
    elif wtype == "ProgressBar":
        lines.append(f"{indent}    w.setValue(binding_integer(value))")
    elif wtype == "ProgressRingDisplay":
        lines.append(f"{indent}    w.set_value(binding_integer(value))")
    elif wtype == "GaugeMeter":
        lines.append(f"{indent}    w.set_value(binding_float(value))")
    elif wtype in ("Slider", "SpinBox"):
        # A slider may sit in a row with its limits; the Slider inside is the one that is bound.
        control = "slider_of(w)" if wtype == "Slider" else "w"
        lines.append(f"{indent}    value = binding_integer(value)")
        lines.append(f"{indent}    with QSignalBlocker({control}):")
        lines.append(f"{indent}        {control}.setValue(value)")
        if wtype == "Slider":
            lines.append(f"{indent}    # Fluent normally moves its handle in the blocked valueChanged signal.")
            lines.append(f"{indent}    {control}._adjustHandlePos()")
    elif wtype == "ToggleSwitch":
        lines.append(f"{indent}    value = binding_boolean(value)")
        lines.append(f"{indent}    with QSignalBlocker(w._switch):")
        lines.append(f"{indent}        w._switch.setChecked(value)")
    else:
        lines.append(f"{indent}    if hasattr(w, 'setText'): w.setText(str(value))")
    lines.append("")


# ---------------------------------------------------------------------------
# Embedded widget class source code for generated projects
# ---------------------------------------------------------------------------

def _led_class() -> str:
    return '''
class LEDIndicator(QWidget):
    COLOR_MAP = {
        "green": QColor(76, 175, 80), "red": QColor(244, 67, 54),
        "yellow": QColor(255, 193, 7), "blue": QColor(33, 150, 243),
        "gray": QColor(158, 158, 158),
    }
    def __init__(self, parent=None):
        super().__init__(parent)
        self._color_name = "green"
        self._on = True
        self._label_text = ""
        self.setMinimumSize(20, 20)
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self.update)
    def set_color(self, name): self._color_name = name; self.update()
    def set_on(self, on): self._on = on; self.update()
    def set_label(self, text): self._label_text = text; self.update()
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = self.COLOR_MAP.get(self._color_name, QColor(76, 175, 80))
        if not self._on: color = QColor("#777777" if isDarkTheme() else "#c8c8c8")
        size = min(self.height(), 30)
        painter.setBrush(color); painter.setPen(Qt.NoPen)
        painter.drawEllipse(4, (self.height()-size)//2, size, size)
        painter.setBrush(Qt.NoBrush); painter.setPen(color.darker(120))
        painter.drawEllipse(4, (self.height()-size)//2, size, size)
        if self._label_text:
            painter.setPen(QColor("#f3f3f3" if isDarkTheme() else "#3c3c3c"))
            painter.setFont(QFont(self.font().family(), 10))
            painter.drawText(size+12, 0, self.width()-size-12, self.height(), Qt.AlignVCenter, self._label_text)
        painter.end()
'''


def _numeric_display_class() -> str:
    return '''
class NumericDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,4,8,4); layout.setSpacing(0)
        self._title = CaptionLabel(tr("标题"))
        self._value = BodyLabel("0.00")
        self._unit = CaptionLabel("")
        for label in (self._title, self._unit):
            label.setTextColor(QColor("#606060"), QColor("#b3b3b3"))
        self._unit.setMinimumHeight(self._unit.fontMetrics().height())  # an empty unit keeps its line
        for label in (self._title, self._value, self._unit):
            label.setAlignment(Qt.AlignCenter); layout.addWidget(label)
        self._update_value_style()
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self._update_value_style)
        self._theme_connections.connect(qconfig.themeColorChanged, self._update_value_style)
    def set_title(self, t): self._title.setText(t)
    def set_value(self, v): self._value.setText(str(v))
    def set_unit(self, u): self._unit.setText(u)
    def set_value_color(self, color):
        self._val_color = color
        self._update_value_style()
    def set_font_size(self, size):
        self._val_font_size = size
        self._update_value_style()
    def _update_value_style(self):
        color = QColor(getattr(self, "_val_color", None) or themeColor())
        font = self._value.font()
        font.setPixelSize(getattr(self, "_val_font_size", 28)); font.setBold(True)
        self._value.setFont(font)
        self._value.setTextColor(color, color)
'''


def _realtime_chart_class() -> str:
    runtime = _runtime("chart_runtime.py").replace(
        "from .chart_history import ChartHistory", "").replace(
        "from .binding_values import modbus_need, modbus_value", "").replace(
        "from .signal_lifetime import SignalConnections", "").replace(
        "from .protocol_parser import RawFrameBuffer",
        "from serial_handler import RawFrameBuffer")
    return (_runtime("signal_lifetime.py") + "\n"
            + _runtime("binding_values.py") + "\n"
            + _runtime("chart_history.py") + "\n" + runtime)


def _gauge_class() -> str:
    return _runtime("gauge_runtime.py").replace(
        "from .signal_lifetime import SignalConnections", "")


def _serial_terminal_class() -> str:
    return '''
from qfluentwidgets import TextEdit as _FTextEdit, LineEdit as _FLineEdit, PushButton as _FPushButton

class SerialTerminal(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(4,4,4,4)
        self._output = _FTextEdit(); self._output.setReadOnly(True)
        terminal_style = "QTextEdit { font-family:Menlo,Consolas,monospace;font-size:12px;background:#1e1e1e;color:#d4d4d4; }"
        setCustomStyleSheet(self._output, terminal_style, terminal_style)
        layout.addWidget(self._output, 1)
        row = QHBoxLayout()
        self._input = _FLineEdit(); self._input.setPlaceholderText(tr("输入命令..."))
        self._send_btn = _FPushButton(tr("发送"))
        row.addWidget(self._input, 1); row.addWidget(self._send_btn)
        layout.addLayout(row)
    def append_received(self, text): self._output.append(f"<< {text}")
    def append_sent(self, text): self._output.append(f">> {text}")
'''


def _titled_container_classes() -> str:
    return '''
class TitledLayoutContainer(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = ""
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self.update)
    def set_title(self, title):
        self._title = title
        self.update()
    def paintEvent(self, event):
        super().paintEvent(event)
        if self._title:
            painter = QPainter(self)
            painter.setPen(QColor("#b3b3b3" if isDarkTheme() else "#606060"))
            painter.setFont(QFont(self.font().family(), 8))
            painter.drawText(6, 14, self._title)
            painter.end()

class TitledCardContainer(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = ""
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self.update)
    def set_title(self, title):
        self._title = title
        self.update()
    def paintEvent(self, event):
        super().paintEvent(event)
        if self._title:
            painter = QPainter(self)
            painter.setPen(QColor("#b3b3b3" if isDarkTheme() else "#606060"))
            painter.setFont(QFont(self.font().family(), 9))
            painter.drawText(12, 18, self._title)
            painter.end()
'''


def _data_table_class() -> str:
    return _runtime("table_runtime.py").replace(
        "from .signal_lifetime import SignalConnections", "")


def _image_display_class() -> str:
    return _runtime("image_runtime.py").replace(
        "from .signal_lifetime import SignalConnections", "")


def _progress_ring_display_class() -> str:
    return '''
class ProgressRingDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self); lo.setContentsMargins(4,4,4,4)
        lo.setAlignment(Qt.AlignCenter); lo.setSpacing(4)
        self._ring = ProgressRing(); self._ring.setRange(0,100); self._ring.setValue(0)
        self._ring.setFixedSize(80,80)
        self._ring.setTextVisible(True)
        self._lbl = CaptionLabel(tr("进度")); self._lbl.setAlignment(Qt.AlignCenter)
        lo.addWidget(self._ring, 0, Qt.AlignCenter)
        lo.addWidget(self._lbl)
    def set_label(self, t): self._lbl.setText(t)
    def set_value(self, v): self._ring.setValue(int(v))
    def set_maximum(self, m): self._ring.setMaximum(int(m))
'''


def _log_display_class() -> str:
    return _runtime("log_runtime.py").replace(
        "from .signal_lifetime import SignalConnections", "")


def _serial_config_card_class() -> str:
    return _runtime("serial_card.py").replace(
        "from .serial_runtime import SerialHandler, _list_all_ports",
        "from serial_handler import SerialHandler, _list_all_ports"
    ).replace("from .signal_lifetime import SignalConnections", "").replace(
        "from .link_polling import (CARD_PARSERS, FULL_MODE, ONE_LINE_MODE, SLAVE_PROPERTY_SETTERS, ModbusSlaveSettings,\n"
        "                           add_value_items, fluent_tooltip, select_value, status_label)", "")


def _link_polling_source() -> str:
    return _runtime("link_polling.py").replace(
        "from .signal_lifetime import SignalConnections", "").replace(
        "from .slave_runtime import ModbusSlaveDevice", "from serial_handler import ModbusSlaveDevice").replace(
        "from .modbus_slave import MASTER_ROLE, SLAVE_ROLE", "from serial_handler import MASTER_ROLE, SLAVE_ROLE")


def _slave_table_class() -> str:
    return _runtime("slave_table.py").replace(
        "from .modbus_slave import AREA_TABLES", "from serial_handler import AREA_TABLES")


def _link_card_class() -> str:
    return _runtime("link_card.py").replace(
        "from .signal_lifetime import SignalConnections", "").replace(
        "from .link_polling import CARD_PARSERS, FULL_MODE, ModbusLinkSettings, add_value_items, select_value, status_label",
        "")


def _tcp_config_card_class() -> str:
    return _runtime("tcp_card.py").replace(
        "from .link_card import LinkConfigCard", "").replace(
        "from .link_polling import SLAVE_PROPERTY_SETTERS, ModbusSlaveSettings, add_value_items, select_value",
        "").replace("from .tcp_runtime import CLIENT, SERVER, TcpHandler",
                    "from tcp_handler import CLIENT, SERVER, TcpHandler")


def _udp_config_card_class() -> str:
    return _runtime("udp_card.py").replace(
        "from .link_card import LinkConfigCard", "").replace(
        "from .link_polling import SLAVE_PROPERTY_SETTERS, ModbusSlaveSettings", "").replace(
        "from .udp_runtime import UdpHandler", "from udp_handler import UdpHandler")


def _mqtt_config_card_class() -> str:
    return _runtime("mqtt_card.py").replace(
        "from .link_card import LinkConfigCard", "").replace(
        "from .mqtt_runtime import MqttHandler", "from mqtt_handler import MqttHandler")


def _data_send_card_class() -> str:
    return '''
class DataSendCard(CardWidget):
    """Data send card for generated code."""
    _NEWLINES = {"无": "", "\\\\r\\\\n": "\\r\\n", "\\\\n": "\\n", "\\\\r": "\\r"}  # i18n: value
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root = QVBoxLayout(self); root.setContentsMargins(16,12,16,12); root.setSpacing(8)
        self._title = StrongBodyLabel(tr("数据发送")); root.addWidget(self._title)
        row = QHBoxLayout()
        self._input = LineEdit(); self._input.setPlaceholderText(tr("输入要发送的数据..."))
        self._send_btn = PrimaryPushButton(FIF.SEND, tr("发送"))
        self._send_btn.clicked.connect(self._do_send)
        self._input.returnPressed.connect(self._do_send)
        row.addWidget(self._input, 1); row.addWidget(self._send_btn)
        root.addLayout(row)
        options = QHBoxLayout(); options.setSpacing(8)
        self._hex_cb = CheckBox(tr("HEX模式"))
        self._newline_combo = ComboBox()
        for newline in self._NEWLINES: self._newline_combo.addItem(tr(newline), userData=newline)
        self._newline_combo.setCurrentIndex(1); self._newline_combo.setFixedWidth(80)
        options.addWidget(self._hex_cb); options.addStretch()
        options.addWidget(BodyLabel(tr("换行符"))); options.addWidget(self._newline_combo)
        root.addLayout(options)
        self._handler = None
    def set_serial_handler(self, h): self._handler = h
    def set_title(self, title): self._title.setText(title)
    def set_placeholder(self, text): self._input.setPlaceholderText(text)
    def _do_send(self):
        if not self._handler or not self._handler.is_connected: return
        text = self._input.text().strip()
        if not text: return
        if self._hex_cb.isChecked():
            hx = text.replace(" ","")
            if len(hx)%2: hx = "0"+hx
            try: self._handler.send(bytes.fromhex(hx))
            except ValueError: pass
        else:
            self._handler.send_text(text + self._NEWLINES[self._newline_combo.currentData()])
        self._input.selectAll()
'''


def _data_recv_card_class() -> str:
    return '''
from datetime import datetime as _dt

class DataRecvCard(CardWidget):
    """Data receive card for generated code."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root = QVBoxLayout(self); root.setContentsMargins(12,10,12,10); root.setSpacing(6)
        hdr = QHBoxLayout()
        self._title_lbl = StrongBodyLabel(tr("数据接收")); hdr.addWidget(self._title_lbl)
        hdr.addStretch()
        self._counter = CaptionLabel(tr("%1 条", 0))
        self._counter.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        hdr.addWidget(self._counter)
        root.addLayout(hdr)
        opt = QHBoxLayout(); opt.setSpacing(8)
        self._hex_cb = CheckBox(tr("HEX显示")); opt.addWidget(self._hex_cb)
        self._scroll_cb = CheckBox(tr("自动滚动")); self._scroll_cb.setChecked(True); opt.addWidget(self._scroll_cb)
        for check in (self._hex_cb, self._scroll_cb):  # macOS would lay them out by a smaller rect
            check.setAttribute(Qt.WA_LayoutUsesWidgetRect)
        opt.addStretch()
        self._clear_btn = PushButton(tr("清空")); self._clear_btn.setFixedWidth(60)
        self._clear_btn.clicked.connect(self._clear); opt.addWidget(self._clear_btn)
        root.addLayout(opt)
        self._text = TextEdit(); self._text.setReadOnly(True)
        terminal_style = (
            "QTextEdit { font-family:Menlo,Consolas,'Courier New',monospace;font-size:12px;"
            "background:#1e1e2e;color:#cdd6f4;border-radius:4px;padding:4px; }")
        setCustomStyleSheet(self._text, terminal_style, terminal_style)
        bar = self._text.scrollDelegate.vScrollBar  # light on the dark terminal in both themes
        bar.setHandleColor(QColor(168, 216, 234, 110), QColor(168, 216, 234, 110))
        bar.setArrowColor(QColor(168, 216, 234, 160), QColor(168, 216, 234, 160))
        bar.setGrooveColor(QColor(36, 36, 60, 235), QColor(36, 36, 60, 235))
        root.addWidget(self._text, 1)
        self._count = 0; self._max_lines = 1000; self._handler = None
        self._serial_connections = SignalConnections(self)
    def set_serial_handler(self, h):
        if h is self._handler: return
        self._serial_connections.clear()
        self._handler = h
        if h is not None:
            self._serial_connections.connect(h.rawReceived, self._on_raw)
            self._serial_connections.connect(h.dataSent, self._on_sent)
            self._serial_connections.connect(h.connected, self._on_connected)
            self._serial_connections.connect(h.disconnected, self._on_disconnected)
    def _on_connected(self, port): self._sys(tr("已连接: %1", port))
    def _on_disconnected(self): self._sys(tr("已断开"))
    def _on_raw(self, data):
        ts = _dt.now().strftime("%H:%M:%S.%f")[:-3]
        if self._hex_cb.isChecked():
            txt = " ".join(f"{b:02X}" for b in data)
        else:
            decode = getattr(self._handler, "decode_raw", None)  # the hub knows the link's encoding
            txt = (decode(data) if decode else data.decode("utf-8", errors="replace")).rstrip("\\r\\n")
            if not txt: return
        self._text.append(f\'<span style="color:#9399b2">[{ts}]</span> \'
                          f\'<span style="color:#a6e3a1">&lt;&lt; {_log_html(txt)}</span>\')
        self._count += 1; self._counter.setText(tr("%1 条", self._count))
        self._trim(); self._do_scroll()
    def _on_sent(self, data):
        ts = _dt.now().strftime("%H:%M:%S.%f")[:-3]
        if self._hex_cb.isChecked():
            txt = " ".join(f"{b:02X}" for b in data)
        else:
            txt = data.decode("utf-8", errors="replace").rstrip("\\r\\n")
            if not txt: return
        self._text.append(f\'<span style="color:#9399b2">[{ts}]</span> \'
                          f\'<span style="color:#f9e2af">&gt;&gt; {_log_html(txt)}</span>\')
        self._trim(); self._do_scroll()
    def _sys(self, msg):
        ts = _dt.now().strftime("%H:%M:%S")
        self._text.append(f\'<span style="color:#74c7ec">[{ts}] --- {_log_html(msg)} ---</span>\')
        self._trim()
    def _do_scroll(self):
        if self._scroll_cb.isChecked():
            sb = self._text.verticalScrollBar(); sb.setValue(sb.maximum())
    def _clear(self):
        self._text.clear(); self._count = 0; self._counter.setText(tr("%1 条", 0))
    def _trim(self):
        doc = self._text.document()
        while doc.blockCount() > self._max_lines:
            c = self._text.textCursor(); c.movePosition(c.Start)
            c.select(c.BlockUnderCursor); c.removeSelectedText(); c.deleteChar()
    def set_title(self, t): self._title_lbl.setText(t)
    def set_max_lines(self, count):
        self._max_lines = max(50, count)
        self._trim()
'''

