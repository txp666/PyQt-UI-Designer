# coding: utf-8
"""Auto-generated UI module."""
import struct, math, json
from html import escape as _html_escape

def _log_html(text):
    return _html_escape(str(text)).replace("\n", "<br>")
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QScrollArea, QFrame, QGroupBox, QTabWidget, QTextEdit, QCheckBox,
    QSizePolicy, QHeaderView, QAbstractItemView, QTableWidget, QTableWidgetItem,
    QSpinBox, QPushButton, QFileDialog, QLineEdit,
)
from PyQt5.QtGui import QColor, QPainter, QFont, QPen, QConicalGradient, QPixmap

from qfluentwidgets import (
    PushButton, PrimaryPushButton, BodyLabel, StrongBodyLabel,
    CaptionLabel, LineEdit, ComboBox, TextEdit, CheckBox,
    SwitchButton, Slider, SpinBox, ProgressBar, ProgressRing,
    CardWidget, TableWidget, ToolButton,
    FluentWindow, NavigationItemPosition,
    FluentIcon as FIF, InfoBar, InfoBarPosition, isDarkTheme,
    qconfig, setCustomStyleSheet,
)

from serial_handler import _list_all_ports

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False


"""Explicit Qt signal lifetimes, including compiled Python callables."""


class SignalConnections:
    """Disconnect external signals when their owning QObject is destroyed.

    PyQt cannot always infer the QObject receiver of a compiled bound method.
    Relays therefore have an explicit lifetime and release their callback before
    disconnecting, so already queued deliveries also become harmless.
    """

    def __init__(self, owner):
        self._connections = []
        owner.destroyed.connect(self.clear)

    def connect(self, signal, slot, *args, **kwargs):
        callback = [slot]

        def relay(*values):
            current = callback[0]
            if current is not None:
                current(*values)

        connection = signal.connect(relay, *args, **kwargs)
        self._connections.append((signal, connection, callback))
        return connection

    def clear(self, *_):
        connections, self._connections = self._connections, []
        for _signal, _connection, callback in connections:
            callback[0] = None
        for signal, connection, _callback in connections:
            try:
                signal.disconnect(connection)
            except (TypeError, RuntimeError):
                # The sender or its connection may already have been destroyed.
                pass

"""Explicit lifetimes for Fluent's external window and configuration signals."""
from functools import update_wrapper


def _bridge_fluent_slot(cls, name, argument_count):
    original = getattr(cls, name)
    if getattr(original, "_designer_signal_lifetimes", False):
        return

    # PyQt recognizes genuine Python bound methods as QObject receivers, but
    # not Nuitka's compiled_method objects. Runtime-created functions keep this
    # distinction in a compiled app. Exact arity also preserves Qt's argument
    # truncation (themeChanged supplies a Theme to a zero-argument handler).
    parameters = ", value" if argument_count else ""
    values = "value" if argument_count else ""
    namespace = {}
    exec(
        f"def {name}(self{parameters}):\n"
        f"    return _original.__get__(self, type(self))({values})\n",
        {"_original": original}, namespace,
    )
    bridge = namespace[name]
    update_wrapper(bridge, original)
    bridge._designer_signal_lifetimes = True
    setattr(cls, name, bridge)


def install_fluent_signal_lifetimes():
    """Give Fluent's long-lived signals QObject-aware slots before creation."""
    from qfluentwidgets import (
        OptionsSettingCard, SwitchSettingCard, RangeSettingCard,
        ColorSettingCard, ComboBoxSettingCard,
    )
    from qfluentwidgets.common.animation import BackgroundAnimationWidget
    from qfluentwidgets.components.widgets.stacked_widget import PopUpAniStackedWidget
    from qfluentwidgets.window.fluent_window import FluentWidget, FluentTitleBar

    _bridge_fluent_slot(BackgroundAnimationWidget, "_updateBackgroundColor", 0)
    # Page animations have no QObject parent and can finish after the window is gone.
    _bridge_fluent_slot(PopUpAniStackedWidget, "_PopUpAniStackedWidget__onAniFinished", 0)
    _bridge_fluent_slot(FluentWidget, "_onThemeChangedFinished", 0)
    _bridge_fluent_slot(FluentTitleBar, "setTitle", 1)
    _bridge_fluent_slot(FluentTitleBar, "setIcon", 1)
    for cls in (OptionsSettingCard, SwitchSettingCard, RangeSettingCard,
                ColorSettingCard, ComboBoxSettingCard):
        _bridge_fluent_slot(cls, "setValue", 1)


class TitleBarLifecycleMixin:
    """Install QObject-aware slots before Fluent creates its widget tree.

    FluentWindow replaces its initial FluentWidgetTitleBar during construction.
    Both title bars must connect the Python bridge from the start: retrieving a
    fresh compiled bound method later cannot reliably disconnect the first one.
    """

    def __init__(self, *args, **kwargs):
        install_fluent_signal_lifetimes()
        super().__init__(*args, **kwargs)

"""Command encoders shared by preview and standalone applications."""
import math
import struct

def _command_hex(text):
    """Accept whitespace and a leading half-byte, but never drop invalid fields."""
    compact = "".join(str(text).split())
    if len(compact) % 2:
        compact = "0" + compact
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("HEX 格式错误，请检查内容、帧头和帧尾") from exc


def command_hex_frame(command, header="", tail=""):
    return _command_hex(header) + _command_hex(command) + _command_hex(tail)


def command_packed_frame(value, fmt, cast=int, template="{value}", header="", tail=""):
    try:
        number = cast(value)
        if isinstance(number, float) and not math.isfinite(number):
            raise ValueError("non-finite value")
        payload = struct.pack(fmt, number)
    except (TypeError, ValueError, OverflowError, struct.error) as exc:
        raise ValueError("数值无效或超出数据类型范围") from exc
    return command_hex_frame(template.replace("{value}", payload.hex()), header, tail)


def modbus_request(slave, func, address, value):
    """Validate a Modbus request and return its integer fields."""
    try:
        slave, func, address, value = (int(item) for item in (slave, func, address, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Modbus 地址和值必须是整数") from exc
    if not 1 <= slave <= 247 or not 0 <= address <= 65535:
        raise ValueError("Modbus 从站地址或寄存器地址超出范围")
    if func in (1, 2):
        valid = 1 <= value <= 2000
    elif func in (3, 4):
        valid = 1 <= value <= 125
    elif func == 5:
        valid = value in (0, 0xFF00)
    elif func == 6:
        valid = 0 <= value <= 65535
    else:
        valid = False
    if not valid:
        raise ValueError("Modbus 值或读取数量超出功能码允许范围")
    return slave, func, address, value


def command_modbus_frame(slave, func, address, value):
    """A validated Modbus RTU request frame (CRC16 appended)."""
    slave, func, address, value = modbus_request(slave, func, address, value)
    from serial_handler import build_modbus_frame
    return build_modbus_frame(slave, func, address, value, value)


_transaction = [0]


def next_modbus_transaction():
    """Successive MBAP transaction identifiers, wrapping at 16 bits."""
    _transaction[0] = (_transaction[0] + 1) & 0xFFFF
    return _transaction[0]


def command_modbus_tcp_frame(slave, func, address, value, transaction=None):
    """A validated Modbus TCP request ADU (MBAP header, no CRC)."""
    slave, func, address, value = modbus_request(slave, func, address, value)
    from serial_handler import build_modbus_tcp_frame
    if transaction is None:
        transaction = next_modbus_transaction()
    return build_modbus_tcp_frame(slave, func, address, value, value, transaction)


def send_modbus_command(hub, slave, func, address, value):
    """Validate once, then send the request over every connected link, framed for that link.

    A link parsing Modbus TCP gets an MBAP frame, every other link an RTU frame. Returns
    the frames that were accepted; an invalid request raises before anything is sent.
    """
    request = modbus_request(slave, func, address, value)
    links = getattr(hub, "connected_links", None)
    if links is None:  # a single link rather than a hub
        links = [hub] if hub.is_connected else []
    frames = []
    for link in links:
        if getattr(link, "parser_type", "") == "modbus_tcp":
            frames.append((link, command_modbus_tcp_frame(*request)))
        else:
            frames.append((link, command_modbus_frame(*request)))
    return [frame for link, frame in frames if link.send(frame)]

"""Preserve the designer's tab-relative coordinates in real Qt tab pages."""
from PyQt5.QtCore import QObject, QEvent, QPoint, QRect, QTimer
from PyQt5 import sip


class TabChildGeometry(QObject):
    def __init__(self, tabs):
        super().__init__(tabs)
        self.tabs = tabs
        self._children = {}
        self._pending = False
        self._applying = False
        tabs.installEventFilter(self)
        tabs.currentChanged.connect(self.schedule)

    def register(self, child, geometry):
        self._children[child] = QRect(*geometry)
        page = child.parentWidget()
        page.installEventFilter(self)
        page.parentWidget().installEventFilter(self)
        self.apply()
        self.schedule()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show,
                            QEvent.LayoutRequest, QEvent.StyleChange, QEvent.FontChange):
            self.schedule()
        return False

    def schedule(self, *_):
        if not self._pending and not self._applying:
            self._pending = True
            QTimer.singleShot(0, self.apply)

    def apply(self):
        self._pending = False
        if sip.isdeleted(self.tabs) or self._applying:
            return
        self._applying = True
        try:
            for child, rect in list(self._children.items()):
                if sip.isdeleted(child):
                    del self._children[child]
                    continue
                page = child.parentWidget()
                # The page may be laid out lazily on its first activation.
                # Reapply after its move/show events, without changing saved coordinates.
                origin = page.mapTo(self.tabs, QPoint())
                child.setGeometry(rect.translated(-origin))
        finally:
            self._applying = False


def place_tab_child(tabs, child, x, y, width, height):
    controller = getattr(tabs, "_designer_child_geometry", None)
    if controller is None:
        controller = TabChildGeometry(tabs)
        tabs._designer_child_geometry = controller
    controller.register(child, (x, y, width, height))

"""A slider's command, sent once when a drag lets go: shared by preview and standalone applications."""
from PyQt5.QtCore import QEvent, QObject, Qt


class SendOnRelease(QObject):
    """Calls send(value) whenever a qfluentwidgets Slider's value changes, except while the mouse is down on
    it: a drag sends once, when it lets go, instead of a command for every value the handle passes. Keys and
    the wheel move in steps and send each one.

    That Slider never sets QSlider.isSliderDown(), and a drag that starts on the groove emits no
    pressed/released signals, so the mouse is watched on the slider and its handle."""

    def __init__(self, slider, send):
        super().__init__(slider)
        self._slider, self._send = slider, send
        self._held = False
        self._press_value = slider.value()
        slider.installEventFilter(self)
        slider.handle.installEventFilter(self)
        slider.valueChanged.connect(self._value_changed)

    def _value_changed(self, value):
        if not self._held:
            self._send(value)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease) and event.button() == Qt.LeftButton:
            if kind == QEvent.MouseButtonPress:
                self._held = True
                self._press_value = self._slider.value()  # before a press on the groove moves it
            elif self._held:
                self._held = False
                if self._slider.value() != self._press_value:
                    self._send(self._slider.value())
        return False


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


class NumericDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,4,8,4); layout.setSpacing(0)
        self._title = QLabel("标题"); self._title.setAlignment(Qt.AlignCenter)
        self._value = QLabel("0.00"); self._value.setAlignment(Qt.AlignCenter)
        self._unit = QLabel(""); self._unit.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title); layout.addWidget(self._value); layout.addWidget(self._unit)
        self.apply_theme()
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self.apply_theme)
    def apply_theme(self):
        secondary = "#b3b3b3" if isDarkTheme() else "#606060"
        self._title.setStyleSheet(f"color:{secondary};font-size:11px;")
        self._unit.setStyleSheet(f"color:{secondary};font-size:12px;")
        self._update_value_style()
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
        color = getattr(self, "_val_color", "#0078d4")
        size = getattr(self, "_val_font_size", 28)
        self._value.setStyleSheet(f"font-size:{size}px;font-weight:bold;color:{color};")

"""Explicit Qt signal lifetimes, including compiled Python callables."""


class SignalConnections:
    """Disconnect external signals when their owning QObject is destroyed.

    PyQt cannot always infer the QObject receiver of a compiled bound method.
    Relays therefore have an explicit lifetime and release their callback before
    disconnecting, so already queued deliveries also become harmless.
    """

    def __init__(self, owner):
        self._connections = []
        owner.destroyed.connect(self.clear)

    def connect(self, signal, slot, *args, **kwargs):
        callback = [slot]

        def relay(*values):
            current = callback[0]
            if current is not None:
                current(*values)

        connection = signal.connect(relay, *args, **kwargs)
        self._connections.append((signal, connection, callback))
        return connection

    def clear(self, *_):
        connections, self._connections = self._connections, []
        for _signal, _connection, callback in connections:
            callback[0] = None
        for signal, connection, _callback in connections:
            try:
                signal.disconnect(connection)
            except (TypeError, RuntimeError):
                # The sender or its connection may already have been destroyed.
                pass

"""Conversions shared by live bindings and standalone exported applications."""
import math


def binding_integer(value):
    """Accept integer-compatible values that fit Qt's signed 32-bit API."""
    number = int(value)
    if not -(2 ** 31) <= number < 2 ** 31:
        raise OverflowError("绑定整数超出 Qt 支持的范围")
    return number


