# coding: utf-8
"""Property editor panel — dynamic form driven by widget metadata."""
from typing import Optional

from PyQt5 import sip
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFormLayout,
    QSizePolicy, QFrame, QFileDialog,
)
from qfluentwidgets import (
    ScrollArea, StrongBodyLabel, BodyLabel, CardWidget,
    LineEdit, SpinBox, DoubleSpinBox, SwitchButton,
    ComboBox, EditableComboBox, TextEdit, CaptionLabel, ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.signal_bus import signalBus
from app.core.signal_lifetime import SignalConnections
from app.core.widget_registry import registry
from app.core.binding_values import DEFAULT_MODBUS_AREA, MODBUS_AREAS
from app.core.data_binding import BIND_PROPERTIES
from app.core.modbus_master import MODBUS_PARSERS
from app.core.project import LINK_CARD_TYPES
from app.core.protocol_parser import (
    HEX_CHECKSUMS, HEX_ENDIANS, HEX_LENGTH_COVERS, LINE_ENCODINGS, LINE_KV_SEPARATORS, PARSER_TYPES,
    hex_field,
)
from app.widgets.base import PropType, PropDef, WidgetMeta
from app.designer.canvas_item import CanvasItem


_MODE_VISIBILITY = {
    "文本":   {"command", "onCommand", "offCommand", "commandNewline", "commandTemplate"},
    "HEX":    {"command", "onCommand", "offCommand", "commandTemplate",
               "frameHeader", "frameTail", "dataType", "byteOrder"},
    "Modbus": {"mbSlave", "mbFunc", "mbAddress", "mbValue", "mbDataType", "mbRegOrder"},
}
_MODE_FIELDS = {
    "command", "onCommand", "offCommand", "commandNewline", "commandTemplate",
    "frameHeader", "frameTail", "dataType", "byteOrder",
    "mbSlave", "mbFunc", "mbAddress", "mbValue", "mbDataType", "mbRegOrder",
}

_SEND_TOGGLE_FIELDS = {"commandMode", "commands"}

# A link card's Modbus polling settings, shown while its own parser is a Modbus one (they still count
# when it uses the project's settings).
_MODBUS_LINK_FIELDS = ("modbusPeriod", "modbusTimeout", "modbusSlave")

# Chart per-curve fields visibility based on curveParseMode
_CHART_PARSE_VIS = {
    "键值匹配":  {"curveKey"},
    "JSON路径":   {"curveJsonPath"},
    "HEX字节提取": {"curveByteOffset", "curveDataType", "curveByteOrder",
                      "curveFrameHeader", "curveFrameTail"},
    "Modbus":     {"curveRegIndex", "curveMbDataType", "curveMbRegOrder",
                   "curveMbFcFilter", "curveMbSlaveFilter", "curveMbArea"},
}
_CHART_PARSE_ALL = set()
for _v in _CHART_PARSE_VIS.values():
    _CHART_PARSE_ALL |= _v


# The frame-format rows each parsing mode shows, by parserConfig key; 解析模式 always shows.
_FRAME_KEYS = {
    "line": ("separator", "terminator", "kvSeparator", "encoding"),
    "hex": ("header", "footer", "lengthOffset", "lengthSize", "lengthEndian", "lengthCovers",
            "fixedLength", "checksum", "checksumStart", "checksumEndian", "idleTimeout", "fields"),
}


# The 行结束符 row shows a terminator with backslash escapes, as people write one.
_TERMINATOR_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\"}
TERMINATOR_CHOICES = ("\\n", "\\r\\n", "\\r", ";")


def terminator_text(value) -> str:
    """A line terminator as the 行结束符 row shows it: "\\r\\n" for CR LF, "\\\\" for a backslash."""
    if not isinstance(value, str):
        return str(value)
    return (value.replace("\\", "\\\\").replace("\n", "\\n")
            .replace("\r", "\\r").replace("\t", "\\t"))


def terminator_from_text(text: str) -> str:
    """The terminator typed text stands for: \\n \\r \\t and \\\\ are escapes; any other
    character, a backslash before anything else included, stands for itself."""
    out, index = [], 0
    while index < len(text):
        pair = text[index:index + 2]
        if pair[:1] == "\\" and pair[1:] in _TERMINATOR_ESCAPES:
            out.append(_TERMINATOR_ESCAPES[pair[1:]])
            index += 2
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def hex_fields_text(fields) -> str:
    """A hex field table as the text the 字段表 row edits: one 名字,偏移,长度,类型[,字节序] per line."""
    if not isinstance(fields, list):
        return ""
    return "\n".join(",".join(str(part) for part in item)
                     for item in fields if isinstance(item, (list, tuple)))


def hex_fields_from_text(text: str):
    """(fields, None) for a valid table, or (None, the number of its first bad line). Lines starting
    with # are comments, and a full-width comma separates as well."""
    fields = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.replace("，", ",").split(",")]
        try:
            if len(parts) not in (4, 5) or not parts[0]:
                raise ValueError(line)
            field = [parts[0], int(parts[1]), int(parts[2]), *parts[3:]]
            hex_field(field)  # the parser's own check: type, size and byte order
        except ValueError:
            return None, number
        fields.append(field)
    return fields, None


