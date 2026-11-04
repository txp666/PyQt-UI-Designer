# coding: utf-8
"""Display widgets: LED indicator, numeric display, progress bar, progress ring, image display."""
from pathlib import Path
from PyQt5.QtCore import Qt, QRectF, QSize
from PyQt5.QtGui import QPainter, QColor, QFont, QImage, QPen
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLayout
from qfluentwidgets import (
    ProgressBar, ProgressRing, BodyLabel, CaptionLabel, ImageLabel, isDarkTheme, qconfig, themeColor,
)

from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.widget_registry import registry
from app.core.signal_lifetime import SignalConnections


def resolved_image_properties(properties, base_dir=None):
    props = dict(properties)
    path = props.get("imagePath", "")
    if path:
        source = Path(path).expanduser()
        if not source.is_absolute():
            source = Path(base_dir or Path.cwd()) / source
        props["imagePath"] = str(source.resolve())
    return props


# ---------------------------------------------------------------------------
# Custom display widgets
# ---------------------------------------------------------------------------

class LEDIndicator(QWidget):
    """Simple circular LED indicator (red/green/yellow)."""

    COLOR_MAP = {
        "green": QColor(76, 175, 80),
        "red": QColor(244, 67, 54),
        "yellow": QColor(255, 193, 7),
        "blue": QColor(33, 150, 243),
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

    def set_color(self, name: str):
        self._color_name = name
        self.update()

    def set_on(self, on: bool):
        self._on = on
        self.update()

    def set_label(self, text: str):
        self._label_text = text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        color = self.COLOR_MAP.get(self._color_name, QColor(76, 175, 80))
        if not self._on:
            color = QColor("#777777" if isDarkTheme() else "#c8c8c8")

        size = min(self.height(), 30)
        x = 4
        y = (self.height() - size) // 2

        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(x, y, size, size)

        # border highlight
        painter.setBrush(Qt.NoBrush)
        painter.setPen(color.darker(120))
        painter.drawEllipse(x, y, size, size)

        if self._label_text:
            painter.setPen(QColor("#f3f3f3" if isDarkTheme() else "#3c3c3c"))
            painter.setFont(QFont(self.font().family(), 10))
            text_x = x + size + 8
            painter.drawText(text_x, 0, self.width() - text_x, self.height(),
                             Qt.AlignVCenter | Qt.AlignLeft, self._label_text)
        painter.end()


class NumericDisplay(QWidget):
    """Large numeric value display with unit label."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)

        self._title_label = CaptionLabel("标题")
        self._value_label = BodyLabel("0.00")
        self._unit_label = CaptionLabel("")
        for label in (self._title_label, self._unit_label):
            label.setTextColor(QColor("#606060"), QColor("#b3b3b3"))
        # An empty unit keeps its line, so the titles of cards with and without one line up.
        self._unit_label.setMinimumHeight(self._unit_label.fontMetrics().height())
        for label in (self._title_label, self._value_label, self._unit_label):
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)
        self._update_value_style()
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self._update_value_style)
        self._theme_connections.connect(qconfig.themeColorChanged, self._update_value_style)

    def set_title(self, text: str):
        self._title_label.setText(text)

    def set_value(self, text: str):
        self._value_label.setText(text)

    def set_unit(self, text: str):
        self._unit_label.setText(text)

    def set_value_color(self, color: str):
        self._val_color = color
        self._update_value_style()

    def set_font_size(self, size: int):
        self._val_font_size = size
        self._update_value_style()

    def _update_value_style(self):
        # The value takes the theme colour, as FluentHMI Studio's does, unless one was set.
        color = QColor(getattr(self, "_val_color", None) or themeColor())
        font = self._value_label.font()
        font.setPixelSize(getattr(self, "_val_font_size", 28))
        font.setBold(True)
        self._value_label.setFont(font)
        self._value_label.setTextColor(color, color)


class ProgressRingDisplay(QWidget):
    """Circular progress indicator with value label."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(4)

        self._ring = ProgressRing()
        self._ring.setRange(0, 100)
        self._ring.setValue(0)
        self._ring.setFixedSize(80, 80)
        self._ring.setTextVisible(True)

        self._label = CaptionLabel("进度")
        self._label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self._ring, 0, Qt.AlignCenter)
        layout.addWidget(self._label)

    def set_value(self, v): self._ring.setValue(int(v))
    def set_maximum(self, v): self._ring.setMaximum(int(v))
    def set_label(self, t): self._label.setText(t)
    def set_ring_size(self, s): self._ring.setFixedSize(s, s)