def binding_float(value):
    """Reject NaN/infinity before passing a sample to a numeric widget."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("绑定数值必须是有限数")
    return number


def binding_register(value):
    """Modbus register payloads must be unsigned 16-bit integers."""
    if not isinstance(value, int) or not 0 <= value <= 65535:
        raise ValueError("Modbus 寄存器值必须是 0 到 65535 的整数")
    return value


def binding_boolean(value):
    """Read explicit boolean tokens or finite numbers; reject unknown text."""
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in ("true", "on", "yes"):
            return True
        if token in ("false", "off", "no"):
            return False
    return bool(binding_float(value))


def binding_decimals(value, places="自动"):
    """A number shown with a fixed count of decimal places; anything else (text, flags, NaN) as it came."""
    if places in ("自动", "", None) or isinstance(value, bool):
        return value
    try:
        number = float(value)
        places = int(places)
    except (TypeError, ValueError, OverflowError):
        return value
    if not math.isfinite(number):
        return value
    return f"{number:.{places}f}"


def binding_led(value, on_value="1", off_value="0"):
    """Preserve custom LED states before falling back to boolean conversion."""
    text = str(value).strip()
    if text == on_value:
        return True
    if text == off_value:
        return False
    try:
        return binding_float(value) == binding_float(on_value)
    except (TypeError, ValueError, OverflowError):
        return binding_boolean(value)

"""Bounded display cache with full history spooled to a temporary file."""
from collections import deque
from itertools import islice
import math
import struct
import tempfile


class ChartHistory:
    def __init__(self, capacity=10000):
        self.cache = deque(maxlen=capacity)
        self.count = 0
        self._file = None

    def append(self, value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("曲线样本必须是有限数")
        if self._file is None:
            self._file = tempfile.TemporaryFile()
        self._file.write(struct.pack("<d", value))
        self.cache.append(value)
        self.count += 1

    def tail(self, count):
        return list(islice(self.cache, max(0, len(self.cache) - count), None))

    def values(self):
        if self._file is None:
            return
        self._file.flush()
        self._file.seek(0)
        try:
            while True:
                chunk = self._file.read(8192)
                if not chunk:
                    break
                yield from (v[0] for v in struct.iter_unpack("<d", chunk))
        finally:
            self._file.seek(0, 2)

    def clear(self):
        self.close()
        self.cache.clear()
        self.count = 0

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None

    def __len__(self):
        return len(self.cache)

    def __getitem__(self, index):
        return self.cache[index]

    def __del__(self):
        self.close()

# coding: utf-8
"""Chart widgets: real-time line chart (pyqtgraph) and gauge meter."""
import csv
import json
import struct
from itertools import zip_longest
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel

from qfluentwidgets import (
    LineEdit as FluentLineEdit, PushButton as FluentPushButton,
    CheckBox as FluentCheckBox, BodyLabel, isDarkTheme, qconfig,
    setCustomStyleSheet,
)



from serial_handler import RawFrameBuffer



try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

_CURVE_COLORS = [
    (0, 120, 212), (244, 67, 54), (76, 175, 80), (255, 152, 0),
    (156, 39, 176), (0, 188, 212), (121, 85, 72), (96, 125, 139),
]

_DARK_CURVE_COLORS = [
    (74, 163, 223), (255, 112, 105), (129, 199, 132), (255, 183, 77),
    (206, 147, 216), (77, 208, 225), (188, 170, 164), (176, 190, 197),
]

_STRUCT_FMT = {
    "uint8": ("B", 1), "int8": ("b", 1),
    "uint16": ("H", 2), "int16": ("h", 2),
    "uint32": ("I", 4), "int32": ("i", 4),
    "float32": ("f", 4),
}


# ---------------------------------------------------------------------------
# Real-time line chart — multi-curve with built-in parsing
# ---------------------------------------------------------------------------

_DEFAULT_CURVE_CFG = {
    "name": "曲线1", "parseMode": "键值匹配",
    "key": "", "jsonPath": "",
    "byteOffset": 0, "dataType": "float32", "byteOrder": "大端(BE)",
    "frameHeader": "", "frameTail": "",
    "regIndex": 0, "mbDataType": "uint16", "mbRegOrder": "大端(AB CD)",
    "mbFcFilter": -1, "mbSlaveFilter": -1,
}

# Virtual prop name -> per-curve storage suffix
_CURVE_FIELD_MAP = {
    "curveName": "name", "curveParseMode": "parseMode",
    "curveKey": "key", "curveJsonPath": "jsonPath",
    "curveByteOffset": "byteOffset", "curveDataType": "dataType",
    "curveByteOrder": "byteOrder", "curveFrameHeader": "frameHeader",
    "curveFrameTail": "frameTail", "curveRegIndex": "regIndex",
    "curveMbDataType": "mbDataType", "curveMbRegOrder": "mbRegOrder",
    "curveMbFcFilter": "mbFcFilter", "curveMbSlaveFilter": "mbSlaveFilter",
}


class _HistoryObjectPairs(list):
    """Distinguish legacy JSON objects while preserving duplicate channel keys."""


def _history_json_channels(document):
    if isinstance(document, _HistoryObjectPairs):
        channels = list(document)
    elif isinstance(document, list):
        channels = []
        for entry in document:
            if not isinstance(entry, _HistoryObjectPairs):
                raise ValueError("曲线 JSON 通道必须包含 name 和 values")
            entry = dict(entry)
            if set(entry) != {"name", "values"}:
                raise ValueError("曲线 JSON 通道必须包含 name 和 values")
            channels.append((entry["name"], entry["values"]))
    else:
        raise ValueError("曲线 JSON 必须是对象或通道数组")
    for name, values in channels:
        if not isinstance(name, str) or not isinstance(values, list) or isinstance(values, _HistoryObjectPairs):
            raise ValueError("曲线 JSON 通道名称必须是文本，样本必须是数组")
    return channels


def build_cfgs_from_props(props: dict) -> list:
    """Build per-curve config list from flat ``_curve_{i}_{field}`` properties."""
    count = max(1, min(8, int(props.get("curveCount", 1))))
    cfgs = []
    for i in range(count):
        cfg = dict(_DEFAULT_CURVE_CFG)
        cfg["name"] = props.get(f"_curve_{i}_name", f"曲线{i + 1}")
        for field in _DEFAULT_CURVE_CFG:
            stored = props.get(f"_curve_{i}_{field}")
            if stored is not None:
                cfg[field] = stored
        cfgs.append(cfg)
    return cfgs


class RealtimeLineChart(QWidget):
    """Multi-curve scrolling real-time chart with right-side value table
    and draggable cursor. Each curve has independent parse configuration."""

    HISTORY_LIMIT = 10000
    REFRESH_MS = 33
    # the value table starts wide enough for these, so typical readings never resize the plot
    _SAMPLE_READING = "-0000.00"
    _SAMPLE_MODE = "游标: x=00000"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial_connections = SignalConnections(self)
        self._external_connections = SignalConnections(self)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(2)

        self._display_points = 200
        self._title = "实时曲线"
        self._cfgs: list = [dict(_DEFAULT_CURVE_CFG)]
        self._curves = []
        self._data: list = []
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(self.REFRESH_MS)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh_all)
        self.destroyed.connect(lambda _=None, histories=self._data: [h.close() for h in histories])
        self._checkboxes: list = []
        # a loaded recording laid over the live curves: [(name, values)], their dashed curves and table rows
        self._refs: list = []
        self._ref_curves: list = []
        self._ref_labels: list = []
        self._listening = False
        self._cursor_mode = False

        # ---- main area: plot (left) + value table (right) ----
        main_h = QHBoxLayout()
        main_h.setSpacing(4)
        self._missing_label = None

        if HAS_PYQTGRAPH:
            self._plot = pg.PlotWidget()
            self._plot.showGrid(x=True, y=True, alpha=0.3)
            main_h.addWidget(self._plot, 1)

            self._cursor_line = pg.InfiniteLine(
                angle=90, movable=True,
                pen=pg.mkPen(color=(255, 0, 0, 180), width=1, style=Qt.DashLine))
            self._cursor_line.setVisible(False)
            self._plot.addItem(self._cursor_line)
            self._external_connections.connect(
                self._cursor_line.sigPositionChanged, self._on_cursor_moved)
            self._external_connections.connect(
                self._plot.scene().sigMouseClicked, self._on_plot_clicked)
        else:
            self._missing_label = BodyLabel("需要安装 pyqtgraph")
            self._missing_label.setAlignment(Qt.AlignCenter)
            main_h.addWidget(self._missing_label, 1)
            self._plot = None
            self._cursor_line = None

        # right panel: mode label + value labels
        self._side = QWidget()
        right_panel = QVBoxLayout(self._side)
        right_panel.setContentsMargins(2, 0, 2, 0)
        right_panel.setSpacing(0)
        self._mode_label = QLabel("实时")
        self._mode_label.setAlignment(Qt.AlignCenter)
        right_panel.addWidget(self._mode_label)

        self._val_panel = QVBoxLayout()
        self._val_panel.setContentsMargins(0, 0, 0, 0)
        self._val_panel.setSpacing(0)
        right_panel.addLayout(self._val_panel)
        right_panel.addStretch()
        self._val_labels: list = []
        main_h.addWidget(self._side)

        self._root.addLayout(main_h, 1)

        # ---- toolbar ----
        tb = QHBoxLayout()
        tb.setContentsMargins(4, 2, 4, 0)
        tb.setSpacing(6)
        tb.addWidget(BodyLabel("显示点数"))
        self._disp_edit = FluentLineEdit()
        self._disp_edit.setText(str(self._display_points))
        self._disp_edit.setFixedWidth(80)
        self._disp_edit.editingFinished.connect(self._on_disp_changed)
        tb.addWidget(self._disp_edit)
        tb.addStretch()
        self._save_btn = FluentPushButton("保存")
        self._save_btn.setFixedWidth(64)
        self._save_btn.clicked.connect(self._save_data)
        tb.addWidget(self._save_btn)
        self._load_btn = FluentPushButton("加载")
        self._load_btn.setFixedWidth(64)
        self._load_btn.clicked.connect(self._load_data)
        tb.addWidget(self._load_btn)
        self._clear_ref_btn = FluentPushButton("清除对比")
        self._clear_ref_btn.clicked.connect(self.clear_reference)
        self._clear_ref_btn.hide()
        tb.addWidget(self._clear_ref_btn)
        self._root.addLayout(tb)

        self._cb_row = QHBoxLayout()
        self._cb_row.setContentsMargins(4, 0, 4, 2)
        self._root.addLayout(self._cb_row)

        self._rebuild_curves()
        self._external_connections.connect(qconfig.themeChangedFinished, self.apply_theme)

    # -- public configuration -------------------------------------------------

    @staticmethod
    def _curve_color(index):
        colors = _DARK_CURVE_COLORS if isDarkTheme() else _CURVE_COLORS
        return colors[index % len(colors)]

    def apply_theme(self):
        """Update appearance without rebuilding curves, histories or controls."""
        dark = isDarkTheme()
        foreground = "#e5e5e5" if dark else "#202020"
        muted = "#b0b0b0" if dark else "#606060"
        accent = "#4aa3df" if dark else "#0078d4"
        if self._plot:
            self._plot.setBackground("#252525" if dark else "#ffffff")
            self._plot.setTitle(self._title, color=foreground, size="10pt")
            for name in ("left", "bottom", "right", "top"):
                axis = self._plot.getAxis(name)
                axis.setPen(pg.mkPen(muted))
                axis.setTextPen(pg.mkPen(foreground))
            for index, curve in enumerate(self._curves):
                if curve:
                    curve.setPen(pg.mkPen(self._curve_color(index), width=2))
            for index, curve in enumerate(self._ref_curves):
                if curve:
                    curve.setPen(self._ref_pen(index))
        elif self._missing_label is not None:
            setCustomStyleSheet(
                self._missing_label,
                "FluentLabelBase { color: #606060; border: 1px dashed #ccc; background: #fafafa; }",
                "FluentLabelBase { color: #c0c0c0; border: 1px dashed #555; background: #252525; }",
            )
        self._mode_label.setStyleSheet(
            f"font-size: 10px; color: {accent}; padding: 1px 0;")
        for label in self._val_labels + self._ref_labels:
            label.setStyleSheet(
                f"font-size: 11px; padding: 1px 2px; color: {foreground};")
        if self._cursor_mode and self._cursor_line:
            self._update_table_at_cursor(self._cursor_line.value())
        else:
            self._update_table_realtime()
        self.update()

    def set_title(self, title: str):
        self._title = title
        if self._plot:
            self._plot.setTitle(title, color="#e5e5e5" if isDarkTheme() else "#202020", size="10pt")

    def set_display_points(self, n: int):
        self._display_points = max(10, min(self.HISTORY_LIMIT, n))
        self._disp_edit.blockSignals(True)
        self._disp_edit.setText(str(self._display_points))
        self._disp_edit.blockSignals(False)
        self._refresh_all()

    def load_from_props(self, props: dict):
        """Build curve configs from flat properties and rebuild."""
        self._cfgs = build_cfgs_from_props(props)
        self._rebuild_curves()

    def set_curve_count(self, n: int):
        old = len(self._cfgs)
        n = max(1, min(8, n))
        while len(self._cfgs) > n:
            self._cfgs.pop()
        while len(self._cfgs) < n:
            idx = len(self._cfgs)
            cfg = dict(_DEFAULT_CURVE_CFG)
            cfg["name"] = f"曲线{idx + 1}"
            self._cfgs.append(cfg)
        if len(self._cfgs) != old:
            self._rebuild_curves()

    # -- internal -------------------------------------------------------------

    def _on_disp_changed(self):
        try:
            v = int(self._disp_edit.text())
        except (ValueError, TypeError):
            v = self._display_points
        self._display_points = max(10, v)
        self._disp_edit.setText(str(self._display_points))
        self._refresh_all()

    def _refresh_all(self):
        self._refresh_timer.stop()
        for i in range(len(self._data)):
            if i < len(self._curves) and self._curves[i]:
                self._curves[i].setData(self._data[i].tail(self._display_points))
        start = self._window_start()
        for curve, (_, values) in zip(self._ref_curves, self._refs):
            if curve:
                curve.setData(values[start:start + self._display_points])
        if self._cursor_mode and self._cursor_line:
            self._update_table_at_cursor(self._cursor_line.value())
        else:
            self._update_table_realtime()

    def _rebuild_curves(self):
        self.clear_reference()  # its rows live in the value table rebuilt below
        self._raw_frames = [
            RawFrameBuffer(_hex_to_bytes(cfg.get("frameHeader", "")),
                           _hex_to_bytes(cfg.get("frameTail", ""))) for cfg in self._cfgs
        ]
        for c in self._curves:
            if self._plot and c:
                self._plot.removeItem(c)
        self._curves.clear()

        count = len(self._cfgs)
        while self._data and len(self._data) > count:
            self._data.pop().close()
        while len(self._data) < count:
            self._data.append(ChartHistory(self.HISTORY_LIMIT))

        while self._cb_row.count():
            item = self._cb_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()

        while self._val_panel.count():
            it = self._val_panel.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._val_labels.clear()

        for i, cfg in enumerate(self._cfgs):
            color = self._curve_color(i)
            name = cfg.get("name", f"曲线{i + 1}")

            if self._plot:
                pen = pg.mkPen(color=color, width=2)
                curve = self._plot.plot(pen=pen, name=name)
                self._curves.append(curve)
            else:
                self._curves.append(None)

            cb = FluentCheckBox(name)
            cb.setChecked(True)
            light_color = _CURVE_COLORS[i % len(_CURVE_COLORS)]
            dark_color = _DARK_CURVE_COLORS[i % len(_DARK_CURVE_COLORS)]
            setCustomStyleSheet(
                cb,
                f"QCheckBox {{ color: rgb{light_color}; font-size: 11px; }}",
                f"QCheckBox {{ color: rgb{dark_color}; font-size: 11px; }}",
            )
            idx = i
            cb.toggled.connect(lambda checked, ci=idx: self._toggle(ci, checked))
            self._checkboxes.append(cb)
            self._cb_row.addWidget(cb)

            # sized for a typical reading up front; apply_theme then shows the real values
            vl = QLabel(f"<b style='color:rgb{color}'>{name}</b>  {self._SAMPLE_READING}")
            vl.setStyleSheet("font-size: 11px; padding: 1px 2px;")
            self._val_panel.addWidget(vl)
            self._val_labels.append(vl)

        self._cb_row.addStretch()
        self._cursor_mode = False
        self._mode_label.setText("实时")
        self._side.setMinimumWidth(0)
        self._hold_side_width()
        self.apply_theme()

    def _hold_side_width(self):
        """Let the value table widen but never narrow back. A reading that gets shorter (99.82 -> 100) would
        otherwise hand its space to the plot, and the whole curve would shift sideways with every sample."""
        for label in (self._mode_label, *self._val_labels, *self._ref_labels):
            label.ensurePolished()
        margins = self._side.layout().contentsMargins()
        need = max([self._mode_label.fontMetrics().horizontalAdvance(self._SAMPLE_MODE)]
                   + [label.sizeHint().width() for label in self._val_labels + self._ref_labels])
        need += margins.left() + margins.right()
        if need > self._side.minimumWidth():
            self._side.setMinimumWidth(need)

    def _toggle(self, index: int, visible: bool):
        if index < len(self._curves) and self._curves[index]:
            self._curves[index].setVisible(visible)

    # -- comparison overlay ---------------------------------------------------

    def load_reference(self, path):
        """Lay a saved recording over the live curves as dashed curves, to compare runs. The live curves and
        their history stay as they are; the two line up sample for sample from the start of each."""
        names, histories = self._read_history(path)
        try:
            refs = [(f"{name}（{Path(path).stem}）", list(history.values()))
                    for name, history in zip(names, histories)]
        finally:
            for history in histories:
                history.close()
        self.clear_reference()
        self._refs = refs
        for index in range(len(refs)):
            self._ref_curves.append(self._plot.plot(pen=self._ref_pen(index)) if self._plot else None)
            label = QLabel()
            self._val_panel.addWidget(label)
            self._ref_labels.append(label)
        self._clear_ref_btn.show()
        self.apply_theme()
        self._refresh_all()

    def clear_reference(self):
        for curve in self._ref_curves:
            if self._plot and curve:
                self._plot.removeItem(curve)
        for label in self._ref_labels:
            self._val_panel.removeWidget(label)
            label.deleteLater()
        self._refs, self._ref_curves, self._ref_labels = [], [], []
        self._clear_ref_btn.hide()

    def _ref_color(self, index):
        """A recording takes the palette colours after the live curves', so it stands apart even where it
        crosses the curve it is compared with; the value table names which is which."""
        return self._curve_color(len(self._cfgs) + index)

    def _ref_pen(self, index):
        return pg.mkPen(self._ref_color(index), width=2, style=Qt.DashLine)

    def _window_start(self):
        """Sample number of the first point the live window shows."""
        return max(0, max((h.count for h in self._data), default=0) - self._display_points)

    def _update_reference_rows(self, sample):
        for index, (label, (name, values)) in enumerate(zip(self._ref_labels, self._refs)):
            val = f"{values[sample]:.4g}" if 0 <= sample < len(values) else "--"
            label.setText(f"<b style='color:rgb{self._ref_color(index)}'>{name}</b>  {val}")

    # -- cursor ---------------------------------------------------------------

    def _on_plot_clicked(self, evt):
        if evt.double():
            self._cursor_mode = False
            self._mode_label.setText("实时")
            if self._cursor_line:
                self._cursor_line.setVisible(False)
            self._update_table_realtime()
            return
        if not self._plot:
            return
        scene_pos = evt.scenePos()
        vb = self._plot.plotItem.vb
        mouse_point = vb.mapSceneToView(scene_pos)
        x = mouse_point.x()
        self._cursor_mode = True
        if self._cursor_line:
            self._cursor_line.setVisible(True)
            self._cursor_line.blockSignals(True)
            self._cursor_line.setValue(x)
            self._cursor_line.blockSignals(False)
        self._update_table_at_cursor(x)

    def _on_cursor_moved(self, *_):
        if not self._cursor_line:
            return
        self._cursor_mode = True
        x = self._cursor_line.value()
        self._update_table_at_cursor(x)

    def _update_table_at_cursor(self, x: float):
        idx = int(round(x))
        self._mode_label.setText(f"游标: x={idx}")
        for i, lbl in enumerate(self._val_labels):
            color = self._curve_color(i)
            name = self._cfgs[i].get("name", f"曲线{i+1}") if i < len(self._cfgs) else ""
            visible = self._data[i].tail(self._display_points) if i < len(self._data) else []
            val = f"{visible[idx]:.4g}" if 0 <= idx < len(visible) else "--"
            lbl.setText(f"<b style='color:rgb{color}'>{name}</b>  {val}")
        self._update_reference_rows(self._window_start() + idx)
        self._hold_side_width()

    def _update_table_realtime(self):
        for i, lbl in enumerate(self._val_labels):
            color = self._curve_color(i)
            name = self._cfgs[i].get("name", f"曲线{i+1}") if i < len(self._cfgs) else ""
            if i < len(self._data) and self._data[i]:
                val = f"{self._data[i][-1]:.4g}"
            else:
                val = "--"
            lbl.setText(f"<b style='color:rgb{color}'>{name}</b>  {val}")
        # the recording at the point the live run has reached
        self._update_reference_rows(max((h.count for h in self._data), default=0) - 1)
        self._hold_side_width()

    # -- data input -----------------------------------------------------------

    def append_value(self, channel: int, value: float):
        if 0 <= channel < len(self._data):
            try:
                self._data[channel].append(value)
            except OSError as error:
                self._mode_label.setText(f"记录失败: {error}")
                return
            if not self._refresh_timer.isActive():
                self._refresh_timer.start()

    def clear_data(self):
        self._refresh_timer.stop()
        for i in range(len(self._data)):
            self._data[i].clear()
            if i < len(self._curves) and self._curves[i]:
                self._curves[i].setData([])
        self._update_table_realtime()

    # -- save / load ----------------------------------------------------------

    def save_data(self, path):
        """Stream the complete history, including samples evicted from display."""
        names = [c.get("name", f"曲线{i+1}") for i, c in enumerate(self._cfgs)]
        with open(path, "w", newline="", encoding="utf-8") as output:
            if str(path).lower().endswith(".json"):
                # Objects retain the original format for unique names. Ordered
                # channel records keep duplicate names lossless in other JSON readers.
                duplicate_names = len(set(names)) != len(names)
                output.write("[" if duplicate_names else "{")
                for i, name in enumerate(names):
                    if i:
                        output.write(",")
                    encoded_name = json.dumps(name, ensure_ascii=False)
                    output.write(('{"name":' + encoded_name + ',"values":[')
                                 if duplicate_names else encoded_name + ":[")
                    for index, value in enumerate(self._data[i].values()):
                        if index:
                            output.write(",")
                        output.write(json.dumps(value, allow_nan=False))
                    output.write("]}" if duplicate_names else "]")
                output.write("]" if duplicate_names else "}")
            else:
                writer = csv.writer(output)
                writer.writerow(names)
                writer.writerows(zip_longest(*(h.values() for h in self._data), fillvalue=""))

    def _save_data(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存完整曲线数据", "", "CSV文件 (*.csv);;JSON文件 (*.json)")
        if path:
            try:
                self.save_data(path)
            except OSError as error:
                self._mode_label.setText(f"保存失败: {error}")

    def load_data(self, path):
        """Replace samples for existing channels without changing live parsing.

        Identical channel lists retain their order (including duplicate names).
        Unique names may be reordered in a file. Other channel changes are
        rejected instead of silently associating samples with another parser.
        An empty, unconfigured default chart can adopt the file's channels.
        """
        adopt_channels = (self._cfgs == [_DEFAULT_CURVE_CFG]
                          and not any(history.count for history in self._data))
        names, histories = self._read_history(path)
        try:
            channel_order = self._history_channel_order(names, adopt_channels)
        except Exception:
            for history in histories:
                history.close()
            raise
        self._refresh_timer.stop()
        for history in self._data:
            history.close()
        self._data[:] = [histories[index] for index in channel_order]
        if adopt_channels:
            self._cfgs = [{**_DEFAULT_CURVE_CFG, "name": name} for name in names]
            self._rebuild_curves()
        self._refresh_all()

    def _read_history(self, path):
        """Channel names and their samples from a saved CSV or JSON file; the caller closes the histories."""
        histories = []
        try:
            with open(path, "r", encoding="utf-8") as source:
                if str(path).lower().endswith(".json"):
                    # JSON is a document format; CSV is streamed for large captures.
                    obj = json.load(source, object_pairs_hook=_HistoryObjectPairs)
                    channels = _history_json_channels(obj)
                    names = [name for name, _ in channels]
                    for name, values in channels:
                        history = ChartHistory(self.HISTORY_LIMIT)
                        histories.append(history)
                        for value in values:
                            if value is not None:
                                history.append(float(value))
                else:
                    rows = csv.reader(source)
                    names = next(rows, [])
                    histories = [ChartHistory(self.HISTORY_LIMIT) for _ in names]
                    for row in rows:
                        for index, history in enumerate(histories):
                            if index < len(row) and row[index].strip():
                                history.append(float(row[index]))
        except Exception:
            for history in histories:
                history.close()
            raise
        return names, histories

    def _history_channel_order(self, names, adopt_channels=False):
        expected = [cfg.get("name", f"曲线{i+1}") for i, cfg in enumerate(self._cfgs)]
        if not names:
            raise ValueError("曲线文件没有通道")
        if len(names) > 8:
            raise ValueError("曲线文件最多支持 8 个通道")
        if adopt_channels:
            return list(range(len(names)))
        if names == expected:
            return list(range(len(expected)))
        if (len(names) == len(expected) and len(set(names)) == len(names)
                and set(names) == set(expected)):
            return [names.index(name) for name in expected]
        raise ValueError("曲线文件通道名称或数量与当前配置不一致，请加载对应通道的历史文件")

    def _load_data(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载对比曲线", "", "CSV文件 (*.csv);;JSON文件 (*.json)")
        if path:
            try:
                self.load_reference(path)
            except (OSError, ValueError, TypeError, OverflowError) as error:
                self._mode_label.setText(f"加载失败: {error}")

    def configure(self, cfgs, disp_pts=200):
        if isinstance(cfgs, str):
            cfgs = json.loads(cfgs)
        self._cfgs = list(cfgs)[:8]
        self._rebuild_curves()
        self.set_display_points(disp_pts)

    def on_parsed(self, data):
        self._on_parsed_data(data)

    def on_raw(self, data):
        self._on_raw_data(data)

    def reset_stream(self):
        for frames in self._raw_frames:
            frames.reset()

    # -- self-parsing (per-curve) ---------------------------------------------

    def _on_parsed_data(self, data: dict):
        for i, cfg in enumerate(self._cfgs):
            try:
                pm = cfg.get("parseMode", "键值匹配")
                val = None
                if pm == "键值匹配":
                    key = cfg.get("key") or cfg.get("name", "")
                    if key and key in data:
                        val = data[key]
                elif pm == "JSON路径":
                    jp = cfg.get("jsonPath", "")
                    if jp:
                        val = self._resolve_path(data, jp)
                elif pm == "Modbus":
                    val = self._extract_modbus(cfg, data)
                if val is not None:
                    self.append_value(i, val)
            except (ValueError, TypeError, OverflowError, struct.error):
                # Reject a bad sample without losing the other channels in this frame.
                continue

    def _on_raw_data(self, raw: bytes):
        for i, cfg in enumerate(self._cfgs):
            if cfg.get("parseMode") != "HEX字节提取":
                continue
            fi = _STRUCT_FMT.get(cfg.get("dataType", "float32"))
            if not fi:
                continue
            fmt_c, sz = fi
            bo = ">" if cfg.get("byteOrder", "大端(BE)") == "大端(BE)" else "<"
            off = int(cfg.get("byteOffset", 0))
            for frame in self._raw_frames[i].feed(raw):
                payload = self._strip_frame(frame, cfg)
                if payload is not None and off >= 0 and off + sz <= len(payload):
                    try:
                        val = struct.unpack(bo + fmt_c, payload[off:off + sz])[0]
                        self.append_value(i, float(val))
                    except (ValueError, TypeError, OverflowError, struct.error):
                        pass

    @staticmethod
    def _extract_modbus(cfg: dict, data: dict):
        sf = int(cfg.get("mbSlaveFilter", -1))
        if sf >= 0 and data.get("slave") != sf:
            return None
        fc = data.get("fc", 0)
        fcf = int(cfg.get("mbFcFilter", -1))
        if fcf >= 0 and fc != fcf:
            return None
        idx = int(cfg.get("regIndex", 0))
        if fc in (0x01, 0x02):
            return data.get(f"coil{idx}")
        r0 = data.get(f"reg{idx}")
        if r0 is None:
            return None
        r0 = binding_register(r0)
        dt = cfg.get("mbDataType", "uint16")
        if dt == "uint16":
            return r0
        if dt == "int16":
            return r0 - 65536 if r0 > 32767 else r0
        r1 = data.get(f"reg{idx + 1}")
        if r1 is None:
            return None
        r1 = binding_register(r1)
        if cfg.get("mbRegOrder", "大端(AB CD)") == "大端(AB CD)":
            hi, lo = r0, r1
        else:
            hi, lo = r1, r0
        raw_b = hi.to_bytes(2, "big") + lo.to_bytes(2, "big")
        if dt == "uint32":
            return int.from_bytes(raw_b, "big")
        if dt == "int32":
            return int.from_bytes(raw_b, "big", signed=True)
        if dt == "float32":
            return struct.unpack(">f", raw_b)[0]
        return r0

    @staticmethod
    def _strip_frame(raw: bytes, cfg: dict):
        data = raw
        fh = cfg.get("frameHeader", "")
        ft = cfg.get("frameTail", "")
        if fh:
            hdr = _hex_to_bytes(fh)
            if hdr:
                idx = data.find(hdr)
                if idx < 0:
                    return None
                data = data[idx + len(hdr):]
        if ft:
            tlr = _hex_to_bytes(ft)
            if tlr:
                idx = data.find(tlr)
                if idx < 0:
                    return None
                data = data[:idx]
        return data

    @staticmethod
    def _resolve_path(data, path: str):
        for part in path.split("."):
            if data is None:
                return None
            if isinstance(data, dict):
                data = data.get(part)
            elif isinstance(data, (list, tuple)):
                try:
                    data = data[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return data


def _hex_to_bytes(s: str) -> bytes:
    s = s.replace(" ", "")
    if not s:
        return b""
    if len(s) % 2 != 0:
        s = "0" + s
    try:
        return bytes.fromhex(s)
    except ValueError:
        return b""

"""Data table shared by the designer preview and exported applications."""
from datetime import datetime

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHeaderView, QTableWidgetItem, QAbstractItemView
from qfluentwidgets import TableWidget




class DataTableWidget(QWidget):
    """Either the latest frame as field / value rows, or a log with one row per frame.

    In the log, each column takes the value of the key it is named after and a column named 时间 takes the
    time the frame arrived; frames carrying none of the named keys belong to some other message and are
    skipped. Beyond the row limit the oldest rows go."""

    TIME_COLUMN = "时间"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial_connections = SignalConnections(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._table = TableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["字段", "值"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self._table)
        self._columns = ["字段", "值"]
        self._max_rows = 500
        self._logging = False
        self._fit_columns()

    def set_serial_handler(self, handler):
        self._serial_connections.clear()
        self._serial_connections.connect(handler.dataReceived, self.on_data)

    def set_columns(self, columns):
        self._columns = list(columns) or ["字段", "值"]
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)
        self._fit_columns()

    def _fit_columns(self):
        """Field / value columns share the width. A log's columns fit what they hold, so a time stamp or a
        reading is never squeezed into an ellipsis, and the last one takes what is left."""
        header = self._table.horizontalHeader()
        header.setResizeContentsPrecision(64)  # sizes from a sample of rows, not the whole log
        # a log's rows are told apart by their time stamps; row numbers growing to four digits would only
        # take width from the readings
        self._table.verticalHeader().setVisible(not self._logging)
        last = len(self._columns) - 1
        for column in range(len(self._columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents
                                        if self._logging and column < last else QHeaderView.Stretch)

    def set_max_rows(self, count):
        self._max_rows = max(10, count)
        while self._table.rowCount() > self._max_rows:
            self._table.removeRow(0 if self._logging else self._table.rowCount() - 1)

    def set_record_mode(self, mode):
        """最新值 (the latest frame) or 逐行记录 (one row per frame)."""
        logging = mode == "逐行记录"
        if logging != self._logging:
            self._logging = logging
            self.clear_data()
            self._fit_columns()

    def on_data(self, data):
        if self._logging:
            self.log_frame(data)
        else:
            self.update_kv_data(data)

    def log_frame(self, data):
        keys = [name for name in self._columns if name != self.TIME_COLUMN]
        if not any(key in data for key in keys):
            return
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.append_row([stamp if name == self.TIME_COLUMN else ("" if data.get(name) is None else data[name])
                         for name in self._columns])

    def append_row(self, values):
        if self._table.rowCount() >= self._max_rows:
            self._table.removeRow(0)
        row = self._table.rowCount()
        self._table.insertRow(row)
        for column, value in enumerate(values):
            if column < self._table.columnCount():
                self._table.setItem(row, column, QTableWidgetItem(str(value)))
        self._table.scrollToBottom()

    def update_kv_data(self, data):
        self._table.setRowCount(0)
        for key, value in data.items():
            row = self._table.rowCount()
            if row >= self._max_rows:
                break
            self._table.insertRow(row)
            for column, cell in enumerate((key, value)):
                if column < self._table.columnCount():
                    self._table.setItem(row, column, QTableWidgetItem(str(cell)))

    def clear_data(self):
        self._table.setRowCount(0)


class ProgressRingDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self); lo.setContentsMargins(4,4,4,4)
        lo.setAlignment(Qt.AlignCenter); lo.setSpacing(4)
        self._ring = ProgressRing(); self._ring.setRange(0,100); self._ring.setValue(0)
        self._ring.setFixedSize(80,80)
        self._ring.setTextVisible(True)
        self._lbl = CaptionLabel("进度"); self._lbl.setAlignment(Qt.AlignCenter)
        lo.addWidget(self._ring, 0, Qt.AlignCenter)
        lo.addWidget(self._lbl)
    def set_label(self, t): self._lbl.setText(t)
    def set_value(self, v): self._ring.setValue(int(v))
    def set_maximum(self, m): self._ring.setMaximum(int(m))

"""Log box shared by the designer preview and exported applications."""
from datetime import datetime
from html import escape

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import TextEdit, setCustomStyleSheet



LOG_STYLE = ("QTextEdit { font-family: Menlo, Consolas, 'Courier New', monospace; font-size: 11px; "
             "background: #1a1a2e; color: #a8d8ea; border: 1px solid #333; border-radius: 6px; padding: 6px; }")
LOG_COLORS = {"info": "#a8d8ea", "warn": "#FFD54F", "error": "#EF5350", "ok": "#81C784"}


def terminal_scroll_bar(edit):
    """Recolour Fluent's overlay scroll bar for a dark terminal in both themes. Its light-theme default, a
    black handle over a white groove, disappears on the dark text and glares when hovered."""
    bar = edit.scrollDelegate.vScrollBar
    handle, arrow, groove = QColor(168, 216, 234, 110), QColor(168, 216, 234, 160), QColor(36, 36, 60, 235)
    bar.setHandleColor(handle, handle)
    bar.setArrowColor(arrow, arrow)
    bar.setGrooveColor(groove, groove)


class LogDisplayBox(QWidget):
    """Scrolling, time-stamped log in a dark terminal look: every parsed frame, and the connect,
    disconnect and error events of every link (serial, TCP, MQTT)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._output = TextEdit()
        self._output.setReadOnly(True)
        setCustomStyleSheet(self._output, LOG_STYLE, LOG_STYLE)  # the terminal keeps its colours in both themes
        terminal_scroll_bar(self._output)
        self._text = self._output
        layout.addWidget(self._output)
        self._max_lines = 500
        self._handler = None
        self._serial_connections = SignalConnections(self)

    def set_serial_handler(self, handler):
        if handler is self._handler:
            return
        self._serial_connections.clear()
        self._handler = handler
        if handler is not None:
            self._serial_connections.connect(handler.connected, self._on_connected)
            self._serial_connections.connect(handler.disconnected, self._on_disconnected)
            self._serial_connections.connect(handler.error, self._on_serial_error)
            self._serial_connections.connect(handler.dataReceived, self._on_parsed_data)

    def _on_connected(self, port):
        self.append_log(f"已连接: {port}", "ok")

    def _on_disconnected(self):
        self.append_log("已断开", "warn")

    def _on_serial_error(self, message):
        self.append_log(f"错误: {message}", "error")

    def _on_parsed_data(self, data):
        self.append_log(", ".join(f"{key}={value}" for key, value in data.items()))

    def append_log(self, text, level="info"):
        color = LOG_COLORS.get(level, LOG_COLORS["info"])
        stamp = datetime.now().strftime("%H:%M:%S")
        body = escape(str(text)).replace("\n", "<br>")
        self._output.append(f'<span style="color:#9399b2">[{stamp}]</span> <span style="color:{color}">{body}</span>')
        self._trim()

    def set_max_lines(self, n):
        self._max_lines = max(50, n)
        self._trim()

    def clear_log(self):
        self._output.clear()

    def _trim(self):
        doc = self._output.document()
        while doc.blockCount() > self._max_lines:
            cursor = self._output.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

