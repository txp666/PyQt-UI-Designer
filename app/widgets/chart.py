# coding: utf-8
"""Design-time chart registration and preview signal wiring."""
from PyQt5.QtWidgets import QWidget
from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.i18n import N_
from app.core.widget_registry import registry
from app.core.binding_values import MODBUS_AREAS
from app.core.chart_runtime import (
    RealtimeLineChart as RuntimeChart, build_cfgs_from_props, _CURVE_FIELD_MAP,
    _DEFAULT_CURVE_CFG,
)
from app.core.gauge_runtime import GaugeMeter  # noqa: F401  (registered below, shared with exports)


class RealtimeLineChart(RuntimeChart):
    def start_listening(self):
        if self._listening:
            return
        self._listening = True
        from app.common.signal_bus import signalBus
        self._serial_connections.connect(signalBus.serialDataReceived, self._on_parsed_data)
        self._serial_connections.connect(signalBus.serialRawReceived, self._on_raw_data)
        self._serial_connections.connect(signalBus.serialDisconnected, self.reset_stream)

    def stop_listening(self):
        if not self._listening:
            return
        self._listening = False
        self._serial_connections.clear()
        self.reset_stream()


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

_PARSE_MODES = ["键值匹配", "JSON路径", "HEX字节提取", "Modbus"]  # i18n: value
_HEX_DTYPES = ["uint8", "int8", "uint16", "int16", "uint32", "int32", "float32"]
_HEX_BORDER = ["大端(BE)", "小端(LE)"]  # i18n: value
_MB_DTYPES = ["uint16", "int16", "uint32", "int32", "float32"]
_MB_REGORD = ["大端(AB CD)", "小端(CD AB)"]  # i18n: value

REALTIME_CHART_META = WidgetMeta(
    type_name="RealtimeChart",
    display_name=N_("实时曲线"),
    category=WidgetCategory.CHART,
    icon="MARKET",
    default_width=400, default_height=280,
    min_width=200, min_height=150,
    properties=[
        PropDef("title", N_("标题"), PropType.STRING, N_("实时曲线")),
        PropDef("displayPoints", N_("显示点数"), PropType.INT, 200,
                min_val=10, max_val=10000),
        PropDef("curveCount", N_("曲线数量"), PropType.INT, 1,
                min_val=1, max_val=8),
        PropDef("currentCurve", N_("当前编辑曲线"), PropType.INT, 0,
                min_val=0, max_val=7),
        # ---- per-curve virtual (stored as _curve_{i}_{field}) ----
        PropDef("curveName", N_("曲线名称"), PropType.STRING, N_("曲线1")),
        PropDef("curveParseMode", N_("解析模式"), PropType.ENUM, "键值匹配",  # i18n: value
                options=_PARSE_MODES),
        PropDef("curveKey", N_("匹配键"), PropType.STRING, ""),
        PropDef("curveJsonPath", N_("JSON路径"), PropType.STRING, ""),
        PropDef("curveByteOffset", N_("字节偏移"), PropType.INT, 0,
                min_val=0, max_val=9999),
        PropDef("curveDataType", N_("数据类型(HEX)"), PropType.ENUM, "float32",
                options=_HEX_DTYPES),
        PropDef("curveByteOrder", N_("字节序(HEX)"), PropType.ENUM, "大端(BE)",  # i18n: value
                options=_HEX_BORDER),
        PropDef("curveFrameHeader", N_("帧头(HEX)"), PropType.STRING, ""),
        PropDef("curveFrameTail", N_("帧尾(HEX)"), PropType.STRING, ""),
        PropDef("curveMbArea", N_("寄存器区"), PropType.ENUM, "保持寄存器",  # i18n: value
                options=list(MODBUS_AREAS)),
        PropDef("curveRegIndex", N_("寄存器地址"), PropType.INT, 0,
                min_val=0, max_val=65535),
        PropDef("curveMbDataType", N_("数据类型(MB)"), PropType.ENUM, "uint16",
                options=_MB_DTYPES),
        PropDef("curveMbRegOrder", N_("寄存器序(MB)"), PropType.ENUM, "大端(AB CD)",  # i18n: value
                options=_MB_REGORD),
        PropDef("curveMbFcFilter", N_("功能码过滤"), PropType.INT, -1,
                min_val=-1, max_val=255),
        PropDef("curveMbSlaveFilter", N_("从站过滤"), PropType.INT, -1,
                min_val=-1, max_val=255),
    ],
)

GAUGE_META = WidgetMeta(
    type_name="GaugeMeter",
    display_name=N_("仪表盘"),
    category=WidgetCategory.CHART,
    icon="SPEED_HIGH",
    default_width=180, default_height=180,
    min_width=80, min_height=80,
    properties=[
        PropDef("title", N_("标题"), PropType.STRING, N_("仪表")),
        PropDef("unit", N_("单位"), PropType.STRING, ""),
        PropDef("value", N_("当前值"), PropType.FLOAT, 0.0, min_val=-99999, max_val=99999),
        PropDef("minimum", N_("最小值"), PropType.FLOAT, 0.0, min_val=-99999, max_val=99999),
        PropDef("maximum", N_("最大值"), PropType.FLOAT, 100.0, min_val=-99999, max_val=99999),
    ],
)

ALL_CHART = [REALTIME_CHART_META, GAUGE_META]


def register_chart_widgets():
    for meta in ALL_CHART:
        registry.register(meta)


def create_chart_widget(type_name: str, props: dict, parent=None) -> QWidget:
    if type_name == "RealtimeChart":
        w = RealtimeLineChart(parent)
        w.set_title(props.get("title", "实时曲线"))  # i18n: value
        w.set_display_points(props.get("displayPoints", 200))
        w.load_from_props(props)
        return w

    if type_name == "GaugeMeter":
        w = GaugeMeter(parent)
        w.set_title(props.get("title", "仪表"))  # i18n: value
        w.set_unit(props.get("unit", ""))
        w.set_range(props.get("minimum", 0), props.get("maximum", 100))
        w.set_value(props.get("value", 0))
        return w

    return None


def apply_chart_property(widget, type_name: str, prop_name: str, value):
    if type_name == "RealtimeChart":
        if prop_name == "title":
            widget.set_title(value)
        elif prop_name == "displayPoints":
            widget.set_display_points(value)

    elif type_name == "GaugeMeter":
        if prop_name == "title":
            widget.set_title(value)
        elif prop_name == "unit":
            widget.set_unit(value)
        elif prop_name == "value":
            widget.set_value(value)
        elif prop_name == "minimum":
            widget.set_range(value, widget._max_val)
        elif prop_name == "maximum":
            widget.set_range(widget._min_val, value)