class _FormRows:
    """The rows of one QFormLayout, in their order. Hiding a row takes it out of the layout and showing
    it puts it back in its place, so a hidden row takes no room: Qt 5's form layout keeps the vertical
    spacing of a row whose widgets are only hidden, which left blank bands between the rows shown."""

    def __init__(self, form):
        self.form = form
        self._rows = []  # [label, field, in the layout]

    def add(self, label, field=None):
        if field is None:
            self.form.addRow(label)
        else:
            self.form.addRow(label, field)
        self._rows.append([label, field, True])

    def __contains__(self, field):
        return any(row[1] is field for row in self._rows)

    def set_visible(self, field, visible):
        index, row = next((index, row) for index, row in enumerate(self._rows) if row[1] is field)
        label, field, shown = row
        if shown != visible:
            position = sum(1 for other in self._rows[:index] if other[2])
            if visible:
                self.form.insertRow(position, label, field)
            else:
                self.form.takeRow(position)  # the widgets stay with the card, out of the layout
            row[2] = visible
        label.setVisible(visible)
        field.setVisible(visible)


def _int_setting(value, default):
    return value if isinstance(value, int) and not isinstance(value, bool) else default


class _TabNamesEdit(TextEdit):
    """Commit a complete list of page names, not each transient keystroke."""
    editingFinished = pyqtSignal()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()


