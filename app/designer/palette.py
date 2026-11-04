# coding: utf-8
"""Widget palette — categorized drag source for the designer."""
from PyQt5.QtCore import Qt, QMimeData, QByteArray, QSize
from PyQt5.QtGui import QDrag, QPixmap, QPainter, QColor, QFont
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QListWidgetItem, QAbstractItemView, QSizePolicy
from qfluentwidgets import (
    ListWidget, ScrollArea, SimpleCardWidget, StrongBodyLabel, isDarkTheme, Theme, qconfig,
)

from app.common.icon import widget_icon
from app.core.widget_registry import registry
from app.core.signal_lifetime import SignalConnections
from app.widgets.base import WidgetCategory, WidgetMeta
from app.designer.canvas import MIME_WIDGET_TYPE


class _DraggableListWidget(ListWidget):
    """List that initiates a drag with widget-type MIME data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        # The icons are drawn for 16 px; Fusion (Linux) would scale them to 24 and blur them.
        self.setIconSize(QSize(16, 16))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

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


class _CategoryCard(SimpleCardWidget):
    """Card showing widgets in one category."""

    def __init__(self, category: WidgetCategory, widgets: list, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

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
            item.setToolTip(meta.type_name)
            icon = widget_icon(meta.icon)
            if icon:
                item.setIcon(icon.icon(theme))
            self._list.addItem(item)

        # Every row shown: the list never scrolls, the palette does.
        self._list.ensurePolished()  # the Fluent QSS sets the row height and the list's margins
        margins = self._list.contentsMargins()
        rows = sum(self._list.sizeHintForRow(row) for row in range(self._list.count()))
        self._list.setFixedHeight(rows + margins.top() + margins.bottom())
        layout.addWidget(self._list)

        self.setFixedHeight(layout.sizeHint().height())


class WidgetPalette(QWidget):
    """Left panel: categorized palette of draggable widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("widgetPalette")
        self.setMinimumWidth(200)
        self.setMaximumWidth(260)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = ScrollArea()
        self._scroll.setWidgetResizable(True)
        # Before the container is in it: afterwards this would also give every card and list a QSS background.
        self._scroll.enableTransparentBackground()

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignTop)

        self._scroll.setWidget(self._container)
        self._container.setAutoFillBackground(False)  # setWidget turned it on: the panel shows through
        outer.addWidget(self._scroll)
        self._external_connections = SignalConnections(self)
        self._external_connections.connect(
            qconfig.themeChangedFinished, self.refresh_icons)

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
                    icon = widget_icon(meta.icon)
                    if icon:
                        item.setIcon(icon.icon(theme))
