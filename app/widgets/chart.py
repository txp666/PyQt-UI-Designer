# coding: utf-8
"""Design-time chart registration and preview signal wiring."""
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPainter, QColor, QFont, QPen
from PyQt5.QtWidgets import QWidget
from qfluentwidgets import isDarkTheme, qconfig
from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.widget_registry import registry
from app.core.chart_runtime import (
    RealtimeLineChart as RuntimeChart, build_cfgs_from_props, _CURVE_FIELD_MAP,
    _DEFAULT_CURVE_CFG,
)


class RealtimeLineChart(RuntimeChart):
    def start_listening(self):
        if self._listening:
            return
        self._listening = True
        from app.common.signal_bus import signalBus
        signalBus.serialDataReceived.connect(self._on_parsed_data)
        signalBus.serialRawReceived.connect(self._on_raw_data)
        signalBus.serialDisconnected.connect(self.reset_stream)

    def stop_listening(self):
        if not self._listening:
            return
        self._listening = False
        from app.common.signal_bus import signalBus
        try:
            signalBus.serialDataReceived.disconnect(self._on_parsed_data)
            signalBus.serialRawReceived.disconnect(self._on_raw_data)
            signalBus.serialDisconnected.disconnect(self.reset_stream)
        except TypeError:
            pass
        self.reset_stream()


# ---------------------------------------------------------------------------
# Gauge meter
# ---------------------------------------------------------------------------

