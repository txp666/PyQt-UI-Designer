# coding: utf-8
"""Display widgets: LED indicator, numeric display, progress bar, image display."""
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor, QFont, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
)
from qfluentwidgets import ProgressBar, BodyLabel, isDarkTheme, qconfig

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

        self._title_label = QLabel("标题")
        self._title_label.setAlignment(Qt.AlignCenter)

        self._value_label = QLabel("0.00")
        self._value_label.setAlignment(Qt.AlignCenter)

        self._unit_label = QLabel("")
        self._unit_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self._title_label)
        layout.addWidget(self._value_label)
        layout.addWidget(self._unit_label)
        self.apply_theme()
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self.apply_theme)

    def apply_theme(self):
        secondary = "#b3b3b3" if isDarkTheme() else "#606060"
        self._title_label.setStyleSheet(f"color: {secondary}; font-size: 11px;")
        self._unit_label.setStyleSheet(f"color: {secondary}; font-size: 12px;")
        self._update_value_style()

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
        color = getattr(self, "_val_color", "#0078d4")
        size = getattr(self, "_val_font_size", 28)
        self._value_label.setStyleSheet(
            f"font-size: {size}px; font-weight: bold; color: {color};"
        )


class ImageDisplay(QWidget):
    """Static image display widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setText("图片")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self._path = ""
        self.apply_theme()
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self.apply_theme)

    def apply_theme(self):
        dark = isDarkTheme()
        background = "#292929" if dark else "#f5f5f5"
        foreground = "#f3f3f3" if dark else "#3c3c3c"
        border = "#606060" if dark else "#c8c8c8"
        self._label.setStyleSheet(
            f"background: {background}; color: {foreground}; "
            f"border: 1px dashed {border};"
        )

    def set_image_path(self, path: str):
        self._path = path
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self._label.setPixmap(
                    pixmap.scaled(self._label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                return
        self._label.setText("图片")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._path:
            self.set_image_path(self._path)


# ---------------------------------------------------------------------------
# Widget metadata
# ---------------------------------------------------------------------------

LED_META = WidgetMeta(
    type_name="LEDIndicator",
    display_name="LED指示灯",
    category=WidgetCategory.DISPLAY,
    icon="CALORIES",
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
    icon="SPEED_HIGH",
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
    icon="SPEED_MEDIUM",
    default_width=250, default_height=20,
    min_height=10,
    properties=[
        PropDef("value", "当前值", PropType.INT, 50, min_val=0, max_val=100),
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

ALL_DISPLAY = [LED_META, NUMERIC_DISPLAY_META, PROGRESS_BAR_META, IMAGE_DISPLAY_META]


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

    elif type_name == "ImageDisplay":
        if prop_name == "imagePath":
            widget.set_image_path(value)
