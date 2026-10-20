"""Preserve the designer's tab-relative coordinates in real Qt tab pages."""
from PyQt5.QtCore import QObject, QEvent, QPoint, QRect, QTimer
from PyQt5 import sip


class TabChildGeometry(QObject):
    def __init__(self, tabs):
        super().__init__(tabs)
        self.tabs = tabs
        self._children = {}
        self._pending = False
        self._applying = False
        tabs.installEventFilter(self)
        tabs.currentChanged.connect(self.schedule)

    def register(self, child, geometry):
        self._children[child] = QRect(*geometry)
        page = child.parentWidget()
        page.installEventFilter(self)
        page.parentWidget().installEventFilter(self)
        self.apply()
        self.schedule()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show,
                            QEvent.LayoutRequest, QEvent.StyleChange, QEvent.FontChange):
            self.schedule()
        return False

    def schedule(self, *_):
        if not self._pending and not self._applying:
            self._pending = True
            QTimer.singleShot(0, self.apply)

    def apply(self):
        self._pending = False
        if sip.isdeleted(self.tabs) or self._applying:
            return
        self._applying = True
        try:
            for child, rect in list(self._children.items()):
                if sip.isdeleted(child):
                    del self._children[child]
                    continue
                page = child.parentWidget()
                # The page may be laid out lazily on its first activation.
                # Reapply after its move/show events, without changing saved coordinates.
                origin = page.mapTo(self.tabs, QPoint())
                child.setGeometry(rect.translated(-origin))
        finally:
            self._applying = False


def place_tab_child(tabs, child, x, y, width, height):
    controller = getattr(tabs, "_designer_child_geometry", None)
    if controller is None:
        controller = TabChildGeometry(tabs)
        tabs._designer_child_geometry = controller
    controller.register(child, (x, y, width, height))
