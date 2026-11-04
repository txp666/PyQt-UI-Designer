# coding: utf-8
"""Basic widget definitions: Button, Label, LineEdit, ComboBox, Switch, Slider, SpinBox."""
from PyQt5.QtWidgets import QWidget, QLabel, QHBoxLayout
from PyQt5.QtCore import Qt
from qfluentwidgets import (
    PushButton, BodyLabel, LineEdit, ComboBox,
    SwitchButton, Slider, SpinBox,
)

from app.widgets.base import (
    WidgetMeta, WidgetCategory, PropDef, PropType, normalized_range_properties,
)
from app.core.widget_registry import registry
from app.core.i18n import N_
from app.core.command_runtime import MODBUS_DATA_TYPES, MODBUS_FUNCTIONS, MODBUS_ORDERS


def _modbus_functions(*codes):
    """The function-code options a widget offers, named as MODBUS_FUNCTIONS names them."""
    return [name for name, code in MODBUS_FUNCTIONS.items() if code in codes]


# ---------------------------------------------------------------------------
# Widget metadata definitions
# ---------------------------------------------------------------------------

PUSH_BUTTON_META = WidgetMeta(
    type_name="PushButton",
    display_name=N_("按钮"),
    category=WidgetCategory.BASIC,
    icon="BUTTON",
    default_width=120, default_height=36,
    properties=[
        PropDef("text", N_("文本"), PropType.STRING, N_("按钮")),
        PropDef("enabled", N_("启用"), PropType.BOOL, True),
        PropDef("commandMode", N_("发送模式"), PropType.ENUM, "文本",  # i18n: value
                options=["文本", "HEX", "JSON", "Modbus"]),  # i18n: value
        PropDef("command", N_("发送内容"), PropType.COMMAND, ""),
        PropDef("commandTemplate", N_("发送模板"), PropType.STRING, "{value}"),
        PropDef("commandJsonNewline", N_("换行符"), PropType.ENUM, "无",  # i18n: value
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("frameHeader", N_("帧头(HEX)"), PropType.STRING, ""),
        PropDef("frameTail", N_("帧尾(HEX)"), PropType.STRING, ""),
        PropDef("dataType", N_("数据类型"), PropType.ENUM, "HEX字符串",  # i18n: value
                options=["HEX字符串", "uint8", "int8", "uint16", "int16",  # i18n: value
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", N_("字节序"), PropType.ENUM, "大端(BE)",  # i18n: value
                options=["大端(BE)", "小端(LE)"]),  # i18n: value
        PropDef("commandNewline", N_("换行符"), PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("mbSlave", N_("从站地址"), PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbFunc", N_("功能码"), PropType.ENUM, "03 读保持寄存器",  # i18n: value
                options=_modbus_functions(1, 2, 3, 4, 5, 6, 0x10)),
        PropDef("mbAddress", N_("寄存器地址"), PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("mbDataType", N_("数据类型"), PropType.ENUM, "uint16",
                options=list(MODBUS_DATA_TYPES)),
        PropDef("mbRegOrder", N_("寄存器序"), PropType.ENUM, MODBUS_ORDERS[0],
                options=list(MODBUS_ORDERS)),
        PropDef("mbValue", N_("值/数量"), PropType.INT, 1,
                min_val=-2147483648, max_val=2147483647),  # negative for int16 / int32 writes
        PropDef("notify", N_("按下通知"), PropType.BOOL, False),
        PropDef("notifyTitle", N_("通知标题"), PropType.STRING, N_("提示")),
        PropDef("notifyContent", N_("通知内容"), PropType.STRING, N_("按钮已按下")),
        PropDef("notifyType", N_("通知类型"), PropType.ENUM, "成功",  # i18n: value
                options=["成功", "信息", "警告", "错误"]),  # i18n: value
        PropDef("notifyDuration", N_("通知时长(ms)"), PropType.INT, 3000,
                min_val=500, max_val=30000),
    ],
)

LABEL_META = WidgetMeta(
    type_name="Label",
    display_name=N_("标签"),
    category=WidgetCategory.BASIC,
    icon="FONT",
    default_width=120, default_height=30,
    properties=[
        PropDef("text", N_("文本"), PropType.STRING, N_("标签")),
        PropDef("fontSize", N_("字号"), PropType.INT, 14, min_val=8, max_val=72),
        PropDef("bold", N_("加粗"), PropType.BOOL, False),
        PropDef("alignment", N_("对齐"), PropType.ENUM, "Left",
                options=["Left", "Center", "Right"]),
        PropDef("displayFormat", N_("显示格式"), PropType.ENUM, "自动",  # i18n: value
                options=["自动", "十进制", "十六进制(HEX)", "二进制(BIN)"]),  # i18n: value
        PropDef("decimals", N_("小数位数"), PropType.ENUM, "自动",  # i18n: value
                options=["自动", "0", "1", "2", "3", "4"]),  # i18n: value
    ],
)

LINE_EDIT_META = WidgetMeta(
    type_name="LineEdit",
    display_name=N_("输入框"),
    category=WidgetCategory.BASIC,
    icon="TEXT_FIELD",
    default_width=200, default_height=36,
    properties=[
        PropDef("placeholderText", N_("占位文本"), PropType.STRING, N_("请输入...")),
        PropDef("text", N_("默认值"), PropType.STRING, ""),
        PropDef("readOnly", N_("只读"), PropType.BOOL, False),
        PropDef("sendOnEnter", N_("回车发送"), PropType.BOOL, False),
        PropDef("commandMode", N_("发送模式"), PropType.ENUM, "文本",  # i18n: value
                options=["文本", "HEX", "JSON", "Modbus"]),  # i18n: value
        PropDef("commandTemplate", N_("发送模板"), PropType.STRING, "{value}"),
        PropDef("commandJsonNewline", N_("换行符"), PropType.ENUM, "无",  # i18n: value
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("frameHeader", N_("帧头(HEX)"), PropType.STRING, ""),
        PropDef("frameTail", N_("帧尾(HEX)"), PropType.STRING, ""),
        PropDef("dataType", N_("数据类型"), PropType.ENUM, "HEX字符串",  # i18n: value
                options=["HEX字符串", "uint8", "int8", "uint16", "int16",  # i18n: value
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", N_("字节序"), PropType.ENUM, "大端(BE)",  # i18n: value
                options=["大端(BE)", "小端(LE)"]),  # i18n: value
        PropDef("commandNewline", N_("换行符"), PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("mbSlave", N_("从站地址"), PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbFunc", N_("功能码"), PropType.ENUM, "06 写单寄存器",  # i18n: value
                options=_modbus_functions(3, 4, 5, 6, 0x10)),
        PropDef("mbAddress", N_("寄存器地址"), PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("mbDataType", N_("数据类型"), PropType.ENUM, "uint16",
                options=list(MODBUS_DATA_TYPES)),
        PropDef("mbRegOrder", N_("寄存器序"), PropType.ENUM, MODBUS_ORDERS[0],
                options=list(MODBUS_ORDERS)),
    ],
)

COMBO_BOX_META = WidgetMeta(
    type_name="ComboBox",
    display_name=N_("下拉框"),
    category=WidgetCategory.BASIC,
    icon="DROPDOWN",
    default_width=160, default_height=36,
    properties=[
        PropDef("items", N_("选项"), PropType.TEXT, N_("选项1\n选项2\n选项3")),
        PropDef("currentIndex", N_("默认选项"), PropType.INT, 0, min_val=0, max_val=99),
        PropDef("sendOnSelect", N_("选中发送"), PropType.BOOL, False),
        PropDef("commands", N_("发送命令表"), PropType.TEXT, "",),
        PropDef("commandMode", N_("发送模式"), PropType.ENUM, "文本",  # i18n: value
                options=["文本", "HEX", "JSON", "Modbus"]),  # i18n: value
        PropDef("commandTemplate", N_("发送模板"), PropType.STRING, "{value}"),
        PropDef("commandJsonNewline", N_("换行符"), PropType.ENUM, "无",  # i18n: value
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("frameHeader", N_("帧头(HEX)"), PropType.STRING, ""),
        PropDef("frameTail", N_("帧尾(HEX)"), PropType.STRING, ""),
        PropDef("dataType", N_("数据类型"), PropType.ENUM, "HEX字符串",  # i18n: value
                options=["HEX字符串", "uint8", "int8", "uint16", "int16",  # i18n: value
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", N_("字节序"), PropType.ENUM, "大端(BE)",  # i18n: value
                options=["大端(BE)", "小端(LE)"]),  # i18n: value
        PropDef("commandNewline", N_("换行符"), PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("mbSlave", N_("从站地址"), PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbFunc", N_("功能码"), PropType.ENUM, "06 写单寄存器",  # i18n: value
                options=_modbus_functions(3, 4, 5, 6, 0x10)),
        PropDef("mbAddress", N_("寄存器地址"), PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("mbDataType", N_("数据类型"), PropType.ENUM, "uint16",
                options=list(MODBUS_DATA_TYPES)),
        PropDef("mbRegOrder", N_("寄存器序"), PropType.ENUM, MODBUS_ORDERS[0],
                options=list(MODBUS_ORDERS)),
        PropDef("mbValue", N_("值/数量"), PropType.INT, 1,
                min_val=-2147483648, max_val=2147483647),  # negative for int16 / int32 writes
    ],
)

SWITCH_META = WidgetMeta(
    type_name="ToggleSwitch",
    display_name=N_("开关"),
    category=WidgetCategory.BASIC,
    icon="TOGGLE",
    default_width=140, default_height=30,
    properties=[
        PropDef("label", N_("标签"), PropType.STRING, N_("开关")),
        PropDef("checked", N_("默认开启"), PropType.BOOL, False),
        PropDef("commandMode", N_("发送模式"), PropType.ENUM, "文本",  # i18n: value
                options=["文本", "HEX", "JSON", "Modbus"]),  # i18n: value
        PropDef("onCommand", N_("开启命令"), PropType.COMMAND, ""),
        PropDef("offCommand", N_("关闭命令"), PropType.COMMAND, ""),
        PropDef("commandTemplate", N_("发送模板"), PropType.STRING, "{value}"),
        PropDef("commandJsonNewline", N_("换行符"), PropType.ENUM, "无",  # i18n: value
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("frameHeader", N_("帧头(HEX)"), PropType.STRING, ""),
        PropDef("frameTail", N_("帧尾(HEX)"), PropType.STRING, ""),
        PropDef("dataType", N_("数据类型"), PropType.ENUM, "HEX字符串",  # i18n: value
                options=["HEX字符串", "uint8", "int8", "uint16", "int16",  # i18n: value
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", N_("字节序"), PropType.ENUM, "大端(BE)",  # i18n: value
                options=["大端(BE)", "小端(LE)"]),  # i18n: value
        PropDef("commandNewline", N_("换行符"), PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("mbSlave", N_("从站地址"), PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbAddress", N_("线圈地址"), PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("notify", N_("切换通知"), PropType.BOOL, False),
        PropDef("notifyTitle", N_("通知标题"), PropType.STRING, N_("提示")),
        PropDef("notifyContent", N_("通知内容"), PropType.STRING, N_("开关已切换")),
        PropDef("notifyType", N_("通知类型"), PropType.ENUM, "信息",  # i18n: value
                options=["成功", "信息", "警告", "错误"]),  # i18n: value
        PropDef("notifyDuration", N_("通知时长(ms)"), PropType.INT, 3000,
                min_val=500, max_val=30000),
    ],
)

SLIDER_META = WidgetMeta(
    type_name="Slider",
    display_name=N_("滑块"),
    category=WidgetCategory.BASIC,
    icon="SLIDER",
    default_width=200, default_height=30,
    properties=[
        PropDef("minimum", N_("最小值"), PropType.INT, 0, min_val=-99999, max_val=99999),
        PropDef("maximum", N_("最大值"), PropType.INT, 100, min_val=-99999, max_val=99999),
        PropDef("value", N_("默认值"), PropType.INT, 50, min_val=-99999, max_val=99999),
        PropDef("sendOnChange", N_("变化发送"), PropType.BOOL, False),
        PropDef("commandMode", N_("发送模式"), PropType.ENUM, "文本",  # i18n: value
                options=["文本", "HEX", "JSON", "Modbus"]),  # i18n: value
        PropDef("commandTemplate", N_("发送模板"), PropType.STRING, "{value}"),
        PropDef("commandJsonNewline", N_("换行符"), PropType.ENUM, "无",  # i18n: value
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("frameHeader", N_("帧头(HEX)"), PropType.STRING, ""),
        PropDef("frameTail", N_("帧尾(HEX)"), PropType.STRING, ""),
        PropDef("commandNewline", N_("换行符"), PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("dataType", N_("数据类型"), PropType.ENUM, "uint16",
                options=["uint8", "int8", "uint16", "int16",
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", N_("字节序"), PropType.ENUM, "大端(BE)",  # i18n: value
                options=["大端(BE)", "小端(LE)"]),  # i18n: value
        PropDef("mbSlave", N_("从站地址"), PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbFunc", N_("功能码"), PropType.ENUM, "06 写单寄存器",  # i18n: value
                options=_modbus_functions(5, 6, 0x10)),
        PropDef("mbAddress", N_("寄存器地址"), PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("mbDataType", N_("数据类型"), PropType.ENUM, "uint16",
                options=list(MODBUS_DATA_TYPES)),
        PropDef("mbRegOrder", N_("寄存器序"), PropType.ENUM, MODBUS_ORDERS[0],
                options=list(MODBUS_ORDERS)),
    ],
)

SPIN_BOX_META = WidgetMeta(
    type_name="SpinBox",
    display_name=N_("数值框"),
    category=WidgetCategory.BASIC,
    icon="SPIN_BOX",
    default_width=140, default_height=36,
    properties=[
        PropDef("minimum", N_("最小值"), PropType.INT, 0, min_val=-99999, max_val=99999),
        PropDef("maximum", N_("最大值"), PropType.INT, 100, min_val=-99999, max_val=99999),
        PropDef("value", N_("默认值"), PropType.INT, 0, min_val=-99999, max_val=99999),
        PropDef("suffix", N_("后缀"), PropType.STRING, ""),
        PropDef("sendOnChange", N_("变化发送"), PropType.BOOL, False),
        PropDef("commandMode", N_("发送模式"), PropType.ENUM, "文本",  # i18n: value
                options=["文本", "HEX", "JSON", "Modbus"]),  # i18n: value
        PropDef("commandTemplate", N_("发送模板"), PropType.STRING, "{value}"),
        PropDef("commandJsonNewline", N_("换行符"), PropType.ENUM, "无",  # i18n: value
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("frameHeader", N_("帧头(HEX)"), PropType.STRING, ""),
        PropDef("frameTail", N_("帧尾(HEX)"), PropType.STRING, ""),
        PropDef("commandNewline", N_("换行符"), PropType.ENUM, "\\r\\n",
                options=["无", "\\r\\n", "\\n", "\\r"]),  # i18n: value
        PropDef("dataType", N_("数据类型"), PropType.ENUM, "uint16",
                options=["uint8", "int8", "uint16", "int16",
                         "uint32", "int32", "float32"]),
        PropDef("byteOrder", N_("字节序"), PropType.ENUM, "大端(BE)",  # i18n: value
                options=["大端(BE)", "小端(LE)"]),  # i18n: value
        PropDef("mbSlave", N_("从站地址"), PropType.INT, 1, min_val=1, max_val=247),
        PropDef("mbFunc", N_("功能码"), PropType.ENUM, "06 写单寄存器",  # i18n: value
                options=_modbus_functions(5, 6, 0x10)),
        PropDef("mbAddress", N_("寄存器地址"), PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("mbDataType", N_("数据类型"), PropType.ENUM, "uint16",
                options=list(MODBUS_DATA_TYPES)),
        PropDef("mbRegOrder", N_("寄存器序"), PropType.ENUM, MODBUS_ORDERS[0],
                options=list(MODBUS_ORDERS)),
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
    props = normalized_range_properties(type_name, props)
    if type_name == "PushButton":
        w = PushButton(props.get("text", "按钮"), parent)  # i18n: value
        w.setEnabled(props.get("enabled", True))
        return w

    if type_name == "Label":
        w = BodyLabel(props.get("text", "标签"), parent)  # i18n: value
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
        label = BodyLabel(props.get("label", "开关"))  # i18n: value
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
        w.setRange(props["minimum"], props["maximum"])
        w.setValue(props.get("value", 50))
        return w

    if type_name == "SpinBox":
        w = SpinBox(parent)
        w.setRange(props["minimum"], props["maximum"])
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
