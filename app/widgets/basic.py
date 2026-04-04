# coding: utf-8
"""Basic widget definitions: Button, Label, LineEdit, ComboBox, Switch, Slider, SpinBox."""
from PyQt5.QtWidgets import QWidget, QLabel, QHBoxLayout
from PyQt5.QtCore import Qt
from qfluentwidgets import (
    PushButton, BodyLabel, LineEdit, ComboBox,
    SwitchButton, Slider, SpinBox,
)

from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.widget_registry import registry


# ---------------------------------------------------------------------------
# Widget metadata definitions
# ---------------------------------------------------------------------------

PUSH_BUTTON_META = WidgetMeta(
    type_name="PushButton",
    display_name="按钮",
    category=WidgetCategory.BASIC,
    icon="SEND",
    default_width=120, default_height=36,
    properties=[
        PropDef("text", "文本", PropType.STRING, "按钮"),
        PropDef("enabled", "启用", PropType.BOOL, True),
        PropDef("commandMode", "发送模式", PropType.ENUM, "文本",
                options=["文本", "HEX", "Modbus"]),
        PropDef("command", "发送内容", PropType.COMMAND, ""),
        PropDef("commandTemplate", "发送模板", PropType.STRING, "{value}"),
        PropDef("frameHeader", "帧头(HEX)", PropType.STRING, ""),
        PropDef("frameTail", "帧尾(HEX)", PropType.STRING, ""),
        PropDef("dataType", "数据类型", PropType.ENUM, "HEX字符串",
                options=["HEX字符串", "uint8", "int8", "uint16", "int16",
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", "字节序", PropType.ENUM, "大端(BE)",
                options=["大端(BE)", "小端(LE)"]),
        PropDef("commandNewline", "换行符", PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),
        PropDef("mbSlave", "从站地址", PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbFunc", "功能码", PropType.ENUM, "03 读保持寄存器",
                options=["01 读线圈", "02 读离散输入", "03 读保持寄存器",
                         "04 读输入寄存器", "05 写单线圈", "06 写单寄存器"]),
        PropDef("mbAddress", "寄存器地址", PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("mbValue", "值/数量", PropType.INT, 1, min_val=0, max_val=65535),
        PropDef("notify", "按下通知", PropType.BOOL, False),
        PropDef("notifyTitle", "通知标题", PropType.STRING, "提示"),
        PropDef("notifyContent", "通知内容", PropType.STRING, "按钮已按下"),
        PropDef("notifyType", "通知类型", PropType.ENUM, "成功",
                options=["成功", "信息", "警告", "错误"]),
        PropDef("notifyDuration", "通知时长(ms)", PropType.INT, 3000,
                min_val=500, max_val=30000),
    ],
)

LABEL_META = WidgetMeta(
    type_name="Label",
    display_name="标签",
    category=WidgetCategory.BASIC,
    icon="FONT",
    default_width=120, default_height=30,
    properties=[
        PropDef("text", "文本", PropType.STRING, "标签", bindable=True),
        PropDef("fontSize", "字号", PropType.INT, 14, min_val=8, max_val=72),
        PropDef("bold", "加粗", PropType.BOOL, False),
        PropDef("alignment", "对齐", PropType.ENUM, "Left",
                options=["Left", "Center", "Right"]),
        PropDef("displayFormat", "显示格式", PropType.ENUM, "自动",
                options=["自动", "十进制", "十六进制(HEX)", "二进制(BIN)"]),
    ],
)

LINE_EDIT_META = WidgetMeta(
    type_name="LineEdit",
    display_name="输入框",
    category=WidgetCategory.BASIC,
    icon="EDIT",
    default_width=200, default_height=36,
    properties=[
        PropDef("placeholderText", "占位文本", PropType.STRING, "请输入..."),
        PropDef("text", "默认值", PropType.STRING, ""),
        PropDef("readOnly", "只读", PropType.BOOL, False),
        PropDef("sendOnEnter", "回车发送", PropType.BOOL, False),
        PropDef("commandMode", "发送模式", PropType.ENUM, "文本",
                options=["文本", "HEX", "Modbus"]),
        PropDef("commandTemplate", "发送模板", PropType.STRING, "{value}"),
        PropDef("frameHeader", "帧头(HEX)", PropType.STRING, ""),
        PropDef("frameTail", "帧尾(HEX)", PropType.STRING, ""),
        PropDef("dataType", "数据类型", PropType.ENUM, "HEX字符串",
                options=["HEX字符串", "uint8", "int8", "uint16", "int16",
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", "字节序", PropType.ENUM, "大端(BE)",
                options=["大端(BE)", "小端(LE)"]),
        PropDef("commandNewline", "换行符", PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),
        PropDef("mbSlave", "从站地址", PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbFunc", "功能码", PropType.ENUM, "06 写单寄存器",
                options=["03 读保持寄存器", "04 读输入寄存器",
                         "05 写单线圈", "06 写单寄存器"]),
        PropDef("mbAddress", "寄存器地址", PropType.INT, 0, min_val=0, max_val=65535),
    ],
)

COMBO_BOX_META = WidgetMeta(
    type_name="ComboBox",
    display_name="下拉框",
    category=WidgetCategory.BASIC,
    icon="MENU",
    default_width=160, default_height=36,
    properties=[
        PropDef("items", "选项", PropType.TEXT, "选项1\n选项2\n选项3"),
        PropDef("currentIndex", "默认选项", PropType.INT, 0, min_val=0, max_val=99),
        PropDef("sendOnSelect", "选中发送", PropType.BOOL, False),
        PropDef("commands", "发送命令表", PropType.TEXT, "",),
        PropDef("commandMode", "发送模式", PropType.ENUM, "文本",
                options=["文本", "HEX", "Modbus"]),
        PropDef("commandTemplate", "发送模板", PropType.STRING, "{value}"),
        PropDef("frameHeader", "帧头(HEX)", PropType.STRING, ""),
        PropDef("frameTail", "帧尾(HEX)", PropType.STRING, ""),
        PropDef("dataType", "数据类型", PropType.ENUM, "HEX字符串",
                options=["HEX字符串", "uint8", "int8", "uint16", "int16",
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", "字节序", PropType.ENUM, "大端(BE)",
                options=["大端(BE)", "小端(LE)"]),
        PropDef("commandNewline", "换行符", PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),
        PropDef("mbSlave", "从站地址", PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbFunc", "功能码", PropType.ENUM, "06 写单寄存器",
                options=["03 读保持寄存器", "04 读输入寄存器",
                         "05 写单线圈", "06 写单寄存器"]),
        PropDef("mbAddress", "寄存器地址", PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("mbValue", "值/数量", PropType.INT, 1, min_val=0, max_val=65535),
    ],
)

SWITCH_META = WidgetMeta(
    type_name="ToggleSwitch",
    display_name="开关",
    category=WidgetCategory.BASIC,
    icon="POWER_BUTTON",
    default_width=140, default_height=30,
    properties=[
        PropDef("label", "标签", PropType.STRING, "开关"),
        PropDef("checked", "默认开启", PropType.BOOL, False),
        PropDef("commandMode", "发送模式", PropType.ENUM, "文本",
                options=["文本", "HEX", "Modbus"]),
        PropDef("onCommand", "开启命令", PropType.COMMAND, ""),
        PropDef("offCommand", "关闭命令", PropType.COMMAND, ""),
        PropDef("commandTemplate", "发送模板", PropType.STRING, "{value}"),
        PropDef("frameHeader", "帧头(HEX)", PropType.STRING, ""),
        PropDef("frameTail", "帧尾(HEX)", PropType.STRING, ""),
        PropDef("dataType", "数据类型", PropType.ENUM, "HEX字符串",
                options=["HEX字符串", "uint8", "int8", "uint16", "int16",
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", "字节序", PropType.ENUM, "大端(BE)",
                options=["大端(BE)", "小端(LE)"]),
        PropDef("commandNewline", "换行符", PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),
        PropDef("mbSlave", "从站地址", PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbAddress", "线圈地址", PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("notify", "切换通知", PropType.BOOL, False),
        PropDef("notifyTitle", "通知标题", PropType.STRING, "提示"),
        PropDef("notifyContent", "通知内容", PropType.STRING, "开关已切换"),
        PropDef("notifyType", "通知类型", PropType.ENUM, "信息",
                options=["成功", "信息", "警告", "错误"]),
        PropDef("notifyDuration", "通知时长(ms)", PropType.INT, 3000,
                min_val=500, max_val=30000),
    ],
)

SLIDER_META = WidgetMeta(
    type_name="Slider",
    display_name="滑块",
    category=WidgetCategory.BASIC,
    icon="SCROLL",
    default_width=200, default_height=30,
    properties=[
        PropDef("minimum", "最小值", PropType.INT, 0, min_val=-99999, max_val=99999),
        PropDef("maximum", "最大值", PropType.INT, 100, min_val=-99999, max_val=99999),
        PropDef("value", "默认值", PropType.INT, 50, min_val=-99999, max_val=99999),
        PropDef("sendOnChange", "变化发送", PropType.BOOL, False),
        PropDef("commandMode", "发送模式", PropType.ENUM, "文本",
                options=["文本", "HEX", "Modbus"]),
        PropDef("commandTemplate", "发送模板", PropType.STRING, "{value}"),
        PropDef("frameHeader", "帧头(HEX)", PropType.STRING, ""),
        PropDef("frameTail", "帧尾(HEX)", PropType.STRING, ""),
        PropDef("commandNewline", "换行符", PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),
        PropDef("dataType", "数据类型", PropType.ENUM, "uint16",
                options=["uint8", "int8", "uint16", "int16",
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", "字节序", PropType.ENUM, "大端(BE)",
                options=["大端(BE)", "小端(LE)"]),
        PropDef("mbSlave", "从站地址", PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbFunc", "功能码", PropType.ENUM, "06 写单寄存器",
                options=["05 写单线圈", "06 写单寄存器"]),
        PropDef("mbAddress", "寄存器地址", PropType.INT, 0, min_val=0, max_val=65535),
    ],
)

SPIN_BOX_META = WidgetMeta(
    type_name="SpinBox",
    display_name="数值框",
    category=WidgetCategory.BASIC,
    icon="SETTING",
    default_width=140, default_height=36,
    properties=[
        PropDef("minimum", "最小值", PropType.INT, 0, min_val=-99999, max_val=99999),
        PropDef("maximum", "最大值", PropType.INT, 100, min_val=-99999, max_val=99999),
        PropDef("value", "默认值", PropType.INT, 0, min_val=-99999, max_val=99999),
        PropDef("suffix", "后缀", PropType.STRING, ""),
        PropDef("sendOnChange", "变化发送", PropType.BOOL, False),
        PropDef("commandMode", "发送模式", PropType.ENUM, "文本",
                options=["文本", "HEX", "Modbus"]),
        PropDef("commandTemplate", "发送模板", PropType.STRING, "{value}"),
        PropDef("frameHeader", "帧头(HEX)", PropType.STRING, ""),
        PropDef("frameTail", "帧尾(HEX)", PropType.STRING, ""),
        PropDef("commandNewline", "换行符", PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),
        PropDef("dataType", "数据类型", PropType.ENUM, "uint16",
                options=["uint8", "int8", "uint16", "int16",
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", "字节序", PropType.ENUM, "大端(BE)",
                options=["大端(BE)", "小端(LE)"]),
        PropDef("mbSlave", "从站地址", PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbFunc", "功能码", PropType.ENUM, "06 写单寄存器",
                options=["05 写单线圈", "06 写单寄存器"]),
        PropDef("mbAddress", "寄存器地址", PropType.INT, 0, min_val=0, max_val=65535),
    ],
)

ALL_BASIC = [
    PUSH_BUTTON_META, LABEL_META, LINE_EDIT_META,
    COMBO_BOX_META, SWITCH_META, SLIDER_META, SPIN_BOX_META,
]


def register_basic_widgets():
    for meta in ALL_BASIC:
        registry.register(meta)


# ---------------------------------------------------------------------------
# Factory: create real Qt widgets from metadata + properties
# ---------------------------------------------------------------------------

_ALIGNMENT_MAP = {
    "Left": Qt.AlignLeft | Qt.AlignVCenter,
    "Center": Qt.AlignCenter,
    "Right": Qt.AlignRight | Qt.AlignVCenter,
}


def create_widget(type_name: str, props: dict, parent: QWidget = None) -> QWidget:
    """Create a real QWidget instance from type name and properties dict."""
    if type_name == "PushButton":
        w = PushButton(props.get("text", "按钮"), parent)
        w.setEnabled(props.get("enabled", True))
        return w

    if type_name == "Label":
        w = BodyLabel(props.get("text", "标签"), parent)
        w.setStyleSheet("border: none; background: transparent; padding: 0px;")
        font = w.font()
        font.setPointSize(props.get("fontSize", 14))
        font.setBold(props.get("bold", False))
        w.setFont(font)
        alignment = _ALIGNMENT_MAP.get(props.get("alignment", "Left"), Qt.AlignLeft)
        w.setAlignment(alignment)
        return w

    if type_name == "LineEdit":
        w = LineEdit(parent)
        w.setPlaceholderText(props.get("placeholderText", ""))
        w.setText(props.get("text", ""))
        w.setReadOnly(props.get("readOnly", False))
        return w

    if type_name == "ComboBox":
        w = ComboBox(parent)
        items_text = props.get("items", "")
        items = [s.strip() for s in items_text.split("\n") if s.strip()]
        w.addItems(items)
        idx = props.get("currentIndex", 0)
        if 0 <= idx < len(items):
            w.setCurrentIndex(idx)
        return w

    if type_name == "ToggleSwitch":
        container = QWidget(parent)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        label = QLabel(props.get("label", "开关"))
        sw = SwitchButton()
        sw.setChecked(props.get("checked", False))
        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(sw)
        container._switch = sw
        container._label = label
        return container

    if type_name == "Slider":
        w = Slider(Qt.Horizontal, parent)
        w.setMinimum(props.get("minimum", 0))
        w.setMaximum(props.get("maximum", 100))
        w.setValue(props.get("value", 50))
        return w

    if type_name == "SpinBox":
        w = SpinBox(parent)
        w.setMinimum(props.get("minimum", 0))
        w.setMaximum(props.get("maximum", 100))
        w.setValue(props.get("value", 0))
        suffix = props.get("suffix", "")
        if suffix:
            w.setSuffix(f" {suffix}")
        return w

    from app.widgets.layout import create_layout_widget
    from app.widgets.display import create_display_widget
    from app.widgets.chart import create_chart_widget
    from app.widgets.comm import create_comm_widget
    from app.widgets.composite import create_composite_widget

    for factory in (create_layout_widget, create_display_widget,
                    create_chart_widget, create_comm_widget,
                    create_composite_widget):
        result = factory(type_name, props, parent)
        if result is not None:
            return result

    raise ValueError(f"Unknown widget type: {type_name}")


def apply_property(widget: QWidget, type_name: str, prop_name: str, value):
    """Apply a single property change to an existing widget."""
    if type_name == "PushButton":
        if prop_name == "text":
            widget.setText(value)
        elif prop_name == "enabled":
            widget.setEnabled(value)

    elif type_name == "Label":
        if prop_name == "text":
            widget.setText(value)
        elif prop_name == "fontSize":
            f = widget.font()
            f.setPointSize(value)
            widget.setFont(f)
        elif prop_name == "bold":
            f = widget.font()
            f.setBold(value)
            widget.setFont(f)
        elif prop_name == "alignment":
            widget.setAlignment(_ALIGNMENT_MAP.get(value, Qt.AlignLeft))

    elif type_name == "LineEdit":
        if prop_name == "placeholderText":
            widget.setPlaceholderText(value)
        elif prop_name == "text":
            widget.setText(value)
        elif prop_name == "readOnly":
            widget.setReadOnly(value)

    elif type_name == "ComboBox":
        if prop_name == "items":
            widget.clear()
            items = [s.strip() for s in value.split("\n") if s.strip()]
            widget.addItems(items)
        elif prop_name == "currentIndex":
            if 0 <= value < widget.count():
                widget.setCurrentIndex(value)

    elif type_name == "ToggleSwitch":
        if prop_name == "label" and hasattr(widget, "_label"):
            widget._label.setText(value)
        elif prop_name == "checked" and hasattr(widget, "_switch"):
            widget._switch.setChecked(value)

    elif type_name == "Slider":
        if prop_name == "minimum":
            widget.setMinimum(value)
        elif prop_name == "maximum":
            widget.setMaximum(value)
        elif prop_name == "value":
            widget.setValue(value)

    elif type_name == "SpinBox":
        if prop_name == "minimum":
            widget.setMinimum(value)
        elif prop_name == "maximum":
            widget.setMaximum(value)
        elif prop_name == "value":
            widget.setValue(value)
        elif prop_name == "suffix":
            widget.setSuffix(f" {value}" if value else "")

    else:
        from app.widgets.layout import apply_layout_property
        from app.widgets.display import apply_display_property
        from app.widgets.chart import apply_chart_property
        from app.widgets.comm import apply_comm_property
        from app.widgets.composite import apply_composite_property

        for applier in (apply_layout_property, apply_display_property,
                        apply_chart_property, apply_comm_property,
                        apply_composite_property):
            applier(widget, type_name, prop_name, value)