class GaugeMeter(QWidget):
    """Analog gauge / dial meter display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._min_val = 0.0
        self._max_val = 100.0
        self._title = "仪表"
        self._unit = ""
        self.setMinimumSize(80, 80)
        qconfig.themeChangedFinished.connect(self.update)

    def set_value(self, v: float):
        self._value = max(self._min_val, min(self._max_val, v))
        self.update()

    def set_range(self, lo: float, hi: float):
        self._min_val = lo
        self._max_val = max(lo, hi)
        self.set_value(self._value)

    def set_title(self, t: str):
        self._title = t
        self.update()

    def set_unit(self, u: str):
        self._unit = u
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        side = min(w, h) - 10
        cx, cy = w / 2, h / 2
        radius = side / 2

        # arc background
        arc_rect = QRectF(cx - radius, cy - radius, side, side)
        start_angle = 225  # degrees
        span_angle = -270

        dark = isDarkTheme()
        bg_pen = QPen(QColor("#555555" if dark else "#dcdcdc"), max(6, side / 12))
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(arc_rect, int(start_angle * 16), int(span_angle * 16))

        # value arc
        rng = self._max_val - self._min_val
        ratio = (self._value - self._min_val) / rng if rng > 0 else 0
        val_span = span_angle * ratio

        val_pen = QPen(QColor("#4cc2ff" if dark else "#0078d4"), max(6, side / 12))
        val_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(val_pen)
        painter.drawArc(arc_rect, int(start_angle * 16), int(val_span * 16))

        # value text
        painter.setPen(QColor("#f3f3f3" if dark else "#1e1e1e"))
        font_size = max(10, int(side / 6))
        painter.setFont(QFont(self.font().family(), font_size, QFont.Bold))
        val_text = f"{self._value:.1f}"
        painter.drawText(self.rect(), Qt.AlignCenter, val_text)

        # unit text below
        painter.setFont(QFont(self.font().family(), max(8, int(font_size * 0.6))))
        painter.setPen(QColor("#b3b3b3" if dark else "#606060"))
        unit_rect = self.rect().adjusted(0, int(font_size * 1.5), 0, 0)
        painter.drawText(unit_rect, Qt.AlignHCenter | Qt.AlignTop, self._unit)

        # title text above
        painter.setFont(QFont(self.font().family(), max(8, int(font_size * 0.5))))
        painter.setPen(QColor("#b3b3b3" if dark else "#606060"))
        title_rect = self.rect().adjusted(0, 0, 0, -int(font_size * 1.5))
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignBottom, self._title)

        painter.end()


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

_PARSE_MODES = ["键值匹配", "JSON路径", "HEX字节提取", "Modbus"]
_HEX_DTYPES = ["uint8", "int8", "uint16", "int16", "uint32", "int32", "float32"]
_HEX_BORDER = ["大端(BE)", "小端(LE)"]
_MB_DTYPES = ["uint16", "int16", "uint32", "int32", "float32"]
_MB_REGORD = ["大端(AB CD)", "小端(CD AB)"]

REALTIME_CHART_META = WidgetMeta(
    type_name="RealtimeChart",
    display_name="实时曲线",
    category=WidgetCategory.CHART,
    icon="HISTORY",
    default_width=400, default_height=280,
    min_width=200, min_height=150,
    properties=[
        PropDef("title", "标题", PropType.STRING, "实时曲线"),
        PropDef("displayPoints", "显示点数", PropType.INT, 200,
                min_val=10, max_val=10000),
        PropDef("curveCount", "曲线数量", PropType.INT, 1,
                min_val=1, max_val=8),
        PropDef("currentCurve", "当前编辑曲线", PropType.INT, 0,
                min_val=0, max_val=7),
        # ---- per-curve virtual (stored as _curve_{i}_{field}) ----
        PropDef("curveName", "曲线名称", PropType.STRING, "曲线1"),
        PropDef("curveParseMode", "解析模式", PropType.ENUM, "键值匹配",
                options=_PARSE_MODES),
        PropDef("curveKey", "匹配键", PropType.STRING, ""),
        PropDef("curveJsonPath", "JSON路径", PropType.STRING, ""),
        PropDef("curveByteOffset", "字节偏移", PropType.INT, 0,
                min_val=0, max_val=9999),
        PropDef("curveDataType", "数据类型(HEX)", PropType.ENUM, "float32",
                options=_HEX_DTYPES),
        PropDef("curveByteOrder", "字节序(HEX)", PropType.ENUM, "大端(BE)",
                options=_HEX_BORDER),
        PropDef("curveFrameHeader", "帧头(HEX)", PropType.STRING, ""),
        PropDef("curveFrameTail", "帧尾(HEX)", PropType.STRING, ""),
        PropDef("curveRegIndex", "寄存器索引", PropType.INT, 0,
                min_val=0, max_val=65535),
        PropDef("curveMbDataType", "数据类型(MB)", PropType.ENUM, "uint16",
                options=_MB_DTYPES),
        PropDef("curveMbRegOrder", "寄存器序(MB)", PropType.ENUM, "大端(AB CD)",
                options=_MB_REGORD),
        PropDef("curveMbFcFilter", "功能码过滤", PropType.INT, -1,
                min_val=-1, max_val=255),
        PropDef("curveMbSlaveFilter", "从站过滤", PropType.INT, -1,
                min_val=-1, max_val=255),
    ],
)

GAUGE_META = WidgetMeta(
    type_name="GaugeMeter",
    display_name="仪表盘",
    category=WidgetCategory.CHART,
    icon="SPEED_HIGH",
    default_width=180, default_height=180,
    min_width=80, min_height=80,
    properties=[
        PropDef("title", "标题", PropType.STRING, "仪表"),
        PropDef("unit", "单位", PropType.STRING, ""),
        PropDef("value", "当前值", PropType.FLOAT, 0.0, min_val=-99999, max_val=99999, bindable=True),
        PropDef("minimum", "最小值", PropType.FLOAT, 0.0, min_val=-99999, max_val=99999),
        PropDef("maximum", "最大值", PropType.FLOAT, 100.0, min_val=-99999, max_val=99999),
    ],
)

ALL_CHART = [REALTIME_CHART_META, GAUGE_META]


def register_chart_widgets():
    for meta in ALL_CHART:
        registry.register(meta)


def create_chart_widget(type_name: str, props: dict, parent=None) -> QWidget:
    if type_name == "RealtimeChart":
        w = RealtimeLineChart(parent)
        w.set_title(props.get("title", "实时曲线"))
        w.set_display_points(props.get("displayPoints", 200))
        w.load_from_props(props)
        return w

    if type_name == "GaugeMeter":
        w = GaugeMeter(parent)
        w.set_title(props.get("title", "仪表"))
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