# coding: utf-8
"""Composite card widgets: SerialConfigCard, DataSendCard, DataRecvCard, LogBox, ProgressRing."""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QSizePolicy, QFrame, QTextEdit,
)
from qfluentwidgets import (
    CardWidget, StrongBodyLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ComboBox, LineEdit, SpinBox,
    ProgressRing, FluentIcon as FIF, ToolButton,
    CheckBox, TextEdit, isDarkTheme, qconfig,
)

from serial_handler import _list_all_ports


class SerialConfigCard(CardWidget):
    """Serial port configuration card with three display modes:
    完整 (full), 简洁 (simple: port+baud+buttons), 单行 (single-line toolbar).
    Buttons drive the hub's serial link so the card works in preview mode."""

    LINK = "serial"  # name of this card's link on a CommHub
    _BAUDS = ["9600", "19200", "38400", "57600", "115200",
              "230400", "460800", "921600"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._display_mode = "完整"
        self._connected = False
        self._handler = None
        self._serial_connections = SignalConnections(self)
        self._theme_connections = SignalConnections(self)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 12, 16, 12)
        self._root.setSpacing(10)

        # ---- title row ----
        self._title_w = self._make_row()
        tl = self._title_w.layout()
        self._title = StrongBodyLabel("串口配置")
        self._status = CaptionLabel("未连接")
        self._status.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        tl.addWidget(self._title); tl.addStretch(); tl.addWidget(self._status)
        self._root.addWidget(self._title_w)

        LW = 48

        # ---- port row ----
        self._port_w = self._make_row()
        pl = self._port_w.layout()
        self._port_label = BodyLabel("端口"); self._port_label.setFixedWidth(LW)
        self._port_combo = ComboBox(); self._port_combo.setMinimumWidth(120)
        self._port_combo.setPlaceholderText("选择串口")
        self._search_btn = ToolButton(FIF.SEARCH)
        self._search_btn.setToolTip("搜索串口")
        self._search_btn.clicked.connect(self.refresh_ports)
        pl.addWidget(self._port_label); pl.addWidget(self._port_combo, 1)
        pl.addWidget(self._search_btn)
        self._root.addWidget(self._port_w)

        # ---- baud row ----
        self._baud_w = self._make_row()
        bl = self._baud_w.layout()
        self._baud_label = BodyLabel("波特率"); self._baud_label.setFixedWidth(LW)
        self._baud_combo = ComboBox()
        self._baud_combo.addItems(self._BAUDS); self._baud_combo.setCurrentIndex(4)
        bl.addWidget(self._baud_label); bl.addWidget(self._baud_combo, 1)
        self._root.addWidget(self._baud_w)

        # ---- params row (databits / parity / stopbits) ----
        self._params_w = self._make_row(spacing=6)
        pal = self._params_w.layout()
        first = True
        for lbl_text, cb_items, attr, idx in [
            ("数据位", ["5", "6", "7", "8"], "_databits_combo", 3),
            ("校验",   ["None", "Even", "Odd", "Mark", "Space"], "_parity_combo", 0),
            ("停止位", ["1", "1.5", "2"], "_stopbits_combo", 0),
        ]:
            lbl = CaptionLabel(lbl_text)
            if first:
                lbl.setFixedWidth(LW)
                first = False
            cb = ComboBox(); cb.addItems(cb_items); cb.setCurrentIndex(idx)
            setattr(self, attr, cb)
            pal.addWidget(lbl); pal.addWidget(cb, 1)
        self._root.addWidget(self._params_w)

        # ---- flow row ----
        self._flow_w = self._make_row()
        fl = self._flow_w.layout()
        self._flow_label = BodyLabel("流控"); self._flow_label.setFixedWidth(LW)
        self._flow_combo = ComboBox()
        self._flow_combo.addItems(["无", "RTS/CTS", "XON/XOFF", "DTR/DSR"])
        fl.addWidget(self._flow_label); fl.addWidget(self._flow_combo, 1)
        self._root.addWidget(self._flow_w)

        self._parser_w = self._make_row()
        self._parser_w.layout().addWidget(BodyLabel("解析模式"))
        self._parser_combo = ComboBox()
        self._parser_combo.addItems(["项目设置", "line", "hex", "modbus", "modbus_tcp"])
        self._parser_w.layout().addWidget(self._parser_combo, 1)
        self._root.addWidget(self._parser_w)

        # ---- button row ----
        self._btn_w = self._make_row()
        btl = self._btn_w.layout()
        self._connect_btn = PrimaryPushButton(FIF.CONNECT, "连接")
        self._disconnect_btn = PushButton(FIF.CLOSE, "断开")
        self._disconnect_btn.setEnabled(False)
        self._connect_btn.clicked.connect(self._on_connect)
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        btl.addWidget(self._connect_btn, 1); btl.addWidget(self._disconnect_btn, 1)
        self._root.addWidget(self._btn_w)

        # ---- single-line row (hidden by default) ----
        self._sl_w = QWidget()
        sl = QHBoxLayout(self._sl_w)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)

        H = 33
        self._sl_port = ComboBox(); self._sl_port.setPlaceholderText("串口")
        self._sl_port.setMinimumWidth(90); self._sl_port.setFixedHeight(H)
        self._sl_baud = ComboBox(); self._sl_baud.addItems(self._BAUDS)
        self._sl_baud.setCurrentIndex(4)
        self._sl_baud.setFixedWidth(90); self._sl_baud.setFixedHeight(H)
        self._sl_search = ToolButton(FIF.SEARCH)
        self._sl_search.clicked.connect(self.refresh_ports)
        self._sl_search.setFixedSize(H, H)
        self._sl_conn = PrimaryPushButton("连接")
        self._sl_conn.setFixedSize(56, H)
        self._sl_disconn = PushButton("断开")
        self._sl_disconn.setFixedSize(56, H)
        self._sl_disconn.setEnabled(False)
        self._sl_conn.clicked.connect(self._on_connect)
        self._sl_disconn.clicked.connect(self._on_disconnect)
        self._sl_status = CaptionLabel("未连接")
        self._sl_status.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        self._sl_status.setAlignment(Qt.AlignCenter)
        self._sl_status.setFixedHeight(H)

        for w, stretch in [(self._sl_port, 2), (self._sl_baud, 0),
                           (self._sl_search, 0), (self._sl_conn, 0),
                           (self._sl_disconn, 0), (self._sl_status, 0)]:
            sl.addWidget(w, stretch, Qt.AlignVCenter)

        self._sl_w.setFixedHeight(H)
        self._root.addWidget(self._sl_w)
        self._sl_w.hide()

        self._root.addStretch(1)

        self.refresh_ports()
        self._theme_connections.connect(qconfig.themeChangedFinished, self.update)

    def set_serial_handler(self, handler):
        """Attach the serial link; a CommHub is resolved to its serial handler."""
        handler = getattr(handler, self.LINK, handler)
        if handler is self._handler:
            return
        self._serial_connections.clear()
        self._handler = handler
        if handler is not None:
            self._serial_connections.connect(handler.connected, self._on_serial_connected)
            self._serial_connections.connect(handler.disconnected, self._on_serial_disconnected)
            self._serial_connections.connect(handler.error, self._on_serial_error)
            self.set_connected(handler.is_connected)

    @staticmethod
    def _make_row(spacing=8):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(spacing)
        return w

    # ---- compact paint ----

    def _content_height(self):
        m = self._root.contentsMargins()
        h = m.top() + m.bottom()
        for i in range(self._root.count()):
            w = self._root.itemAt(i).widget()
            if w and not w.isHidden():
                h += w.sizeHint().height() + self._root.spacing()
        return max(h, 30)

    def paintEvent(self, event):
        if self._display_mode == "完整":
            super().paintEvent(event)
            return
        ch = self._content_height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if isDarkTheme():
            painter.setBrush(QColor(44, 44, 44))
            painter.setPen(QColor(55, 55, 55))
        else:
            painter.setBrush(QColor(255, 255, 255, 230))
            painter.setPen(QColor(220, 220, 220))
        painter.drawRoundedRect(0, 0, self.width(), ch, 6, 6)
        painter.end()

    # ---- mode switching ----

    def set_display_mode(self, mode: str):
        self._display_mode = mode
        is_sl = mode == "单行"
        compact = mode != "完整"
        self.setAttribute(Qt.WA_TranslucentBackground, compact)
        self.setAutoFillBackground(not compact)
        self._title_w.setVisible(not is_sl)
        self._port_w.setVisible(not is_sl)
        self._baud_w.setVisible(not is_sl)
        self._params_w.setVisible(mode == "完整")
        self._flow_w.setVisible(mode == "完整")
        self._parser_w.setVisible(mode == "完整")
        self._btn_w.setVisible(not is_sl)
        self._sl_w.setVisible(is_sl)
        if is_sl:
            self._root.setContentsMargins(8, 6, 8, 6)
            self._root.setSpacing(0)
            self._sync_to_sl()
        else:
            self._root.setContentsMargins(16, 12, 16, 12)
            self._root.setSpacing(10)
            self._sync_from_sl()
        self.update()
        self.adjustSize()
        self.updateGeometry()

    def _sync_to_sl(self):
        self._sl_port.clear()
        for i in range(self._port_combo.count()):
            self._sl_port.addItem(self._port_combo.itemText(i), self._port_combo.itemData(i))
        self._sl_port.setCurrentIndex(self._port_combo.currentIndex())
        self._sl_baud.setCurrentIndex(self._baud_combo.currentIndex())
        # A disabled preview parent also makes isEnabled() false. Preserve
        # connection state instead of making that inherited state permanent.
        self._sl_conn.setEnabled(not self._connected)
        self._sl_disconn.setEnabled(self._connected)
        self._sl_status.setText(self._status.text())
        self._sl_status.setTextColor(self._status.lightColor, self._status.darkColor)

    def _sync_from_sl(self):
        idx = self._sl_port.currentIndex()
        if 0 <= idx < self._port_combo.count():
            self._port_combo.setCurrentIndex(idx)
        self._baud_combo.setCurrentIndex(self._sl_baud.currentIndex())

    # ---- connect / disconnect ----

    def _on_connect(self):
        port = self.port
        baud = self.baudrate
        if not port:
            return

        flow_map = {"无": "none", "RTS/CTS": "rtscts", "XON/XOFF": "xonxoff", "DTR/DSR": "dsrdtr"}
        parity_map = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"}

        for btn in (self._connect_btn, self._sl_conn):
            btn.setEnabled(False)
        self._set_status("连接中...", "#FF9800")

        if self._handler is None:
            return
        ok = self._handler.connect(
            port, baud,
            databits=int(self._databits_combo.currentText()),
            parity=parity_map.get(self._parity_combo.currentText(), "N"),
            stopbits=float(self._stopbits_combo.currentText()),
            flowcontrol=flow_map.get(self._flow_combo.currentText(), "none"),
            parser_type=None if self._parser_combo.currentText() == "项目设置" else self._parser_combo.currentText(),
        )
        if not ok:
            for btn in (self._connect_btn, self._sl_conn):
                btn.setEnabled(True)
            self._set_status("连接失败", "#F44336")

    def _on_disconnect(self):
        if self._handler is not None:
            self._handler.disconnect()

    def _on_serial_connected(self, port_name: str):
        self.set_connected(True)

    def _on_serial_disconnected(self):
        self.set_connected(False)

    def _on_serial_error(self, msg: str):
        self._set_status("错误", "#F44336")
        self._status.setToolTip(msg)
        self._sl_status.setToolTip(msg)

    def _set_status(self, text: str, color: str):
        colors = {
            "#888": ("#606060", "#b0b0b0"),
            "#4CAF50": ("#237b27", "#81c784"),
            "#F44336": ("#c62828", "#ff8a80"),
            "#FF9800": ("#8a4b00", "#ffb74d"),
        }
        light, dark = colors.get(color, (color, color))
        for label in (self._status, self._sl_status):
            label.setText(text)
            label.setTextColor(QColor(light), QColor(dark))

    # ---- ports / state ----

    def refresh_ports(self):
        ports = _list_all_ports()
        for combo in (self._port_combo, self._sl_port):
            combo.clear()
            for p in ports:
                combo.addItem(f"{p['port']}  {p['description']}")
            if combo.count() == 0:
                combo.addItem("无可用串口")

    def set_connected(self, connected: bool):
        self._connected = connected
        editable = not connected
        for btn in (self._connect_btn, self._sl_conn):
            btn.setEnabled(editable)
        for btn in (self._disconnect_btn, self._sl_disconn):
            btn.setEnabled(connected)
        for w in (self._port_combo, self._sl_port, self._baud_combo, self._sl_baud,
                  self._search_btn, self._sl_search,
                  self._databits_combo, self._parity_combo,
                  self._stopbits_combo, self._flow_combo, self._parser_combo):
            w.setEnabled(editable)
        if connected:
            self._set_status("● 已连接", "#4CAF50")
        else:
            self._set_status("未连接", "#888")

    # ---- property setters ----

    def set_default_parser(self, value):
        self._parser_combo.setCurrentText(value)

    def set_title(self, t): self._title.setText(t)

    def set_default_baud(self, baud: str):
        for cb in (self._baud_combo, self._sl_baud):
            idx = cb.findText(baud)
            if idx >= 0: cb.setCurrentIndex(idx)

    def set_default_databits(self, v: str):
        idx = self._databits_combo.findText(v)
        if idx >= 0: self._databits_combo.setCurrentIndex(idx)

    def set_default_parity(self, v: str):
        idx = self._parity_combo.findText(v)
        if idx >= 0: self._parity_combo.setCurrentIndex(idx)

    def set_default_stopbits(self, v: str):
        idx = self._stopbits_combo.findText(v)
        if idx >= 0: self._stopbits_combo.setCurrentIndex(idx)

    def set_default_flow(self, v: str):
        idx = self._flow_combo.findText(v)
        if idx >= 0: self._flow_combo.setCurrentIndex(idx)

    @property
    def port(self):
        c = self._sl_port if self._display_mode == "单行" else self._port_combo
        text = c.currentText()
        if not text or text == "无可用串口":
            return ""
        return text.split()[0]

    @property
    def baudrate(self):
        c = self._sl_baud if self._display_mode == "单行" else self._baud_combo
        return int(c.currentText())