class ImageDisplay(QWidget):
    """Static image display widget: the picture aspect-fit and centred, or a placeholder."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._image = QImage()
        self._label = ImageLabel(self)
        self._label.hide()
        self._placeholder = CaptionLabel("未选择图片", self)
        self._placeholder.setTextColor(QColor("#606060"), QColor("#b3b3b3"))
        self._placeholder.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # The picture's fixed size must never become the widget's minimum.
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        layout.addWidget(self._label, 0, Qt.AlignCenter)
        layout.addWidget(self._placeholder, 0, Qt.AlignCenter)
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self.update)

    def set_image_path(self, path: str):
        self._path = path
        self._image = QImage(path) if path else QImage()
        if self._image.isNull():
            self._label.hide()
            self._placeholder.setText("无法加载图片" if path else "未选择图片")
            self._placeholder.show()
        else:
            self._placeholder.hide()
            self._label.setImage(self._image)
            self._fit_image()
            self._label.show()
        self.update()

    def _fit_image(self):
        if not self._image.isNull():
            self._label.setScaledSize(self._image.size().scaled(self.size(), Qt.KeepAspectRatio))

    def sizeHint(self):
        return QSize(200, 150)

    def minimumSizeHint(self):
        return QSize(1, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_image()

    def paintEvent(self, event):
        if not self._image.isNull():
            return
        dark = isDarkTheme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#606060" if dark else "#c8c8c8"), 1, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor("#292929" if dark else "#f5f5f5"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)


# ---------------------------------------------------------------------------
# Widget metadata
# ---------------------------------------------------------------------------

LED_META = WidgetMeta(
    type_name="LEDIndicator",
    display_name="LED指示灯",
    category=WidgetCategory.DISPLAY,
    icon="LED",
    default_width=140, default_height=30,
    properties=[
        PropDef("label", "标签", PropType.STRING, "状态"),
        PropDef("color", "颜色", PropType.ENUM, "green",
                options=["green", "red", "yellow", "blue", "gray"]),
        PropDef("on", "点亮", PropType.BOOL, True),
        PropDef("onValue", "亮值", PropType.STRING, "1"),
        PropDef("offValue", "灭值", PropType.STRING, "0"),
    ],
)

NUMERIC_DISPLAY_META = WidgetMeta(
    type_name="NumericDisplay",
    display_name="数值显示",
    category=WidgetCategory.DISPLAY,
    icon="SEVEN_SEGMENT",
    default_width=160, default_height=90,
    properties=[
        PropDef("title", "标题", PropType.STRING, "温度"),
        PropDef("value", "数值", PropType.STRING, "0.00"),
        PropDef("unit", "单位", PropType.STRING, "°C"),
        PropDef("fontSize", "字号", PropType.INT, 28, min_val=12, max_val=72),
        PropDef("displayFormat", "显示格式", PropType.ENUM, "自动",
                options=["自动", "十进制", "十六进制(HEX)", "二进制(BIN)"]),
        PropDef("decimals", "小数位数", PropType.ENUM, "自动",
                options=["自动", "0", "1", "2", "3", "4"]),
    ],
)

PROGRESS_BAR_META = WidgetMeta(
    type_name="ProgressBar",
    display_name="进度条",
    category=WidgetCategory.DISPLAY,
    icon="PROGRESS_BAR",
    default_width=250, default_height=20,
    min_height=10,
    properties=[
        PropDef("value", "当前值", PropType.INT, 50, min_val=0, max_val=100),
        PropDef("maximum", "最大值", PropType.INT, 100, min_val=1, max_val=99999),
    ],
)

PROGRESS_RING_META = WidgetMeta(
    type_name="ProgressRingDisplay",
    display_name="进度环",
    category=WidgetCategory.DISPLAY,
    icon="PROGRESS_RING",
    default_width=120, default_height=130,
    min_width=80, min_height=80,
    properties=[
        PropDef("label", "标签", PropType.STRING, "进度"),
        PropDef("value", "当前值", PropType.INT, 0, min_val=0, max_val=100),
        PropDef("maximum", "最大值", PropType.INT, 100, min_val=1, max_val=99999),
    ],
)

IMAGE_DISPLAY_META = WidgetMeta(
    type_name="ImageDisplay",
    display_name="图片显示",
    category=WidgetCategory.DISPLAY,
    icon="PHOTO",
    default_width=200, default_height=150,
    properties=[
        PropDef("imagePath", "图片路径", PropType.STRING, ""),
    ],
)

ALL_DISPLAY = [LED_META, NUMERIC_DISPLAY_META, PROGRESS_BAR_META, PROGRESS_RING_META,
               IMAGE_DISPLAY_META]


def register_display_widgets():
    for meta in ALL_DISPLAY:
        registry.register(meta)


# ---------------------------------------------------------------------------
# Factory integration — extend basic.create_widget
# ---------------------------------------------------------------------------

def create_display_widget(type_name: str, props: dict, parent=None) -> QWidget:
    if type_name == "LEDIndicator":
        w = LEDIndicator(parent)
        w.set_label(props.get("label", "状态"))
        w.set_color(props.get("color", "green"))
        w.set_on(props.get("on", True))
        return w

    if type_name == "NumericDisplay":
        w = NumericDisplay(parent)
        w.set_title(props.get("title", "温度"))
        w.set_value(props.get("value", "0.00"))
        w.set_unit(props.get("unit", "°C"))
        w.set_font_size(props.get("fontSize", 28))
        return w

    if type_name == "ProgressBar":
        w = ProgressBar(parent)
        w.setMaximum(props.get("maximum", 100))
        w.setValue(props.get("value", 50))
        return w

    if type_name == "ProgressRingDisplay":
        w = ProgressRingDisplay(parent)
        w.set_label(props.get("label", "进度"))
        w.set_maximum(props.get("maximum", 100))
        w.set_value(props.get("value", 0))
        return w

    if type_name == "ImageDisplay":
        w = ImageDisplay(parent)
        w.set_image_path(props.get("imagePath", ""))
        return w

    return None


def apply_display_property(widget, type_name: str, prop_name: str, value):
    if type_name == "LEDIndicator":
        if prop_name == "label":
            widget.set_label(value)
        elif prop_name == "color":
            widget.set_color(value)
        elif prop_name == "on":
            widget.set_on(value)

    elif type_name == "NumericDisplay":
        if prop_name == "title":
            widget.set_title(value)
        elif prop_name == "value":
            widget.set_value(str(value))
        elif prop_name == "unit":
            widget.set_unit(value)
        elif prop_name == "fontSize":
            widget.set_font_size(value)

    elif type_name == "ProgressBar":
        if prop_name == "value":
            widget.setValue(value)
        elif prop_name == "maximum":
            widget.setMaximum(value)

    elif type_name == "ProgressRingDisplay":
        if prop_name == "label":
            widget.set_label(value)
        elif prop_name == "value":
            widget.set_value(value)
        elif prop_name == "maximum":
            widget.set_maximum(value)

    elif type_name == "ImageDisplay":
        if prop_name == "imagePath":
            widget.set_image_path(value)