class PropertyEditor(ScrollArea):
    """Right panel showing editable properties for the selected widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("propertyEditor")
        self.setWidgetResizable(True)
        self.setMinimumWidth(240)
        self.setMaximumWidth(320)

        self._container = QWidget()
        self._container.setObjectName("propEditorContainer")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignTop)
        self.setWidget(self._container)

        self._current_item: Optional[CanvasItem] = None
        self._editors = {}  # prop_name -> editor widget
        self._prop_rows = {}  # prop_name -> (label_widget, editor_widget)
        self._updating = False  # prevent feedback loops
        self._project_source = None  # returns the open ProjectData; saving replaces it
        self._project_frame_rows = {}  # parserConfig key -> (label, editor) of 默认帧格式
        self._card_frame_section = None  # a link card's 帧格式 card, and its rows
        self._card_frame_rows = {}
        self._row_forms = []  # the _FormRows of the forms shown, whose rows come and go

        self._empty_label = BodyLabel("选择一个控件以编辑属性")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._empty_label)

        self._external_connections = SignalConnections(self)
        self._external_connections.connect(
            signalBus.widgetSelected, self._on_widget_selected)
        self._external_connections.connect(
            signalBus.widgetDeselected, self._on_deselected)
        self._external_connections.connect(
            signalBus.projectSaved, self._sync_saved_image_path)
        for replaced in (signalBus.projectLoaded, signalBus.projectNew):
            self._external_connections.connect(replaced, self._on_project_replaced)
        self._scene_connections = SignalConnections(self)

        self.setStyleSheet(
            "QScrollArea, #propEditorContainer { background: transparent; border: none; }"
        )

    def set_scene(self, scene):
        self._scene_connections.clear()
        self._scene = scene
        self._scene_connections.connect(
            scene.aboutToSerialize, self.commit_pending_edits)

    def _on_widget_selected(self, widget_id: str):
        if not hasattr(self, "_scene"):
            return
        item = self._scene.get_item_by_id(widget_id)
        if item:
            self._load_item(item)

    def _on_deselected(self):
        self._clear()

    def set_project_source(self, source):
        """``source()`` is the open project, whose frame format shows while nothing is selected."""
        self._project_source = source
        if self._current_item is None:
            self._clear()

    def _project(self):
        return self._project_source() if self._project_source is not None else None

    def _on_project_replaced(self, *_args):
        if self._current_item is None:
            self._clear()

    def _sync_saved_image_path(self, _path):
        item = self._current_item
        if item is None or sip.isdeleted(item) or item.type_name != "ImageDisplay":
            return
        editor = self._editors.get("imagePath")
        if editor is not None:
            field = editor.findChild(LineEdit)
            if field is not None:
                self._updating = True
                field.setText(item.properties.get("imagePath", ""))
                self._updating = False

    def _clear(self):
        self.commit_pending_edits()
        self._current_item = None
        self._editors.clear()
        self._forget_frame_sections()
        while self._layout.count():
            child = self._layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._empty_label = BodyLabel("选择一个控件以编辑属性")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._empty_label)
        project = self._project()
        if project is not None:
            serial = project.serial
            config = serial.get("parserConfig")
            section, self._project_frame_rows = self._frame_format_section(
                "默认帧格式", serial.get("parser", "line"),
                config if isinstance(config, dict) else {},
                self._write_project_frame, with_mode=True)
            self._layout.addWidget(section)

    def _load_item(self, item: CanvasItem):
        self.commit_pending_edits()
        self._current_item = item
        self._editors.clear()
        self._prop_rows.clear()
        self._forget_frame_sections()

        while self._layout.count():
            child = self._layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        meta = registry.get(item.type_name)
        if not meta:
            return

        # header
        header_card = CardWidget()
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(12, 8, 12, 8)
        title = StrongBodyLabel(f"{meta.display_name}")
        subtitle = CaptionLabel(f"ID: {item.widget_id}")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        self._layout.addWidget(header_card)

        # geometry card
        geo_card = CardWidget()
        geo_layout = QFormLayout(geo_card)
        geo_layout.setContentsMargins(12, 8, 12, 8)
        geo_layout.setSpacing(6)
        geo_layout.addRow(StrongBodyLabel("位置与尺寸"))

        pos = item.pos()
        rect = item.rect()
        for label_text, val, attr in [
            ("X", pos.x(), "geo_x"), ("Y", pos.y(), "geo_y"),
            ("宽度", rect.width(), "geo_w"), ("高度", rect.height(), "geo_h"),
        ]:
            spin = SpinBox()
            minimum = {"geo_w": meta.min_width, "geo_h": item.min_height()}.get(attr, 0)
            spin.setRange(minimum, 9999)
            spin.setValue(int(val))
            spin.valueChanged.connect(lambda v, a=attr: self._on_geo_changed(a, v))
            self._editors[attr] = spin
            geo_layout.addRow(BodyLabel(label_text), spin)

        self._layout.addWidget(geo_card)

        # properties card
        if meta.properties:
            props_card = CardWidget()
            props_layout = QFormLayout(props_card)
            props_layout.setContentsMargins(12, 8, 12, 8)
            props_layout.setSpacing(6)
            props_rows = self._rows_of(props_layout)
            props_rows.add(StrongBodyLabel("属性"))

            for prop_def in meta.properties:
                editor = self._create_editor(prop_def, item.properties.get(prop_def.name, prop_def.default))
                if editor:
                    label = BodyLabel(prop_def.label)
                    if BIND_PROPERTIES.get(item.type_name) == prop_def.name:
                        label.setText(f"{prop_def.label} ⚡")
                        label.setToolTip("可绑定到串口数据")
                    props_rows.add(label, editor)
                    self._editors[prop_def.name] = editor
                    self._prop_rows[prop_def.name] = (label, editor)

            self._layout.addWidget(props_card)

            if item.type_name in LINK_CARD_TYPES:
                self._apply_link_parser_visibility(item.properties.get("defaultParser", "项目设置"))
                self._card_frame_section = self._card_frame_format()
                self._layout.addWidget(self._card_frame_section)

            cur_mode = item.properties.get("commandMode", "文本")
            self._apply_mode_visibility(cur_mode)

            if ("sendOnEnter" in self._prop_rows
                    or "sendOnSelect" in self._prop_rows
                    or "sendOnChange" in self._prop_rows):
                send_on = (item.properties.get("sendOnEnter", False)
                           or item.properties.get("sendOnSelect", False)
                           or item.properties.get("sendOnChange", False))
                self._apply_send_toggle_visibility(send_on)

            if item.type_name == "TabWidget":
                self._sync_tab_editors()
                self._editors["tabNames"].setToolTip(
                    "每行一个标签，离开输入框后应用，按序号保留页面。减少页数时，"
                    "超出页的控件移至最后一页；名称为空时保留“标签1”。")

            if item.type_name == "RealtimeChart":
                self._load_curve_editors(item)
                pm = item.properties.get(
                    f"_curve_{int(item.properties.get('currentCurve', 0))}_parseMode",
                    "键值匹配")
                self._apply_chart_parse_visibility(pm)

        # binding card — for the widgets the runtime binds (data_binding.BIND_PROPERTIES)
        if item.type_name in BIND_PROPERTIES:
            binding_card = CardWidget()
            binding_layout = QFormLayout(binding_card)
            binding_layout.setContentsMargins(12, 8, 12, 8)
            binding_layout.setSpacing(6)
            binding_rows = self._rows_of(binding_layout)
            binding_rows.add(StrongBodyLabel("数据绑定"))

            bd = item.binding or {}

            self._bind_mode_combo = ComboBox()
            self._bind_mode_combo.addItems(["键值匹配", "JSON路径", "HEX字节提取", "Modbus"])
            cur_pm = bd.get("parseMode", "键值匹配")
            if cur_pm in ["键值匹配", "JSON路径", "HEX字节提取", "Modbus"]:
                self._bind_mode_combo.setCurrentText(cur_pm)
            self._bind_mode_combo.currentTextChanged.connect(self._on_bind_mode_changed)
            binding_rows.add(BodyLabel("解析模式"), self._bind_mode_combo)

            self._bind_key_edit = LineEdit()
            self._bind_key_edit.setPlaceholderText("字段名 (如 temperature)")
            self._bind_key_edit.setText(bd.get("key", ""))
            self._bind_key_edit.textChanged.connect(self._on_binding_changed)
            self._bind_key_label = BodyLabel("绑定字段")
            binding_rows.add(self._bind_key_label, self._bind_key_edit)

            self._bind_json_edit = LineEdit()
            self._bind_json_edit.setPlaceholderText("路径 (如 data.sensors.0.temp)")
            self._bind_json_edit.setText(bd.get("jsonPath", ""))
            self._bind_json_edit.textChanged.connect(self._on_binding_changed)
            self._bind_json_label = BodyLabel("JSON路径")
            binding_rows.add(self._bind_json_label, self._bind_json_edit)

            self._bind_offset_spin = SpinBox()
            self._bind_offset_spin.setRange(0, 9999)
            self._bind_offset_spin.setValue(int(bd.get("byteOffset", 0)))
            self._bind_offset_spin.valueChanged.connect(self._on_binding_changed)
            self._bind_offset_label = BodyLabel("字节偏移")
            binding_rows.add(self._bind_offset_label, self._bind_offset_spin)

            self._bind_dtype_combo = ComboBox()
            self._bind_dtype_combo.addItems([
                "uint8", "int8", "uint16", "int16",
                "uint32", "int32", "float32", "ASCII"])
            dt = bd.get("dataType", "uint16")
            self._bind_dtype_combo.setCurrentText(dt)
            self._bind_dtype_combo.currentTextChanged.connect(self._on_binding_changed)
            self._bind_dtype_label = BodyLabel("数据类型")
            binding_rows.add(self._bind_dtype_label, self._bind_dtype_combo)

            self._bind_order_combo = ComboBox()
            self._bind_order_combo.addItems(["大端(BE)", "小端(LE)"])
            bo = bd.get("byteOrder", "大端(BE)")
            self._bind_order_combo.setCurrentText(bo)
            self._bind_order_combo.currentTextChanged.connect(self._on_binding_changed)
            self._bind_order_label = BodyLabel("字节序")
            binding_rows.add(self._bind_order_label, self._bind_order_combo)

            self._bind_header_edit = LineEdit()
            self._bind_header_edit.setPlaceholderText("如 AA 55")
            self._bind_header_edit.setText(bd.get("frameHeader", ""))
            self._bind_header_edit.textChanged.connect(self._on_binding_changed)
            self._bind_header_label = BodyLabel("帧头(HEX)")
            binding_rows.add(self._bind_header_label, self._bind_header_edit)

            self._bind_tail_edit = LineEdit()
            self._bind_tail_edit.setPlaceholderText("如 0D 0A")
            self._bind_tail_edit.setText(bd.get("frameTail", ""))
            self._bind_tail_edit.textChanged.connect(self._on_binding_changed)
            self._bind_tail_label = BodyLabel("帧尾(HEX)")
            binding_rows.add(self._bind_tail_label, self._bind_tail_edit)

            self._bind_mb_area_combo = ComboBox()
            self._bind_mb_area_combo.addItems(list(MODBUS_AREAS))
            self._bind_mb_area_combo.setCurrentText(bd.get("mbArea", DEFAULT_MODBUS_AREA))
            self._bind_mb_area_combo.currentTextChanged.connect(self._on_binding_changed)
            self._bind_mb_area_label = BodyLabel("寄存器区")
            binding_rows.add(self._bind_mb_area_label, self._bind_mb_area_combo)

            self._bind_mb_reg_spin = SpinBox()
            self._bind_mb_reg_spin.setRange(0, 65535)
            self._bind_mb_reg_spin.setValue(int(bd.get("mbRegIndex", 0)))
            self._bind_mb_reg_spin.valueChanged.connect(self._on_binding_changed)
            self._bind_mb_reg_label = BodyLabel("寄存器地址")
            binding_rows.add(self._bind_mb_reg_label, self._bind_mb_reg_spin)

            self._bind_mb_dtype_combo = ComboBox()
            self._bind_mb_dtype_combo.addItems([
                "uint16", "int16", "uint32", "int32", "float32"])
            self._bind_mb_dtype_combo.setCurrentText(bd.get("mbDataType", "uint16"))
            self._bind_mb_dtype_combo.currentTextChanged.connect(self._on_binding_changed)
            self._bind_mb_dtype_label = BodyLabel("数据类型")
            binding_rows.add(self._bind_mb_dtype_label, self._bind_mb_dtype_combo)

            self._bind_mb_regorder_combo = ComboBox()
            self._bind_mb_regorder_combo.addItems(["大端(AB CD)", "小端(CD AB)"])
            self._bind_mb_regorder_combo.setCurrentText(bd.get("mbRegOrder", "大端(AB CD)"))
            self._bind_mb_regorder_combo.currentTextChanged.connect(self._on_binding_changed)
            self._bind_mb_regorder_label = BodyLabel("寄存器序")
            binding_rows.add(self._bind_mb_regorder_label, self._bind_mb_regorder_combo)

            self._bind_mb_fc_spin = SpinBox()
            self._bind_mb_fc_spin.setRange(-1, 255)
            self._bind_mb_fc_spin.setValue(int(bd.get("mbFcFilter", -1)))
            self._bind_mb_fc_spin.valueChanged.connect(self._on_binding_changed)
            self._bind_mb_fc_label = BodyLabel("功能码过滤(-1=全部)")
            binding_rows.add(self._bind_mb_fc_label, self._bind_mb_fc_spin)

            self._bind_mb_slave_spin = SpinBox()
            self._bind_mb_slave_spin.setRange(-1, 247)
            self._bind_mb_slave_spin.setValue(int(bd.get("mbSlaveFilter", -1)))
            self._bind_mb_slave_spin.valueChanged.connect(self._on_binding_changed)
            self._bind_mb_slave_label = BodyLabel("从站过滤(-1=全部)")
            binding_rows.add(self._bind_mb_slave_label, self._bind_mb_slave_spin)

            # How often the Modbus poller reads this binding's block.
            self._bind_mb_period_spin = SpinBox()
            self._bind_mb_period_spin.setRange(0, 60000)
            self._bind_mb_period_spin.setValue(_int_setting(bd.get("mbPeriod", 0), 0))
            self._bind_mb_period_spin.valueChanged.connect(self._on_binding_changed)
            self._bind_mb_period_label = BodyLabel("采集周期(ms)")
            for widget in (self._bind_mb_period_label, self._bind_mb_period_spin):
                widget.setToolTip("0 = 用默认周期（链路卡片的「默认轮询(ms)」，默认 500）")
            binding_rows.add(self._bind_mb_period_label, self._bind_mb_period_spin)

            self._bind_expr_edit = LineEdit()
            self._bind_expr_edit.setPlaceholderText("表达式 (如 value * 0.1)")
            self._bind_expr_edit.setText(bd.get("expression", ""))
            self._bind_expr_edit.textChanged.connect(self._on_binding_changed)
            binding_rows.add(BodyLabel("转换表达式"), self._bind_expr_edit)

            self._layout.addWidget(binding_card)
            self._apply_bind_mode_visibility(cur_pm)

        self._layout.addStretch()

    # ---- frame format: the project's 默认帧格式 and a link card's 帧格式 ----

    def _forget_frame_sections(self):
        self._project_frame_rows = {}
        self._card_frame_section = None
        self._card_frame_rows = {}
        self._row_forms = []

    def _rows_of(self, form):
        rows = _FormRows(form)
        self._row_forms.append(rows)
        return rows

    def _show_row(self, field, visible):
        """Show or hide the form row of ``field`` (an editor), taking no room while hidden."""
        for rows in self._row_forms:
            if field in rows:
                rows.set_visible(field, visible)
                return

    def _frame_format_section(self, title, mode, config, write, with_mode=False):
        """A card with the frame-format rows for ``config``, showing those of ``mode``.

        ``write(key, value)`` stores one edited key. ``with_mode`` adds the 解析模式 row,
        written under the key ``parser``; a link card has its own 默认解析模式 property instead.
        """
        card = CardWidget()
        form = QFormLayout(card)
        form.setContentsMargins(12, 8, 12, 8)
        form.setSpacing(6)
        form_rows = self._rows_of(form)
        form_rows.add(StrongBodyLabel(title))
        rows = {}

        def add(key, text, editor, tip=""):
            label = BodyLabel(text)
            if tip:
                label.setToolTip(tip)
                editor.setToolTip(tip)
            form_rows.add(label, editor)
            rows[key] = (label, editor)

        def combo(key, options, default, convert=str, normal=str):
            editor = ComboBox()
            editor.addItems(options)
            current = normal(config.get(key, default))
            if current in options:
                editor.setCurrentText(current)
            editor.currentTextChanged.connect(lambda value: write(key, convert(value)))
            return editor

        def spin(key, low, high, default):
            editor = SpinBox()
            editor.setRange(low, high)
            editor.setValue(max(low, min(high, _int_setting(config.get(key), default))))
            editor.valueChanged.connect(lambda value: write(key, value))
            return editor

        def line_edit(key, default, placeholder, hex_text=False):
            # HEX text loses its stray spaces; other text is kept as typed, so a separator
            # may be a single space.
            editor = LineEdit()
            value = config.get(key, default)
            editor.setText(value if isinstance(value, str) else str(value))
            editor.setPlaceholderText(placeholder)
            editor.textChanged.connect(
                lambda value: write(key, value.strip() if hex_text else value))
            return editor

        if with_mode:
            def on_mode(value):
                write("parser", value)
                self._show_frame_rows(rows, value)
            editor = ComboBox()
            editor.addItems(list(PARSER_TYPES))
            if mode in PARSER_TYPES:
                editor.setCurrentText(mode)
            editor.currentTextChanged.connect(on_mode)
            add("parser", "解析模式", editor)
        add("separator", "分隔符", line_edit("separator", ",", "如 , 或 ;"))
        terminator = EditableComboBox()
        terminator.addItems(list(TERMINATOR_CHOICES))
        terminator.setText(terminator_text(config.get("terminator", "\n")))
        # An emptied box is a terminator still being typed, not one to store.
        terminator.currentTextChanged.connect(
            lambda text: text and write("terminator", terminator_from_text(text)))
        add("terminator", "行结束符", terminator, "一条记录的结尾；\\n 换行，\\r 回车，\\t 制表符，\\\\ 反斜杠")
        add("kvSeparator", "键值分隔符", combo("kvSeparator", list(LINE_KV_SEPARATORS), "="))
        add("encoding", "编码", combo("encoding", list(LINE_ENCODINGS), LINE_ENCODINGS[0],
                                      normal=lambda value: str(value).lower()))
        add("header", "帧头(HEX)", line_edit("header", "AA55", "如 AA 55，留空表示没有帧头", True))
        add("footer", "帧尾(HEX)", line_edit("footer", "55AA", "如 0D 0A，留空表示没有帧尾", True))
        add("lengthOffset", "长度字段偏移", spin("lengthOffset", -1, 65535, -1), "-1 = 没有长度字段")
        add("lengthSize", "长度字节数", combo("lengthSize", ["1", "2"], 1, int))
        add("lengthEndian", "长度字节序", combo("lengthEndian", list(HEX_ENDIANS), HEX_ENDIANS[0]))
        add("lengthCovers", "长度含义", combo("lengthCovers", list(HEX_LENGTH_COVERS), HEX_LENGTH_COVERS[0]))
        add("fixedLength", "固定帧长", spin("fixedLength", 0, 65536, 0), "0 = 不固定")
        add("checksum", "校验", combo("checksum", list(HEX_CHECKSUMS), "无"))
        add("checksumStart", "校验起点", spin("checksumStart", 0, 65535, 0))
        add("checksumEndian", "校验字节序", combo("checksumEndian", list(HEX_ENDIANS), HEX_ENDIANS[0]))
        add("idleTimeout", "空闲超时(ms)", spin("idleTimeout", 0, 60000, 0))
        add("fields", "字段表", self._fields_editor(config.get("fields", []), write))
        self._show_frame_rows(rows, mode)
        return card, rows

    def _fields_editor(self, fields, write):
        """The 字段表 row: the table as text, and under it the first line that does not parse."""
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        box.text_edit = TextEdit()
        box.text_edit.setPlainText(hex_fields_text(fields))
        box.text_edit.setPlaceholderText("一行一个：名字,偏移,长度,类型[,字节序]")
        box.text_edit.setMaximumHeight(110)
        box.hint = CaptionLabel()
        box.hint.setTextColor(QColor("#c62828"), QColor("#ff8a80"))
        box.hint.hide()
        column.addWidget(box.text_edit)
        column.addWidget(box.hint)
        stored = [fields]

        def changed():
            parsed, bad = hex_fields_from_text(box.text_edit.toPlainText())
            box.hint.setVisible(bad is not None)
            if bad is not None:
                box.hint.setText(f"第 {bad} 行格式错误")  # the stored table stays as it was
            elif parsed != stored[0]:
                stored[0] = parsed
                write("fields", parsed)

        box.text_edit.textChanged.connect(changed)
        return box

    def _show_frame_rows(self, rows, mode):
        shown = _FRAME_KEYS.get(mode, ())
        for key, (_label, editor) in rows.items():
            self._show_row(editor, key == "parser" or key in shown)

    def _write_project_frame(self, key, value):
        project = self._project()
        if project is None:
            return
        serial = project.serial
        if key == "parser":
            serial["parser"] = value
        else:
            config = serial.get("parserConfig")
            serial["parserConfig"] = {**(config if isinstance(config, dict) else {}), key: value}
        signalBus.canvasChanged.emit()

    def _card_effective_frame(self):
        """The mode a link card parses with and the frame format it gets, by the links' rule: its own
        parserConfig, else the project's when the modes match, else the defaults."""
        props = self._current_item.properties
        mode = props.get("defaultParser", "项目设置")
        own = props.get("parserConfig")
        own = own if isinstance(own, dict) else {}
        project = self._project()
        if own or project is None or mode != project.serial.get("parser", "line"):
            return mode, own
        shared = project.serial.get("parserConfig")
        return mode, dict(shared) if isinstance(shared, dict) else {}

    def _card_frame_format(self):
        """The 帧格式 card of the selected link card; hidden while it uses the project's settings.
        A Modbus mode has nothing to set, and shows the title alone."""
        mode, config = self._card_effective_frame()
        section, self._card_frame_rows = self._frame_format_section(
            "帧格式", mode, config, self._write_card_frame)
        section.setVisible(mode != "项目设置")
        return section

    def _write_card_frame(self, key, value):
        if self._updating or not self._current_item:
            return
        # The first edit copies what the card showed, so its other rows keep their values.
        _mode, config = self._card_effective_frame()
        self._on_prop_changed("parserConfig", {**config, key: value})

    def _create_file_picker(self, prop_def: PropDef, current_value) -> QWidget:
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        edit = LineEdit()
        edit.setText(str(current_value))
        edit.setPlaceholderText("选择图片...")
        edit.textChanged.connect(
            lambda v, n=prop_def.name: self._on_prop_changed(n, v))
        h.addWidget(edit, 1)
        btn = ToolButton(FIF.FOLDER)
        btn.setFixedSize(30, 30)

        def browse():
            path, _ = QFileDialog.getOpenFileName(
                self, "选择图片", "",
                "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.svg);;所有文件 (*)")
            if path:
                edit.setText(path)

        btn.clicked.connect(browse)
        h.addWidget(btn)
        return container

    def _create_editor(self, prop_def: PropDef, current_value) -> Optional[QWidget]:
        if prop_def.name == "imagePath":
            return self._create_file_picker(prop_def, current_value)

        if prop_def.prop_type == PropType.STRING or prop_def.prop_type == PropType.COMMAND:
            editor = LineEdit()
            editor.setText(str(current_value))
            editor.textChanged.connect(lambda v, n=prop_def.name: self._on_prop_changed(n, v))
            return editor

        if prop_def.prop_type == PropType.INT:
            editor = SpinBox()
            editor.setRange(
                int(prop_def.min_val) if prop_def.min_val is not None else -99999,
                int(prop_def.max_val) if prop_def.max_val is not None else 99999,
            )
            editor.setValue(int(current_value))
            editor.valueChanged.connect(lambda v, n=prop_def.name: self._on_prop_changed(n, v))
            return editor

        if prop_def.prop_type == PropType.FLOAT:
            editor = DoubleSpinBox()
            editor.setRange(
                prop_def.min_val if prop_def.min_val is not None else -99999.0,
                prop_def.max_val if prop_def.max_val is not None else 99999.0,
            )
            editor.setValue(float(current_value))
            editor.valueChanged.connect(lambda v, n=prop_def.name: self._on_prop_changed(n, v))
            return editor

        if prop_def.prop_type == PropType.BOOL:
            editor = SwitchButton()
            editor.setChecked(bool(current_value))
            editor.checkedChanged.connect(lambda v, n=prop_def.name: self._on_prop_changed(n, v))
            return editor

        if prop_def.prop_type == PropType.ENUM:
            editor = ComboBox()
            editor.addItems(prop_def.options or [])
            if current_value in (prop_def.options or []):
                editor.setCurrentIndex(prop_def.options.index(current_value))
            editor.currentTextChanged.connect(lambda v, n=prop_def.name: self._on_prop_changed(n, v))
            return editor

        if prop_def.prop_type == PropType.TEXT:
            editor = _TabNamesEdit() if prop_def.name == "tabNames" else TextEdit()
            editor.setPlainText(str(current_value))
            editor.setMaximumHeight(80)
            if prop_def.name == "tabNames":
                editor.textChanged.connect(self._on_pending_tab_names_changed)
                editor.editingFinished.connect(
                    lambda: self.commit_pending_edits(editor))
            else:
                editor.textChanged.connect(
                    lambda n=prop_def.name: self._on_text_prop_changed(n, editor))
            return editor

        return None

    def _apply_mode_visibility(self, mode: str):
        """Show/hide command-related property rows based on commandMode."""
        visible = _MODE_VISIBILITY.get(mode, set())
        for name in _MODE_FIELDS:
            if name in self._prop_rows:
                self._show_row(self._prop_rows[name][1], name in visible)

    def _apply_link_parser_visibility(self, parser: str):
        """A link card's 默认轮询 / 响应超时 / 默认从站 rows show while it parses Modbus itself."""
        for name in _MODBUS_LINK_FIELDS:
            if name in self._prop_rows:
                self._show_row(self._prop_rows[name][1], parser in MODBUS_PARSERS)

    def _apply_send_toggle_visibility(self, enabled: bool):
        """Show/hide send-related fields when sendOnEnter/sendOnSelect/sendOnChange toggles.
        A Modbus-mode control sends whether or not the toggle is on, so its fields stay visible."""
        all_fields = _SEND_TOGGLE_FIELDS | _MODE_FIELDS
        mode = self._current_item.properties.get("commandMode", "文本") if self._current_item else "文本"
        if not enabled and mode != "Modbus":
            for name in all_fields:
                if name in self._prop_rows:
                    self._show_row(self._prop_rows[name][1], False)
        else:
            for name in _SEND_TOGGLE_FIELDS:
                if name in self._prop_rows:
                    self._show_row(self._prop_rows[name][1], True)
            self._apply_mode_visibility(mode)

    def _apply_chart_parse_visibility(self, mode: str):
        """Show/hide chart per-curve property rows based on curveParseMode."""
        visible = _CHART_PARSE_VIS.get(mode, set())
        for name in _CHART_PARSE_ALL:
            if name in self._prop_rows:
                self._show_row(self._prop_rows[name][1], name in visible)

    def _load_curve_editors(self, item: CanvasItem):
        """Fill per-curve editors from ``_curve_{ci}_{field}`` stored properties."""
        from app.widgets.chart import _CURVE_FIELD_MAP, _DEFAULT_CURVE_CFG
        ci = int(item.properties.get("currentCurve", 0))
        self._updating = True
        for virt, suffix in _CURVE_FIELD_MAP.items():
            if virt not in self._editors:
                continue
            stored = item.properties.get(f"_curve_{ci}_{suffix}")
            default = _DEFAULT_CURVE_CFG.get(suffix, "")
            if stored is None:
                if suffix == "name":
                    default = f"曲线{ci + 1}"
                stored = default
            editor = self._editors[virt]
            if hasattr(editor, "setValue"):
                try:
                    editor.setValue(int(stored))
                except (ValueError, TypeError):
                    editor.setValue(0)
            elif hasattr(editor, "setCurrentText"):
                editor.setCurrentText(str(stored))
            elif hasattr(editor, "setText"):
                editor.setText(str(stored))
        self._updating = False

    def _on_pending_tab_names_changed(self):
        if not self._updating:
            signalBus.canvasChanged.emit()

    def commit_pending_edits(self, editor=None):
        current = self._editors.get("tabNames")
        if (self._updating or current is None or not self._current_item
                or sip.isdeleted(self._current_item)
                or (editor is not None and editor is not current)):
            return
        if (hasattr(self, "_scene")
                and self._current_item.scene() is not self._scene):
            return
        text = current.toPlainText()
        if text != self._current_item.properties.get("tabNames", ""):
            self._on_prop_changed("tabNames", text)

    def _sync_tab_editors(self):
        item = self._current_item
        if item is None or item.type_name != "TabWidget":
            return
        updating = self._updating
        self._updating = True
        current = int(item.properties.get("currentTab", 0))
        if "currentTab" in self._editors:
            editor = self._editors["currentTab"]
            editor.setRange(0, item._inner_widget.count() - 1)
            editor.setValue(current)
        if "tabLayout" in self._editors:
            self._editors["tabLayout"].setCurrentText(
                item.properties.get(f"_tabLayout_{current}", "自由"))
        self._updating = updating

    def _on_prop_changed(self, prop_name: str, value):
        if self._updating or not self._current_item:
            return
        self._updating = True
        self._current_item.set_property(prop_name, value)
        signalBus.widgetPropertyChanged.emit(
            self._current_item.widget_id, prop_name, value
        )
        signalBus.canvasChanged.emit()
        self._updating = False

        if (self._current_item.type_name in ("Slider", "SpinBox", "GaugeMeter")
                and prop_name in ("minimum", "maximum", "value")):
            self._updating = True
            for name in ("minimum", "maximum", "value"):
                if name in self._editors:
                    self._editors[name].setValue(self._current_item.properties[name])
            self._updating = False
        elif prop_name == "commandMode":
            self._apply_mode_visibility(value)
            toggles = [name for name in ("sendOnEnter", "sendOnSelect", "sendOnChange") if name in self._prop_rows]
            if toggles:
                self._apply_send_toggle_visibility(any(self._current_item.properties.get(n, False) for n in toggles))
        elif prop_name in ("sendOnEnter", "sendOnSelect", "sendOnChange"):
            self._apply_send_toggle_visibility(bool(value))
        elif prop_name == "displayMode" and self._current_item.type_name in LINK_CARD_TYPES:
            self._sync_height_editor()  # another display mode needs another least height
        elif (prop_name == "defaultParser" and self._card_frame_section is not None
              and self._current_item.type_name in LINK_CARD_TYPES):
            self._apply_link_parser_visibility(value)
            # Another mode shows other rows, and possibly the project's values.
            section = self._card_frame_format()
            self._layout.replaceWidget(self._card_frame_section, section)
            self._card_frame_section.deleteLater()
            self._card_frame_section = section
        elif (prop_name in ("currentTab", "tabNames")
              and self._current_item
              and self._current_item.type_name == "TabWidget"):
            self._sync_tab_editors()
        elif (self._current_item
              and self._current_item.type_name == "RealtimeChart"):
            if prop_name == "currentCurve":
                self._load_curve_editors(self._current_item)
                ci = int(value)
                pm = self._current_item.properties.get(
                    f"_curve_{ci}_parseMode", "键值匹配")
                self._apply_chart_parse_visibility(pm)
            elif prop_name == "curveCount":
                ci = int(self._current_item.properties.get("currentCurve", 0))
                if ci >= int(value):
                    self._current_item.properties["currentCurve"] = 0
                    if "currentCurve" in self._editors:
                        self._updating = True
                        self._editors["currentCurve"].setValue(0)
                        self._updating = False
                    self._load_curve_editors(self._current_item)
                    pm = self._current_item.properties.get(
                        "_curve_0_parseMode", "键值匹配")
                    self._apply_chart_parse_visibility(pm)
            elif prop_name == "curveParseMode":
                self._apply_chart_parse_visibility(value)

    def _sync_height_editor(self):
        editor = self._editors.get("geo_h")
        if editor is None or not self._current_item:
            return
        updating, self._updating = self._updating, True
        editor.setMinimum(self._current_item.min_height())
        editor.setValue(int(self._current_item.rect().height()))
        self._updating = updating

    def _on_text_prop_changed(self, prop_name: str, editor):
        if self._updating or not self._current_item:
            return
        self._on_prop_changed(prop_name, editor.toPlainText())

    def _on_geo_changed(self, attr: str, value: int):
        if self._updating or not self._current_item:
            return
        self._updating = True
        item = self._current_item
        pos = item.pos()
        rect = item.rect()
        meta = registry.get(item.type_name)

        if attr == "geo_x":
            item.setPos(value, pos.y())
        elif attr == "geo_y":
            item.setPos(pos.x(), value)
        elif attr == "geo_w":
            from PyQt5.QtCore import QRectF
            value = max(meta.min_width if meta else 1, value)
            item.set_rect(QRectF(0, 0, value, rect.height()))
        elif attr == "geo_h":
            from PyQt5.QtCore import QRectF
            value = max(item.min_height(), value)
            item.set_rect(QRectF(0, 0, rect.width(), value))

        signalBus.canvasChanged.emit()
        self._updating = False

    def _apply_bind_mode_visibility(self, mode: str):
        """Show/hide binding fields based on parseMode."""
        is_kv = mode == "键值匹配"
        is_json = mode == "JSON路径"
        is_hex = mode == "HEX字节提取"
        is_mb = mode == "Modbus"
        for field, shown in ((self._bind_key_edit, is_kv), (self._bind_json_edit, is_json),
                             *((field, is_hex) for field in (
                                 self._bind_offset_spin, self._bind_dtype_combo, self._bind_order_combo,
                                 self._bind_header_edit, self._bind_tail_edit)),
                             *((field, is_mb) for field in (
                                 self._bind_mb_area_combo, self._bind_mb_reg_spin, self._bind_mb_dtype_combo,
                                 self._bind_mb_regorder_combo, self._bind_mb_fc_spin,
                                 self._bind_mb_slave_spin, self._bind_mb_period_spin))):
            self._show_row(field, shown)

    def _on_bind_mode_changed(self, mode: str):
        self._apply_bind_mode_visibility(mode)
        self._on_binding_changed()

    def _on_binding_changed(self, _=None):
        if self._updating or not self._current_item:
            return
        if not hasattr(self, "_bind_mode_combo"):
            return
        pm = self._bind_mode_combo.currentText()
        key = self._bind_key_edit.text().strip()
        json_path = self._bind_json_edit.text().strip()
        expr = self._bind_expr_edit.text().strip()

        has_config = (
            (pm == "键值匹配" and key)
            or (pm == "JSON路径" and json_path)
            or (pm == "HEX字节提取")
            or (pm == "Modbus")
        )
        if has_config:
            self._current_item.binding = {
                "parseMode": pm,
                "key": key,
                "jsonPath": json_path,
                "byteOffset": self._bind_offset_spin.value(),
                "dataType": self._bind_dtype_combo.currentText(),
                "byteOrder": self._bind_order_combo.currentText(),
                "expression": expr or None,
                "frameHeader": self._bind_header_edit.text().strip(),
                "frameTail": self._bind_tail_edit.text().strip(),
                "mbRegIndex": self._bind_mb_reg_spin.value(),
                "mbDataType": self._bind_mb_dtype_combo.currentText(),
                "mbRegOrder": self._bind_mb_regorder_combo.currentText(),
                "mbFcFilter": self._bind_mb_fc_spin.value(),
                "mbSlaveFilter": self._bind_mb_slave_spin.value(),
                "mbArea": self._bind_mb_area_combo.currentText(),
                "mbPeriod": self._bind_mb_period_spin.value(),
            }
        else:
            self._current_item.binding = None
        signalBus.canvasChanged.emit()