from datetime import datetime as _dt

class DataRecvCard(CardWidget):
    """Data receive card for generated code."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root = QVBoxLayout(self); root.setContentsMargins(12,10,12,10); root.setSpacing(6)
        hdr = QHBoxLayout()
        self._title_lbl = StrongBodyLabel("数据接收"); hdr.addWidget(self._title_lbl)
        hdr.addStretch()
        self._counter = CaptionLabel("0 条")
        self._counter.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        hdr.addWidget(self._counter)
        root.addLayout(hdr)
        opt = QHBoxLayout(); opt.setSpacing(8)
        self._hex_cb = CheckBox("HEX显示"); opt.addWidget(self._hex_cb)
        self._scroll_cb = CheckBox("自动滚动"); self._scroll_cb.setChecked(True); opt.addWidget(self._scroll_cb)
        opt.addStretch()
        self._clear_btn = PushButton("清空"); self._clear_btn.setFixedWidth(60)
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
    def _on_connected(self, port): self._sys(f"已连接: {port}")
    def _on_disconnected(self): self._sys("已断开")
    def _on_raw(self, data):
        ts = _dt.now().strftime("%H:%M:%S.%f")[:-3]
        if self._hex_cb.isChecked():
            txt = " ".join(f"{b:02X}" for b in data)
        else:
            txt = data.decode("utf-8", errors="replace").rstrip("\r\n")
            if not txt: return
        self._text.append(f'<span style="color:#9399b2">[{ts}]</span> '
                          f'<span style="color:#a6e3a1">&lt;&lt; {_log_html(txt)}</span>')
        self._count += 1; self._counter.setText(f"{self._count} 条")
        self._trim(); self._do_scroll()
    def _on_sent(self, data):
        ts = _dt.now().strftime("%H:%M:%S.%f")[:-3]
        if self._hex_cb.isChecked():
            txt = " ".join(f"{b:02X}" for b in data)
        else:
            txt = data.decode("utf-8", errors="replace").rstrip("\r\n")
            if not txt: return
        self._text.append(f'<span style="color:#9399b2">[{ts}]</span> '
                          f'<span style="color:#f9e2af">&gt;&gt; {_log_html(txt)}</span>')
        self._trim(); self._do_scroll()
    def _sys(self, msg):
        ts = _dt.now().strftime("%H:%M:%S")
        self._text.append(f'<span style="color:#74c7ec">[{ts}] --- {_log_html(msg)} ---</span>')
        self._trim()
    def _do_scroll(self):
        if self._scroll_cb.isChecked():
            sb = self._text.verticalScrollBar(); sb.setValue(sb.maximum())
    def _clear(self):
        self._text.clear(); self._count = 0; self._counter.setText("0 条")
    def _trim(self):
        doc = self._text.document()
        while doc.blockCount() > self._max_lines:
            c = self._text.textCursor(); c.movePosition(c.Start)
            c.select(c.BlockUnderCursor); c.removeSelectedText(); c.deleteChar()
    def set_title(self, t): self._title_lbl.setText(t)
    def set_max_lines(self, count):
        self._max_lines = max(50, count)
        self._trim()


class MainUI(TitleBarLifecycleMixin, FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('串口采集 Demo')
        self.resize(1180, 910)

        self._page = QWidget()
        self._page.setObjectName("mainPage")
        self._page.setFixedSize(1080, 810)

        self.widgets = {}
        self._theme_containers = []
        self._create_widgets()

        scroll = QScrollArea()
        scroll.setWidget(self._page)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignCenter)
        scroll.setObjectName("scrollPage")
        scroll.setStyleSheet("QScrollArea#scrollPage { background: transparent; border: none; }")

        self.addSubInterface(scroll, FIF.HOME, "主界面")
        self.apply_theme()
        self._external_connections = SignalConnections(self)
        self._external_connections.connect(
            qconfig.themeChangedFinished, self.apply_theme)



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

        self.widgets['title'] = BodyLabel('串口采集 Demo', self._page); _font = self.widgets['title'].font(); _font.setPointSize(22); _font.setBold(True); self.widgets['title'].setFont(_font); self.widgets['title'].setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.widgets['title'].setGeometry(24, 12, 850, 36)
        self.widgets['title'].show()

        self.widgets['help'] = BodyLabel('连接设备查看温度与压力，可控制设备运行、保存曲线或发送自定义命令。', self._page); _font = self.widgets['help'].font(); _font.setPointSize(13); _font.setBold(False); self.widgets['help'].setFont(_font); self.widgets['help'].setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.widgets['help'].setGeometry(24, 50, 1020, 28)
        self.widgets['help'].show()

        self.widgets['serial'] = SerialConfigCard(self._page); self.widgets['serial'].set_title('串口配置'); self.widgets['serial'].set_display_mode('单行'); self.widgets['serial'].set_default_baud('115200'); self.widgets['serial'].set_default_databits('8'); self.widgets['serial'].set_default_parity('None'); self.widgets['serial'].set_default_stopbits('1'); self.widgets['serial'].set_default_flow('无'); self.widgets['serial'].set_default_parser('项目设置')
        self.widgets['serial'].setGeometry(24, 90, 1032, 48)
        self.widgets['serial'].show()

        self.widgets['temperature'] = NumericDisplay(self._page); self.widgets['temperature'].set_title('温度'); self.widgets['temperature'].set_unit('°C'); self.widgets['temperature'].set_value('0.00'); self.widgets['temperature'].set_font_size(34)
        self.widgets['temperature'].setGeometry(24, 155, 240, 120)
        self.widgets['temperature'].show()

        self.widgets['pressure'] = NumericDisplay(self._page); self.widgets['pressure'].set_title('压力'); self.widgets['pressure'].set_unit('kPa'); self.widgets['pressure'].set_value('0.00'); self.widgets['pressure'].set_font_size(34)
        self.widgets['pressure'].setGeometry(282, 155, 240, 120)
        self.widgets['pressure'].show()

        self.widgets['pressure_ring'] = ProgressRingDisplay(self._page); self.widgets['pressure_ring'].set_label('压力满量程'); self.widgets['pressure_ring'].set_maximum(100); self.widgets['pressure_ring'].set_value(0)
        self.widgets['pressure_ring'].setGeometry(530, 145, 160, 140)
        self.widgets['pressure_ring'].show()

        self.widgets['running'] = LEDIndicator(self._page); self.widgets['running'].set_color('green'); self.widgets['running'].set_label('设备运行'); self.widgets['running'].set_on(False)
        self.widgets['running'].setGeometry(730, 154, 220, 40)
        self.widgets['running'].show()

        self.widgets['start'] = PushButton('启动设备', self._page); self.widgets['start'].setEnabled(True)
        self.widgets['start'].setGeometry(712, 217, 150, 40)
        self.widgets['start'].show()
        self.widgets['start'].clicked.connect(lambda: self._send_text_command(str('START'), '\r\n'))

        self.widgets['stop'] = PushButton('停止设备', self._page); self.widgets['stop'].setEnabled(True)
        self.widgets['stop'].setGeometry(886, 217, 150, 40)
        self.widgets['stop'].show()
        self.widgets['stop'].clicked.connect(lambda: self._send_text_command(str('STOP'), '\r\n'))

        self.widgets['chart'] = RealtimeLineChart(self._page); self.widgets['chart'].configure('[{"name": "温度", "parseMode": "键值匹配", "key": "temperature", "jsonPath": "", "byteOffset": 0, "dataType": "float32", "byteOrder": "大端(BE)", "frameHeader": "", "frameTail": "", "regIndex": 0, "mbDataType": "uint16", "mbRegOrder": "大端(AB CD)", "mbFcFilter": -1, "mbSlaveFilter": -1}, {"name": "压力", "parseMode": "键值匹配", "key": "pressure", "jsonPath": "", "byteOffset": 0, "dataType": "float32", "byteOrder": "大端(BE)", "frameHeader": "", "frameTail": "", "regIndex": 0, "mbDataType": "uint16", "mbRegOrder": "大端(AB CD)", "mbFcFilter": -1, "mbSlaveFilter": -1}]', 200); self.widgets['chart'].set_title('实时采样')
        self.widgets['chart'].setGeometry(24, 355, 642, 310)
        self.widgets['chart'].show()

        self.widgets['monitor_tabs'] = QTabWidget(self._page); self.widgets['monitor_tabs'].setObjectName('tabContainer'); self._theme_containers.append((self.widgets['monitor_tabs'], 'tabs')); self.widgets['monitor_tabs'].addTab(QWidget(), '原始数据'); self.widgets['monitor_tabs'].addTab(QWidget(), '字段表格'); self.widgets['monitor_tabs'].addTab(QWidget(), '事件日志')
        self.widgets['monitor_tabs'].setGeometry(688, 355, 368, 310)
        self.widgets['monitor_tabs'].show()

        self.widgets['receive'] = DataRecvCard(self.widgets['monitor_tabs'].widget(0)); self.widgets['receive'].set_title('原始串口数据'); self.widgets['receive'].set_max_lines(200)
        place_tab_child(self.widgets['monitor_tabs'], self.widgets['receive'], 1, 33, 366, 276)
        self.widgets['receive'].show()

        self.widgets['live_table'] = DataTableWidget(self.widgets['monitor_tabs'].widget(1)); self.widgets['live_table'].set_columns(['数据字段', '当前值']); self.widgets['live_table'].set_record_mode('最新值'); self.widgets['live_table'].set_max_rows(20)
        place_tab_child(self.widgets['monitor_tabs'], self.widgets['live_table'], 1, 33, 366, 276)
        self.widgets['live_table'].show()

        self.widgets['event_log'] = LogDisplayBox(self.widgets['monitor_tabs'].widget(2)); self.widgets['event_log'].set_max_lines(200)
        place_tab_child(self.widgets['monitor_tabs'], self.widgets['event_log'], 1, 33, 366, 276)
        self.widgets['event_log'].show()

        self.widgets['command'] = LineEdit(self._page); self.widgets['command'].setPlaceholderText('输入 READ、START 或 STOP，按回车发送'); self.widgets['command'].setText(''); self.widgets['command'].setReadOnly(False)
        self.widgets['command'].setGeometry(24, 690, 440, 36)
        self.widgets['command'].show()
        self.widgets['command'].returnPressed.connect(lambda: self._send_text_command(str(self.widgets['command'].text().strip()), '\r\n') if self.widgets['command'].text().strip() else None)

        self.widgets['protocol_hint'] = BodyLabel('默认 115200 / 8N1 · 每行 JSON 或键值文本', self._page); _font = self.widgets['protocol_hint'].font(); _font.setPointSize(12); _font.setBold(False); self.widgets['protocol_hint'].setFont(_font); self.widgets['protocol_hint'].setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.widgets['protocol_hint'].setGeometry(490, 690, 566, 36)
        self.widgets['protocol_hint'].show()

        self.widgets['setpoint_label'] = BodyLabel('压力中心', self._page); _font = self.widgets['setpoint_label'].font(); _font.setPointSize(13); _font.setBold(False); self.widgets['setpoint_label'].setFont(_font); self.widgets['setpoint_label'].setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.widgets['setpoint_label'].setGeometry(24, 295, 110, 36)
        self.widgets['setpoint_label'].show()

        self.widgets['setpoint_slider'] = Slider(Qt.Horizontal, self._page); self.widgets['setpoint_slider'].setRange(20, 80); self.widgets['setpoint_slider'].setValue(50)
        self.widgets['setpoint_slider'].setGeometry(140, 295, 300, 36)
        self.widgets['setpoint_slider'].show()
        SendOnRelease(self.widgets['setpoint_slider'], lambda v: self._send_text_command(str(v), '\r\n'))

        self.widgets['setpoint_spin'] = SpinBox(self._page); self.widgets['setpoint_spin'].setRange(20, 80); self.widgets['setpoint_spin'].setValue(50); self.widgets['setpoint_spin'].setSuffix(' kPa')
        self.widgets['setpoint_spin'].setGeometry(460, 295, 160, 36)
        self.widgets['setpoint_spin'].show()
        self.widgets['setpoint_spin'].valueChanged.connect(lambda v: self._send_text_command(str(v), '\r\n'))

        _tw = QWidget(self._page); _tl = QHBoxLayout(_tw); _tl.setContentsMargins(0,0,0,0); _sw = SwitchButton(); _sw.setChecked(False); _tl.addWidget(BodyLabel('设备运行')); _tl.addStretch(); _tl.addWidget(_sw); _tw._switch = _sw; self.widgets['run_switch'] = _tw
        self.widgets['run_switch'].setGeometry(710, 295, 325, 36)
        self.widgets['run_switch'].show()
        self.widgets['run_switch']._switch.checkedChanged.connect(lambda c: self._send_text_command(str('START'), '\r\n') if c else self._send_text_command(str('STOP'), '\r\n'))

        self.widgets['reserved'] = PushButton('预留操作（禁用）', self._page); self.widgets['reserved'].setEnabled(False)
        self.widgets['reserved'].setGeometry(24, 745, 210, 36)
        self.widgets['reserved'].show()
        self.widgets['reserved'].clicked.connect(lambda: self._send_text_command(str('STOP'), '\r\n'))

        self.widgets['protocol_info'] = LineEdit(self._page); self.widgets['protocol_info'].setPlaceholderText(''); self.widgets['protocol_info'].setText('协议: JSON / 115200 / 8N1'); self.widgets['protocol_info'].setReadOnly(True)
        self.widgets['protocol_info'].setGeometry(250, 745, 320, 36)
        self.widgets['protocol_info'].show()

        self.widgets['command_presets'] = ComboBox(self._page); self.widgets['command_presets'].addItems(['停止设备', '读取一次', '启动设备']); self.widgets['command_presets'].setCurrentIndex(1)
        self.widgets['command_presets'].setGeometry(590, 745, 240, 36)
        self.widgets['command_presets'].show()
        self.widgets['command_presets'].currentIndexChanged.connect(lambda i, _cmds=['STOP', 'READ', 'START']: self._send_text_command(str((_cmds[i] if i < len(_cmds) and _cmds[i] else self.widgets['command_presets'].currentText())), '\r\n') if i >= 0 and (_cmds[i] if i < len(_cmds) and _cmds[i] else self.widgets['command_presets'].currentText()) else None)

        self.widgets['preset_hint'] = BodyLabel('快捷命令 · 选择后发送', self._page); _font = self.widgets['preset_hint'].font(); _font.setPointSize(12); _font.setBold(False); self.widgets['preset_hint'].setFont(_font); self.widgets['preset_hint'].setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.widgets['preset_hint'].setGeometry(850, 745, 200, 36)
        self.widgets['preset_hint'].show()


    def _send_text_command(self, cmd, suffix="\r\n"):
        if hasattr(self, '_comm_hub') and self._comm_hub.is_connected:
            self._comm_hub.send_text(cmd + suffix)

    def _command_error(self, error):
        InfoBar.error(title="提示", content=str(error), duration=2000, parent=self)

    def _send_hex_command(self, cmd, header="", tail=""):
        if hasattr(self, '_comm_hub') and self._comm_hub.is_connected:
            try:
                frame = command_hex_frame(cmd, header, tail)
            except ValueError as exc:
                self._command_error(exc)
                return
            self._comm_hub.send(frame)

    def _send_modbus(self, slave, func, address, value=1):
        # One request per connected link: RTU, or MBAP where the link parses Modbus TCP.
        if hasattr(self, '_comm_hub') and self._comm_hub.is_connected:
            try:
                send_modbus_command(self._comm_hub, slave, func, address, value)
            except ValueError as exc:
                self._command_error(exc)

    def _send_packed_value(self, value, fmt, cast=int, tpl="{value}", header="", tail=""):
        if hasattr(self, '_comm_hub') and self._comm_hub.is_connected:
            try:
                frame = command_packed_frame(value, fmt, cast, tpl, header, tail)
            except ValueError as exc:
                self._command_error(exc)
                return
            self._comm_hub.send(frame)
