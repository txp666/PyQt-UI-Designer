# coding: utf-8
"""Widget palette — categorized drag source for the designer."""
from PyQt5.QtCore import Qt, QMimeData, QByteArray, QSize
from PyQt5.QtGui import QDrag, QPixmap, QPainter, QColor, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QAbstractItemView, QHBoxLayout, QFrame, QSizePolicy,
)
from PyQt5.QtWidgets import QScrollArea
from qfluentwidgets import (
    StrongBodyLabel, FluentIcon as FIF, isDarkTheme, Theme, getIconColor,
)

from app.core.widget_registry import registry
from app.widgets.base import WidgetCategory, WidgetMeta
from app.designer.canvas import MIME_WIDGET_TYPE

_ICON_MAP = {
    # basic
    "SEND": FIF.SEND, "FONT": FIF.FONT, "EDIT": FIF.EDIT,
    "MENU": FIF.MENU, "POWER_BUTTON": FIF.POWER_BUTTON,
    "SCROLL": FIF.SCROLL, "SETTING": FIF.SETTING,
    # layout
    "RIGHT_ARROW": FIF.RIGHT_ARROW, "ARROW_DOWN": FIF.ARROW_DOWN,
    "LAYOUT": FIF.LAYOUT, "FOLDER": FIF.FOLDER, "TILES": FIF.TILES,
    "REMOVE": FIF.REMOVE,
    # display
    "CHECKBOX": FIF.CHECKBOX, "CALORIES": FIF.CALORIES,
    "SPEED_HIGH": FIF.SPEED_HIGH, "SPEED_MEDIUM": FIF.SPEED_MEDIUM,
    "SPEED_OFF": FIF.SPEED_OFF, "PHOTO": FIF.PHOTO,
    # chart
    "HISTORY": FIF.HISTORY, "ALBUM": FIF.ALBUM,
    # comm
    "COMMAND_PROMPT": FIF.COMMAND_PROMPT, "VIEW": FIF.VIEW,
    # composite
    "CONNECT": FIF.CONNECT, "LABEL": FIF.LABEL,
    "IOT": FIF.IOT, "DEVELOPER_TOOLS": FIF.DEVELOPER_TOOLS,
    "DOWNLOAD": FIF.DOWNLOAD,
}


class _DraggableListWidget(QListWidget):
    """List that initiates a drag with widget-type MIME data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSpacing(2)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-radius: 6px;
            }
            QListWidget::item:hover {
                background: rgba(128, 128, 128, 0.1);
            }
            QListWidget::item:selected {
                background: rgba(0, 120, 212, 0.15);
            }
        """)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
        type_name = item.data(Qt.UserRole)
        if not type_name:
            return

        mime = QMimeData()
        mime.setData(MIME_WIDGET_TYPE, QByteArray(type_name.encode("utf-8")))

        pixmap = QPixmap(140, 32)
        if isDarkTheme():
            pixmap.fill(QColor(0, 120, 212, 60))
            text_color = QColor(200, 220, 255)
        else:
            pixmap.fill(QColor(0, 120, 212, 40))
            text_color = QColor(0, 120, 212)
        painter = QPainter(pixmap)
        painter.setPen(text_color)
        painter.setFont(QFont(self.font().family(), 10))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, item.text())
        painter.end()

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(pixmap.rect().center())
        drag.exec_(Qt.CopyAction)


class _CategoryCard(QFrame):
    """Card showing widgets in one category."""

    def __init__(self, category: WidgetCategory, widgets: list, parent=None):
        super().__init__(parent)
        self.setObjectName("categoryCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("""
            #categoryCard {
                background: rgba(128, 128, 128, 0.06);
                border: 1px solid rgba(128, 128, 128, 0.1);
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        header = StrongBodyLabel(category.value)
        layout.addWidget(header)

        self._list = _DraggableListWidget()
        theme = Theme.DARK if isDarkTheme() else Theme.LIGHT
        for meta in widgets:
            item = QListWidgetItem(meta.display_name)
            item.setData(Qt.UserRole, meta.type_name)
            icon = _ICON_MAP.get(meta.icon)
            if icon:
                item.setIcon(icon.icon(theme))
            self._list.addItem(item)

        row_height = 36
        list_h = len(widgets) * row_height + 8
        self._list.setFixedHeight(list_h)
        layout.addWidget(self._list)

        total_h = list_h + 28 + 24  # header ~28px + margins
        self.setFixedHeight(total_h)


class WidgetPalette(QWidget):
    """Left panel: categorized palette of draggable widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("widgetPalette")
        self.setMinimumWidth(200)
        self.setMaximumWidth(260)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)

        self._container = QWidget()
        self._container.setObjectName("paletteContainer")
        self._layout = QVBoxLayout(self._container)
        self._scroll.setStyleSheet(
            "QScrollArea, #paletteContainer { background: transparent; border: none; }"
        )
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignTop)

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll)

    def populate(self):
        self._cards = []
        for cat in registry.categories():
            widgets = registry.by_category(cat)
            if widgets:
                card = _CategoryCard(cat, widgets, self._container)
                self._layout.addWidget(card)
                self._cards.append(card)

    def refresh_icons(self):
        theme = Theme.DARK if isDarkTheme() else Theme.LIGHT
        for card in getattr(self, "_cards", []):
            lst = card._list
            for i in range(lst.count()):
                item = lst.item(i)
                type_name = item.data(Qt.UserRole)
                meta = registry.get(type_name)
                if meta:
                    icon = _ICON_MAP.get(meta.icon)
                    if icon:
                        item.setIcon(icon.icon(theme))
