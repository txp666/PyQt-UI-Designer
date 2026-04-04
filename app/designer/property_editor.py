# coding: utf-8
"""Property editor panel — dynamic form driven by widget metadata."""
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFormLayout,
    QSizePolicy, QFrame, QFileDialog,
)
from qfluentwidgets import (
    ScrollArea, StrongBodyLabel, BodyLabel, CardWidget,
    LineEdit, SpinBox, DoubleSpinBox, SwitchButton,
    ComboBox, TextEdit, CaptionLabel, ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.signal_bus import signalBus
from app.core.widget_registry import registry
from app.widgets.base import PropType, PropDef, WidgetMeta
from app.designer.canvas_item import CanvasItem


_MODE_VISIBILITY = {
    "文本":   {"command", "onCommand", "offCommand", "commandNewline", "commandTemplate"},
    "HEX":    {"command", "onCommand", "offCommand", "commandTemplate",
               "frameHeader", "frameTail", "dataType", "byteOrder"},
    "Modbus": {"mbSlave", "mbFunc", "mbAddress", "mbValue"},
}
_MODE_FIELDS = {
    "command", "onCommand", "offCommand", "commandNewline", "commandTemplate",
    "frameHeader", "frameTail", "dataType", "byteOrder",
    "mbSlave", "mbFunc", "mbAddress", "mbValue",
}

_SEND_TOGGLE_FIELDS = {"commandMode", "commands"}

# Chart per-curve fields visibility based on curveParseMode
_CHART_PARSE_VIS = {
    "键值匹配":  {"curveKey"},
    "JSON路径":   {"curveJsonPath"},
    "HEX字节提取": {"curveByteOffset", "curveDataType", "curveByteOrder",
                      "curveFrameHeader", "curveFrameTail"},
    "Modbus":     {"curveRegIndex", "curveMbDataType", "curveMbRegOrder",
                   "curveMbFcFilter", "curveMbSlaveFilter"},
}
_CHART_PARSE_ALL = set()
for _v in _CHART_PARSE_VIS.values():
    _CHART_PARSE_ALL |= _v


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

        self._empty_label = BodyLabel("选择一个控件以编辑属性")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._empty_label)

        signalBus.widgetSelected.connect(self._on_widget_selected)
        signalBus.widgetDeselected.connect(self._on_deselected)

        self.setStyleSheet(
            "QScrollArea, #propEditorContainer { background: transparent; border: none; }"
        )

    def set_scene(self, scene):
        self._scene = scene

    def _on_widget_selected(self, widget_id: str):
        if not hasattr(self, "_scene"):
            return
        item = self._scene.get_item_by_id(widget_id)
        if item:
            self._load_item(item)

    def _on_deselected(self):
        self._clear()

    def _clear(self):
        self._current_item = None
        self._editors.clear()
        while self._layout.count():
            child = self._layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._empty_label = BodyLabel("选择一个控件以编辑属性")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._empty_label)

    def _load_item(self, item: CanvasItem):
        self._current_item = item
        self._editors.clear()
        self._prop_rows.clear()

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
            spin.setRange(0, 9999)
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
            props_layout.addRow(StrongBodyLabel("属性"))

            for prop_def in meta.properties:
                editor = self._create_editor(prop_def, item.properties.get(prop_def.name, prop_def.default))
                if editor:
                    label = BodyLabel(prop_def.label)
                    if prop_def.bindable:
                        label.setText(f"{prop_def.label} ⚡")
                        label.setToolTip("可绑定到串口数据")
                    props_layout.addRow(label, editor)
                    self._editors[prop_def.name] = editor
                    self._prop_rows[prop_def.name] = (label, editor)

            self._layout.addWidget(props_card)

            cur_mode = item.properties.get("commandMode", "文本")
            self._apply_mode_visibility(cur_mode)

            if ("sendOnEnter" in self._prop_rows
                    or "sendOnSelect" in self._prop_rows
                    or "sendOnChange" in self._prop_rows):
                send_on = (item.properties.get("sendOnEnter", False)
                           or item.properties.get("sendOnSelect", False)
                           or item.properties.get("sendOnChange", False))
                self._apply_send_toggle_visibility(send_on)

            if item.type_name == "TabWidget" and "tabLayout" in self._editors:
                ct = int(item.properties.get("currentTab", 0))
                real_val = item.properties.get(f"_tabLayout_{ct}", "垂直")
                self._updating = True
                self._editors["tabLayout"].setCurrentText(real_val)
                self._updating = False

            if item.type_name == "RealtimeChart":
                self._load_curve_editors(item)
                pm = item.properties.get(
                    f"_curve_{int(item.properties.get('currentCurve', 0))}_parseMode",
                    "键值匹配")
                self._apply_chart_parse_visibility(pm)

        # binding card — only for widgets that have bindable properties
        has_bindable = any(p.bindable for p in meta.properties)
        if has_bindable:
            binding_card = CardWidget()
            binding_layout = QFormLayout(binding_card)
            binding_layout.setContentsMargins(12, 8, 12, 8)
            binding_layout.setSpacing(6)
            binding_layout.addRow(StrongBodyLabel("数据绑定"))

            bd = item.binding or {}

            self._bind_mode_combo = ComboBox()
            self._bind_mode_combo.addItems(["键值匹配", "JSON路径", "HEX字节提取", "Modbus"])
            cur_pm = bd.get("parseMode", "键值匹配")
            if cur_pm in ["键值匹配", "JSON路径", "HEX字节提取", "Modbus"]:
                self._bind_mode_combo.setCurrentText(cur_pm)
            self._bind_mode_combo.currentTextChanged.connect(self._on_bind_mode_changed)
            binding_layout.addRow(BodyLabel("解析模式"), self._bind_mode_combo)

            self._bind_key_edit = LineEdit()
            self._bind_key_edit.setPlaceholderText("字段名 (如 temperature)")
            self._bind_key_edit.setText(bd.get("key", ""))
            self._bind_key_edit.textChanged.connect(self._on_binding_changed)
            self._bind_key_label = BodyLabel("绑定字段")
            binding_layout.addRow(self._bind_key_label, self._bind_key_edit)

            self._bind_json_edit = LineEdit()
            self._bind_json_edit.setPlaceholderText("路径 (如 data.sensors.0.temp)")
            self._bind_json_edit.setText(bd.get("jsonPath", ""))
            self._bind_json_edit.textChanged.connect(self._on_binding_changed)
            self._bind_json_label = BodyLabel("JSON路径")
            binding_layout.addRow(self._bind_json_label, self._bind_json_edit)

            self._bind_offset_spin = SpinBox()
            self._bind_offset_spin.setRange(0, 9999)
            self._bind_offset_spin.setValue(int(bd.get("byteOffset", 0)))
            self._bind_offset_spin.valueChanged.connect(self._on_binding_changed)
            self._bind_offset_label = BodyLabel("字节偏移")
            binding_layout.addRow(self._bind_offset_label, self._bind_offset_spin)

            self._bind_dtype_combo = ComboBox()
            self._bind_dtype_combo.addItems([
                "uint8", "int8", "uint16", "int16",
                "uint32", "int32", "float32", "ASCII"])
            dt = bd.get("dataType", "uint16")
            self._bind_dtype_combo.setCurrentText(dt)
            self._bind_dtype_combo.currentTextChanged.connect(self._on_binding_changed)
            self._bind_dtype_label = BodyLabel("数据类型")
            binding_layout.addRow(self._bind_dtype_label, self._bind_dtype_combo)

            self._bind_order_combo = ComboBox()
            self._bind_order_combo.addItems(["大端(BE)", "小端(LE)"])
            bo = bd.get("byteOrder", "大端(BE)")
            self._bind_order_combo.setCurrentText(bo)
            self._bind_order_combo.currentTextChanged.connect(self._on_binding_changed)
            self._bind_order_label = BodyLabel("字节序")
            binding_layout.addRow(self._bind_order_label, self._bind_order_combo)

            self._bind_header_edit = LineEdit()
            self._bind_header_edit.setPlaceholderText("如 AA 55")
            self._bind_header_edit.setText(bd.get("frameHeader", ""))
            self._bind_header_edit.textChanged.connect(self._on_binding_changed)
            self._bind_header_label = BodyLabel("帧头(HEX)")
            binding_layout.addRow(self._bind_header_label, self._bind_header_edit)

            self._bind_tail_edit = LineEdit()
            self._bind_tail_edit.setPlaceholderText("如 0D 0A")
            self._bind_tail_edit.setText(bd.get("frameTail", ""))
            self._bind_tail_edit.textChanged.connect(self._on_binding_changed)
            self._bind_tail_label = BodyLabel("帧尾(HEX)")
            binding_layout.addRow(self._bind_tail_label, self._bind_tail_edit)

            self._bind_mb_reg_spin = SpinBox()
            self._bind_mb_reg_spin.setRange(0, 255)
            self._bind_mb_reg_spin.setValue(int(bd.get("mbRegIndex", 0)))
            self._bind_mb_reg_spin.valueChanged.connect(self._on_binding_changed)
            self._bind_mb_reg_label = BodyLabel("寄存器索引")
            binding_layout.addRow(self._bind_mb_reg_label, self._bind_mb_reg_spin)

            self._bind_mb_dtype_combo = ComboBox()
            self._bind_mb_dtype_combo.addItems([
                "uint16", "int16", "uint32", "int32", "float32"])
            self._bind_mb_dtype_combo.setCurrentText(bd.get("mbDataType", "uint16"))
            self._bind_mb_dtype_combo.currentTextChanged.connect(self._on_binding_changed)
            self._bind_mb_dtype_label = BodyLabel("数据类型")
            binding_layout.addRow(self._bind_mb_dtype_label, self._bind_mb_dtype_combo)

            self._bind_mb_regorder_combo = ComboBox()
            self._bind_mb_regorder_combo.addItems(["大端(AB CD)", "小端(CD AB)"])
            self._bind_mb_regorder_combo.setCurrentText(bd.get("mbRegOrder", "大端(AB CD)"))
            self._bind_mb_regorder_combo.currentTextChanged.connect(self._on_binding_changed)
            self._bind_mb_regorder_label = BodyLabel("寄存器序")
            binding_layout.addRow(self._bind_mb_regorder_label, self._bind_mb_regorder_combo)

            self._bind_mb_fc_spin = SpinBox()
            self._bind_mb_fc_spin.setRange(-1, 255)
            self._bind_mb_fc_spin.setValue(int(bd.get("mbFcFilter", -1)))
            self._bind_mb_fc_spin.valueChanged.connect(self._on_binding_changed)
            self._bind_mb_fc_label = BodyLabel("功能码过滤(-1=全部)")
            binding_layout.addRow(self._bind_mb_fc_label, self._bind_mb_fc_spin)

            self._bind_mb_slave_spin = SpinBox()
            self._bind_mb_slave_spin.setRange(-1, 247)
            self._bind_mb_slave_spin.setValue(int(bd.get("mbSlaveFilter", -1)))
            self._bind_mb_slave_spin.valueChanged.connect(self._on_binding_changed)
            self._bind_mb_slave_label = BodyLabel("从站过滤(-1=全部)")
            binding_layout.addRow(self._bind_mb_slave_label, self._bind_mb_slave_spin)

            self._bind_expr_edit = LineEdit()
            self._bind_expr_edit.setPlaceholderText("表达式 (如 value * 0.1)")
            self._bind_expr_edit.setText(bd.get("expression", ""))
            self._bind_expr_edit.textChanged.connect(self._on_binding_changed)
            binding_layout.addRow(BodyLabel("转换表达式"), self._bind_expr_edit)

            self._layout.addWidget(binding_card)
            self._apply_bind_mode_visibility(cur_pm)

        self._layout.addStretch()

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
            editor = TextEdit()
            editor.setPlainText(str(current_value))
            editor.setMaximumHeight(80)
            editor.textChanged.connect(lambda n=prop_def.name: self._on_text_prop_changed(n, editor))
            return editor

        return None

    def _apply_mode_visibility(self, mode: str):
        """Show/hide command-related property rows based on commandMode."""
        visible = _MODE_VISIBILITY.get(mode, set())
        for name in _MODE_FIELDS:
            if name in self._prop_rows:
                label, editor = self._prop_rows[name]
                show = name in visible
                label.setVisible(show)
                editor.setVisible(show)

    def _apply_send_toggle_visibility(self, enabled: bool):
        """Show/hide send-related fields when sendOnEnter/sendOnSelect/sendOnChange toggles."""
        all_fields = _SEND_TOGGLE_FIELDS | _MODE_FIELDS
        if not enabled:
            for name in all_fields:
                if name in self._prop_rows:
                    label, editor = self._prop_rows[name]
                    label.setVisible(False)
                    editor.setVisible(False)
        else:
            for name in _SEND_TOGGLE_FIELDS:
                if name in self._prop_rows:
                    label, editor = self._prop_rows[name]
                    label.setVisible(True)
                    editor.setVisible(True)
            mode = self._current_item.properties.get("commandMode", "文本") if self._current_item else "文本"
            self._apply_mode_visibility(mode)

    def _apply_chart_parse_visibility(self, mode: str):
        """Show/hide chart per-curve property rows based on curveParseMode."""
        visible = _CHART_PARSE_VIS.get(mode, set())
        for name in _CHART_PARSE_ALL:
            if name in self._prop_rows:
                label, editor = self._prop_rows[name]
                show = name in visible
                label.setVisible(show)
                editor.setVisible(show)

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

        if prop_name == "commandMode":
            self._apply_mode_visibility(value)
        elif prop_name in ("sendOnEnter", "sendOnSelect", "sendOnChange"):
            self._apply_send_toggle_visibility(bool(value))
        elif (prop_name == "currentTab"
              and self._current_item
              and self._current_item.type_name == "TabWidget"):
            ct = int(value)
            layout_val = self._current_item.properties.get(
                f"_tabLayout_{ct}", "垂直")
            if "tabLayout" in self._editors:
                self._updating = True
                self._editors["tabLayout"].setCurrentText(layout_val)
                self._updating = False
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

        if attr == "geo_x":
            item.setPos(value, pos.y())
        elif attr == "geo_y":
            item.setPos(pos.x(), value)
        elif attr == "geo_w":
            from PyQt5.QtCore import QRectF
            item.set_rect(QRectF(0, 0, value, rect.height()))
        elif attr == "geo_h":
            from PyQt5.QtCore import QRectF
            item.set_rect(QRectF(0, 0, rect.width(), value))

        signalBus.canvasChanged.emit()
        self._updating = False

    def _apply_bind_mode_visibility(self, mode: str):
        """Show/hide binding fields based on parseMode."""
        is_kv = mode == "键值匹配"
        is_json = mode == "JSON路径"
        is_hex = mode == "HEX字节提取"
        is_mb = mode == "Modbus"
        for w in (self._bind_key_label, self._bind_key_edit):
            w.setVisible(is_kv)
        for w in (self._bind_json_label, self._bind_json_edit):
            w.setVisible(is_json)
        for w in (self._bind_offset_label, self._bind_offset_spin,
                  self._bind_dtype_label, self._bind_dtype_combo,
                  self._bind_order_label, self._bind_order_combo,
                  self._bind_header_label, self._bind_header_edit,
                  self._bind_tail_label, self._bind_tail_edit):
            w.setVisible(is_hex)
        for w in (self._bind_mb_reg_label, self._bind_mb_reg_spin,
                  self._bind_mb_dtype_label, self._bind_mb_dtype_combo,
                  self._bind_mb_regorder_label, self._bind_mb_regorder_combo,
                  self._bind_mb_fc_label, self._bind_mb_fc_spin,
                  self._bind_mb_slave_label, self._bind_mb_slave_spin):
            w.setVisible(is_mb)

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
            }
        else:
            self._current_item.binding = None
        signalBus.canvasChanged.emit()
