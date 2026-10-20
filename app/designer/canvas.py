# coding: utf-8
"""Design canvas based on QGraphicsScene/View with grid, drag-drop, selection."""
import json
import sys
from typing import Optional, List, Dict

from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QPen, QColor, QPainter, QBrush
from PyQt5.QtWidgets import (
    QGraphicsScene, QGraphicsView, QGraphicsItem, QWidget,
)
from qfluentwidgets import isDarkTheme

from app.common.config import cfg
from app.common.signal_bus import signalBus
from app.core.widget_registry import registry
from app.designer.canvas_item import CanvasItem

MIME_WIDGET_TYPE = "application/x-widget-type"


class DesignScene(QGraphicsScene):
    """Scene that holds all CanvasItems and draws a grid background."""

    itemSelectionUpdated = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid_size = cfg.get(cfg.gridSize)
        self._show_grid = cfg.get(cfg.showGrid)
        w = cfg.get(cfg.canvasWidth)
        h = cfg.get(cfg.canvasHeight)
        self.setSceneRect(0, 0, w, h)

    @property
    def grid_size(self) -> int:
        return self._grid_size

    def set_grid_size(self, size: int):
        self._grid_size = max(1, size)
        self.update()

    def set_show_grid(self, show: bool):
        self._show_grid = show
        self.update()

    def set_canvas_size(self, w: int, h: int):
        self.setSceneRect(0, 0, w, h)
        self.update()

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        dark = isDarkTheme()

        bg_color = QColor(40, 40, 40) if dark else QColor(250, 250, 250)
        painter.fillRect(rect, QBrush(bg_color))

        if not self._show_grid or self._grid_size <= 1:
            return

        g = self._grid_size
        if dark:
            pen_light = QPen(QColor(55, 55, 55), 0.5)
            pen_major = QPen(QColor(70, 70, 70), 1.0)
        else:
            pen_light = QPen(QColor(220, 220, 220), 0.5)
            pen_major = QPen(QColor(200, 200, 200), 1.0)

        sr = self.sceneRect()
        left = int(sr.left()) - (int(sr.left()) % g)
        top = int(sr.top()) - (int(sr.top()) % g)

        lines_light = []
        lines_major = []
        x = left
        while x <= sr.right():
            if x % (g * 5) == 0:
                lines_major.append((x, sr.top(), x, sr.bottom()))
            else:
                lines_light.append((x, sr.top(), x, sr.bottom()))
            x += g
        y = top
        while y <= sr.bottom():
            if y % (g * 5) == 0:
                lines_major.append((sr.left(), y, sr.right(), y))
            else:
                lines_light.append((sr.left(), y, sr.right(), y))
            y += g

        painter.setPen(pen_light)
        for lx, ly, lx2, ly2 in lines_light:
            painter.drawLine(int(lx), int(ly), int(lx2), int(ly2))
        painter.setPen(pen_major)
        for lx, ly, lx2, ly2 in lines_major:
            painter.drawLine(int(lx), int(ly), int(lx2), int(ly2))

        border_color = QColor(80, 80, 80) if dark else QColor(180, 180, 180)
        border_pen = QPen(border_color, 2)
        painter.setPen(border_pen)
        painter.drawRect(sr)

    # ------------------------------------------------------------------
    # Item management
    # ------------------------------------------------------------------

    def add_canvas_item(self, item: CanvasItem):
        item.set_scene_ref(self)
        item.set_grid_size(self._grid_size)
        self.addItem(item)
        signalBus.widgetAdded.emit(item.widget_id)
        self._setup_children(item)
        signalBus.canvasChanged.emit()

    def _setup_children(self, item: CanvasItem):
        for child in item._container_children:
            child.set_scene_ref(self)
            child.set_grid_size(self._grid_size)
            signalBus.widgetAdded.emit(child.widget_id)
            self._setup_children(child)

    def remove_canvas_item(self, item: CanvasItem):
        if item._container_parent:
            item._container_parent.remove_child(item)
        all_ids = item.collect_all_ids()
        self.removeItem(item)
        for wid in all_ids:
            signalBus.widgetRemoved.emit(wid)
        signalBus.canvasChanged.emit()

    def get_item_by_id(self, widget_id: str) -> Optional[CanvasItem]:
        for it in self.items():
            if isinstance(it, CanvasItem) and it.widget_id == widget_id:
                return it
        return None

    def all_canvas_items(self) -> List[CanvasItem]:
        """Return ALL CanvasItems including children (for selection, etc.)."""
        return [it for it in self.items() if isinstance(it, CanvasItem)]

    def top_level_canvas_items(self) -> List[CanvasItem]:
        """Return only top-level CanvasItems (for serialization)."""
        return [it for it in self.items()
                if isinstance(it, CanvasItem) and it._container_parent is None]

    def item_changed(self, item: CanvasItem):
        signalBus.canvasChanged.emit()

    def clear_all(self):
        for it in self.top_level_canvas_items():
            self.removeItem(it)
        signalBus.canvasChanged.emit()

    def refresh_all_widgets(self):
        """Force all proxy widgets to repaint (e.g. after theme change)."""
        for it in self.all_canvas_items():
            w = it._inner_widget
            if w:
                w.style().unpolish(w)
                w.style().polish(w)
                w.update()
                for child in w.findChildren(QWidget):
                    child.style().unpolish(child)
                    child.style().polish(child)
                    child.update()
        self.update()


