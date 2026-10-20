# coding: utf-8
"""Layout container widgets: HBox, VBox, Grid, GroupBox, TabWidget."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QGroupBox, QTabWidget, QLabel, QSizePolicy, QFrame,
)
from qfluentwidgets import isDarkTheme, CardWidget, qconfig

from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.widget_registry import registry


def tab_names(names_text: str) -> list:
    """A tab container always has at least one usable page."""
    return [name.strip() for name in names_text.split("\n") if name.strip()] or ["标签1"]


def clamp_tab_index(index: int, count: int) -> int:
    return max(0, min(int(index), max(0, count - 1)))


class HBoxContainer(QFrame):
    """Horizontal flex container — children are laid out left to right."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(8)
        self._title = "水平布局"
        self.apply_theme()
        qconfig.themeChangedFinished.connect(self.apply_theme)

    def set_title(self, t): self._title = t; self.update()
    def set_spacing(self, s): self._layout.setSpacing(s)

    def apply_theme(self):
        dark = isDarkTheme()
        border = "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.06)"
        bg = "rgba(255,255,255,0.03)" if dark else "rgba(0,0,0,0.02)"
        self.setStyleSheet(
            f"HBoxContainer {{ border: 2px dashed {border}; "
            f"background: {bg}; border-radius: 6px; }}"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._title:
            p = QPainter(self)
            p.setPen(QColor("#b3b3b3" if isDarkTheme() else "#606060"))
            p.setFont(QFont(self.font().family(), 8))
            p.drawText(6, 14, self._title)
            p.end()


class VBoxContainer(QFrame):
    """Vertical flex container — children are laid out top to bottom."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(8)
        self._title = "垂直布局"
        self.apply_theme()
        qconfig.themeChangedFinished.connect(self.apply_theme)

    def set_title(self, t): self._title = t; self.update()
    def set_spacing(self, s): self._layout.setSpacing(s)

    def apply_theme(self):
        dark = isDarkTheme()
        border = "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.06)"
        bg = "rgba(255,255,255,0.03)" if dark else "rgba(0,0,0,0.02)"
        self.setStyleSheet(
            f"VBoxContainer {{ border: 2px dashed {border}; "
            f"background: {bg}; border-radius: 6px; }}"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._title:
            p = QPainter(self)
            p.setPen(QColor("#b3b3b3" if isDarkTheme() else "#606060"))
            p.setFont(QFont(self.font().family(), 8))
            p.drawText(6, 14, self._title)
            p.end()


class FlexContainer(QFrame):
    """Flex/Wrap container — children wrap to next line when full."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = "弹性布局"
        self._spacing = 8
        self._direction = "row"
        self.apply_theme()
        qconfig.themeChangedFinished.connect(self.apply_theme)

    def set_title(self, t): self._title = t; self.update()
    def set_spacing(self, s): self._spacing = s
    def set_direction(self, d): self._direction = d

    def apply_theme(self):
        dark = isDarkTheme()
        border = "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.06)"
        bg = "rgba(255,255,255,0.03)" if dark else "rgba(0,0,0,0.02)"
        self.setStyleSheet(
            f"FlexContainer {{ border: 2px dashed {border}; "
            f"background: {bg}; border-radius: 6px; }}"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QColor("#b3b3b3" if isDarkTheme() else "#606060"))
        p.setFont(QFont(self.font().family(), 8))
        p.drawText(6, 14, self._title)
        p.end()


class GroupBoxContainer(QGroupBox):
    """Styled group box with title."""

    def __init__(self, parent=None):
        super().__init__("分组", parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 20, 8, 8)
        self._layout.setSpacing(6)
        self.apply_theme()
        qconfig.themeChangedFinished.connect(self.apply_theme)

    def set_title(self, t): self.setTitle(t)

    def apply_theme(self):
        foreground = "#f3f3f3" if isDarkTheme() else "#202020"
        border = "#606060" if isDarkTheme() else "#c8c8c8"
        self.setStyleSheet(
            "GroupBoxContainer {"
            f"color: {foreground}; border: 1px solid {border}; "
            "border-radius: 6px; margin-top: 10px; }"
            "GroupBoxContainer::title { subcontrol-origin: margin; "
            "subcontrol-position: top left; left: 10px; padding: 0 4px; }"
        )


class TabContainer(QTabWidget):
    """Tab widget with configurable tab names."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tab_names = ["标签1", "标签2"]
        self._rebuild_tabs()
        self.apply_theme()
        qconfig.themeChangedFinished.connect(self.apply_theme)

    def apply_theme(self):
        dark = isDarkTheme()
        foreground = "#f3f3f3" if dark else "#202020"
        border = "#606060" if dark else "#c8c8c8"
        tab = "#292929" if dark else "#ededed"
        selected = "#3c3c3c" if dark else "#ffffff"
        self.setStyleSheet(
            "TabContainer::pane {"
            f"border: 1px solid {border}; border-radius: 4px; }}"
            "TabContainer > QTabBar::tab {"
            f"color: {foreground}; background: {tab}; "
            "padding: 6px 12px; margin-right: 2px; "
            "border-top-left-radius: 4px; border-top-right-radius: 4px; }"
            "TabContainer > QTabBar::tab:selected {"
            f"background: {selected}; }}"
        )

    def set_tab_names(self, names_text: str):
        self._tab_names = tab_names(names_text)
        self._rebuild_tabs()

    def _rebuild_tabs(self):
        current = self.currentIndex()
        # Keep surviving page widgets and their contents when a label changes.
        while self.count() < len(self._tab_names):
            page = QWidget()
            page.setStyleSheet("background: transparent;")
            self.addTab(page, "")
        while self.count() > len(self._tab_names):
            page = self.widget(self.count() - 1)
            destination = self.widget(len(self._tab_names) - 1)
            for child in page.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
                position = child.pos()
                child.setParent(destination)
                child.move(position)
                child.show()
            self.removeTab(self.count() - 1)
            page.deleteLater()
        for index, name in enumerate(self._tab_names):
            self.setTabText(index, name)
        self.setCurrentIndex(clamp_tab_index(current, self.count()))


class Separator(QFrame):
    """Visual separator line (horizontal or vertical)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._orientation = "horizontal"
        self._apply()

    def set_orientation(self, o: str):
        self._orientation = o
        self._apply()

    def _apply(self):
        # Release the old fixed axis when changing orientation.
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        if self._orientation == "horizontal":
            self.setFrameShape(QFrame.HLine)
            self.setFixedHeight(2)
        else:
            self.setFrameShape(QFrame.VLine)
            self.setFixedWidth(2)
        self.setStyleSheet("color: rgba(128,128,128,0.3);")


class CardContainer(CardWidget):
    """Empty card container — children can be freely placed inside."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = ""
        self._radius = 8
        self.setBorderRadius(self._radius)
        qconfig.themeChangedFinished.connect(self.update)

    def set_title(self, t):
        self._title = t
        self.update()

    def set_radius(self, r):
        self._radius = max(0, r)
        # CardWidget paints its own rounded background; a QSS border radius
        # neither changes that painter nor survives Fluent's stylesheet refresh.
        self.setBorderRadius(self._radius)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._title:
            p = QPainter(self)
            p.setPen(QColor("#b3b3b3" if isDarkTheme() else "#606060"))
            p.setFont(QFont(self.font().family(), 9))
            p.drawText(12, 18, self._title)
            p.end()


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

HBOX_META = WidgetMeta(
    type_name="HBoxLayout",
    display_name="水平布局",
    category=WidgetCategory.LAYOUT,
    icon="RIGHT_ARROW",
    default_width=300, default_height=80,
    min_width=60, min_height=40,
    properties=[
        PropDef("title", "标题", PropType.STRING, "水平布局"),
        PropDef("spacing", "间距", PropType.INT, 8, min_val=0, max_val=100),
    ],
)

VBOX_META = WidgetMeta(
    type_name="VBoxLayout",
    display_name="垂直布局",
    category=WidgetCategory.LAYOUT,
    icon="ARROW_DOWN",
    default_width=200, default_height=200,
    min_width=60, min_height=40,
    properties=[
        PropDef("title", "标题", PropType.STRING, "垂直布局"),
        PropDef("spacing", "间距", PropType.INT, 8, min_val=0, max_val=100),
    ],
)

FLEX_META = WidgetMeta(
    type_name="FlexLayout",
    display_name="弹性布局",
    category=WidgetCategory.LAYOUT,
    icon="LAYOUT",
    default_width=400, default_height=200,
    min_width=100, min_height=60,
    properties=[
        PropDef("title", "标题", PropType.STRING, "弹性布局"),
        PropDef("direction", "方向", PropType.ENUM, "row", options=["row", "column"]),
        PropDef("spacing", "间距", PropType.INT, 8, min_val=0, max_val=100),
    ],
)

GROUPBOX_META = WidgetMeta(
    type_name="GroupBox",
    display_name="分组框",
    category=WidgetCategory.LAYOUT,
    icon="FOLDER",
    default_width=280, default_height=180,
    min_width=80, min_height=60,
    properties=[
        PropDef("title", "标题", PropType.STRING, "分组"),
    ],
)

TAB_META = WidgetMeta(
    type_name="TabWidget",
    display_name="选项卡",
    category=WidgetCategory.LAYOUT,
    icon="TILES",
    default_width=350, default_height=250,
    min_width=150, min_height=80,
    properties=[
        PropDef("tabNames", "标签名称", PropType.TEXT, "标签1\n标签2\n标签3"),
        PropDef("currentTab", "当前标签页", PropType.INT, 0, min_val=0, max_val=9999),
        PropDef("tabLayout", "当前页布局", PropType.ENUM, "自由",
                options=["自由", "垂直", "水平", "弹性(Flex)"]),
    ],
)

SEPARATOR_META = WidgetMeta(
    type_name="Separator",
    display_name="分割线",
    category=WidgetCategory.LAYOUT,
    icon="REMOVE",
    default_width=200, default_height=2,
    min_width=20, min_height=2,
    properties=[
        PropDef("orientation", "方向", PropType.ENUM, "horizontal",
                options=["horizontal", "vertical"]),
    ],
)

CARD_META = WidgetMeta(
    type_name="CardContainer",
    display_name="卡片容器",
    category=WidgetCategory.LAYOUT,
    icon="LABEL",
    default_width=300, default_height=200,
    min_width=80, min_height=60,
    properties=[
        PropDef("title", "标题", PropType.STRING, ""),
        PropDef("layout", "布局", PropType.ENUM, "自由",
                options=["自由", "垂直", "水平"]),
        PropDef("spacing", "间距", PropType.INT, 8, min_val=0, max_val=100),
    ],
)

ALL_LAYOUT = [HBOX_META, VBOX_META, FLEX_META, GROUPBOX_META, TAB_META, SEPARATOR_META, CARD_META]


def register_layout_widgets():
    for meta in ALL_LAYOUT:
        registry.register(meta)


def create_layout_widget(type_name: str, props: dict, parent=None) -> QWidget:
    if type_name == "HBoxLayout":
        w = HBoxContainer(parent)
        w.set_title(props.get("title", "水平布局"))
        w.set_spacing(props.get("spacing", 8))
        return w
    if type_name == "VBoxLayout":
        w = VBoxContainer(parent)
        w.set_title(props.get("title", "垂直布局"))
        w.set_spacing(props.get("spacing", 8))
        return w
    if type_name == "FlexLayout":
        w = FlexContainer(parent)
        w.set_title(props.get("title", "弹性布局"))
        w.set_direction(props.get("direction", "row"))
        w.set_spacing(props.get("spacing", 8))
        return w
    if type_name == "GroupBox":
        w = GroupBoxContainer(parent)
        w.set_title(props.get("title", "分组"))
        return w
    if type_name == "TabWidget":
        w = TabContainer(parent)
        w.set_tab_names(props.get("tabNames", "标签1\n标签2"))
        w.setCurrentIndex(clamp_tab_index(props.get("currentTab", 0), w.count()))
        return w
    if type_name == "Separator":
        w = Separator(parent)
        w.set_orientation(props.get("orientation", "horizontal"))
        return w
    if type_name == "CardContainer":
        w = CardContainer(parent)
        w.set_title(props.get("title", ""))
        w.set_radius(props.get("radius", 8))
        return w
    return None


def apply_layout_property(widget, type_name: str, prop_name: str, value):
    if type_name in ("HBoxLayout", "VBoxLayout"):
        if prop_name == "title":
            widget.set_title(value)
        elif prop_name == "spacing":
            widget.set_spacing(value)
    elif type_name == "FlexLayout":
        if prop_name == "title":
            widget.set_title(value)
        elif prop_name == "direction":
            widget.set_direction(value)
        elif prop_name == "spacing":
            widget.set_spacing(value)
    elif type_name == "GroupBox":
        if prop_name == "title":
            widget.set_title(value)
    elif type_name == "TabWidget":
        if prop_name == "tabNames":
            widget.set_tab_names(value)
        elif prop_name == "currentTab":
            widget.setCurrentIndex(clamp_tab_index(value, widget.count()))
    elif type_name == "Separator":
        if prop_name == "orientation":
            widget.set_orientation(value)
    elif type_name == "CardContainer":
        if prop_name == "title":
            widget.set_title(value)