class DesignView(QGraphicsView):
    """View providing zoom, pan, and drag-drop acceptance."""

    def __init__(self, scene: DesignScene, parent=None):
        super().__init__(scene, parent)
        self._scene = scene
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setAcceptDrops(True)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._zoom = 1.0
        self._apply_view_style()

        self.scene().selectionChanged.connect(self._on_selection_changed)

    def _apply_view_style(self):
        dark = isDarkTheme()
        bg = "#2b2b2b" if dark else "#f0f0f0"
        self.setStyleSheet(f"QGraphicsView {{ background: {bg}; border: none; }}")

    def _on_selection_changed(self):
        items = self.scene().selectedItems()
        canvas_items = [i for i in items if isinstance(i, CanvasItem)]
        if len(canvas_items) == 1:
            signalBus.widgetSelected.emit(canvas_items[0].widget_id)
        else:
            signalBus.widgetDeselected.emit()

    def _find_container_at(self, scene_pos: QPointF) -> Optional[CanvasItem]:
        """Find a layout container CanvasItem at scene_pos."""
        for it in self._scene.items(scene_pos):
            if isinstance(it, CanvasItem) and it.is_container():
                return it
        return None

    def _clear_all_highlights(self):
        for it in self._scene.all_canvas_items():
            if it.is_container():
                it.set_drop_highlight(False)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def wheelEvent(self, event):
        # On Mac a two-finger gesture pans; Command + scroll zooms.
        if sys.platform == "darwin" and not event.modifiers() & Qt.ControlModifier:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return
        factor = 1.15 ** (delta / 120)
        new_zoom = max(0.2, min(5.0, self._zoom * factor))
        self.scale(new_zoom / self._zoom, new_zoom / self._zoom)
        self._zoom = new_zoom
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_WIDGET_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_WIDGET_TYPE):
            event.acceptProposedAction()
            scene_pos = self.mapToScene(event.pos())
            # Highlight layout container under cursor
            for it in self._scene.all_canvas_items():
                if it.is_container():
                    hit = it.sceneBoundingRect().contains(scene_pos)
                    it.set_drop_highlight(hit)
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._clear_all_highlights()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME_WIDGET_TYPE):
            self._clear_all_highlights()

            type_name = bytes(event.mimeData().data(MIME_WIDGET_TYPE)).decode("utf-8")
            meta = registry.get(type_name)
            if meta:
                props = meta.get_default_props()
                item = CanvasItem(type_name, props)
                scene_pos = self.mapToScene(event.pos())

                container = self._find_container_at(scene_pos)
                if container and not item.is_container():
                    grid = self._scene.grid_size
                    x = round(scene_pos.x() / grid) * grid
                    y = round(scene_pos.y() / grid) * grid
                    item.setPos(x, y)
                    self._scene.add_canvas_item(item)
                    container.add_child(item)
                else:
                    grid = self._scene.grid_size
                    x = round(scene_pos.x() / grid) * grid
                    y = round(scene_pos.y() / grid) * grid
                    item.setPos(x, y)
                    self._scene.add_canvas_item(item)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Delete
                or (sys.platform == "darwin" and event.key() == Qt.Key_Backspace)):
            for item in self.scene().selectedItems():
                if isinstance(item, CanvasItem):
                    self._scene.remove_canvas_item(item)
            event.accept()
        else:
            super().keyPressEvent(event)
