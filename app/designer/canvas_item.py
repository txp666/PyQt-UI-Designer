# coding: utf-8
"""CanvasItem wraps a real QWidget inside QGraphicsScene with resize handles."""
import uuid
from typing import Dict, Any, Optional, List

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPen, QColor, QBrush, QPainter
from PyQt5.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, QGraphicsProxyWidget,
    QWidget, QStyleOptionGraphicsItem,
)

from app.widgets.basic import create_widget, apply_property
from app.core.widget_registry import registry

HANDLE_SIZE = 8
HANDLE_HALF = HANDLE_SIZE / 2
MIN_SIZE = 30

LAYOUT_TYPES = {"HBoxLayout", "VBoxLayout", "FlexLayout", "GroupBox", "TabWidget", "CardContainer"}


class ResizeHandle(QGraphicsRectItem):
    """A small square handle for resizing the parent CanvasItem."""

    def __init__(self, direction: str, parent: "CanvasItem"):
        super().__init__(-HANDLE_HALF, -HANDLE_HALF, HANDLE_SIZE, HANDLE_SIZE, parent)
        self.direction = direction
        self._parent_item = parent
        self.setBrush(QBrush(QColor(0, 120, 212)))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
        self.setCursor(self._cursor_for_direction(direction))
        self.setAcceptHoverEvents(True)
        self.setZValue(100)

    @staticmethod
    def _cursor_for_direction(d: str):
        cursors = {
            "tl": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
            "bl": Qt.SizeBDiagCursor, "br": Qt.SizeFDiagCursor,
            "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
            "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
        }
        return cursors.get(d, Qt.ArrowCursor)

    def mousePressEvent(self, event):
        self._start_pos = event.scenePos()
        self._start_rect = self._parent_item.rect()
        self._start_item_pos = self._parent_item.pos()
        event.accept()

    def mouseMoveEvent(self, event):
        delta = event.scenePos() - self._start_pos
        r = QRectF(self._start_rect)
        pos = QPointF(self._start_item_pos)
        d = self.direction
        meta = registry.get(self._parent_item.type_name)
        mw = meta.min_width if meta else MIN_SIZE
        mh = meta.min_height if meta else MIN_SIZE

        if "r" in d:
            r.setWidth(max(mw, r.width() + delta.x()))
        if "b" in d:
            r.setHeight(max(mh, r.height() + delta.y()))
        if "l" in d:
            new_w = max(mw, r.width() - delta.x())
            pos.setX(pos.x() + (r.width() - new_w))
            r.setWidth(new_w)
        if "t" in d:
            new_h = max(mh, r.height() - delta.y())
            pos.setY(pos.y() + (r.height() - new_h))
            r.setHeight(new_h)

        self._parent_item.setPos(pos)
        self._parent_item.set_rect(r)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._parent_item.snap_to_grid()
        self._parent_item.notify_changed()
        event.accept()


class CanvasItem(QGraphicsRectItem):
    """Wraps a designable widget on the canvas with selection handles."""

    def __init__(self, type_name: str, properties: Dict[str, Any],
                 widget_id: str = None, parent=None):
        super().__init__(parent)
        self.widget_id = widget_id or f"{type_name}_{uuid.uuid4().hex[:6]}"
        self.type_name = type_name
        self.properties = dict(properties)
        self.binding: Optional[Dict] = None
        self._grid_size = 10

        # Container support
        self._container_children: List['CanvasItem'] = []
        self._container_parent: Optional['CanvasItem'] = None
        self.tab_index: int = 0  # which tab page this child belongs to

        meta = registry.get(type_name)
        w = meta.default_width if meta else 120
        h = meta.default_height if meta else 40

        self.setRect(0, 0, w, h)
        self.setPen(QPen(Qt.transparent))
        self.setBrush(Qt.transparent)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

        self._proxy = QGraphicsProxyWidget(self)
        self._inner_widget = create_widget(type_name, properties)
        self._inner_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._proxy.setWidget(self._inner_widget)
        self._proxy.setPos(0, 0)
        self._proxy.setAcceptedMouseButtons(Qt.NoButton)
        self._proxy.setAcceptHoverEvents(False)
        self._proxy.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self._proxy.setFlag(QGraphicsItem.ItemIsMovable, False)
        self._sync_proxy_size()

        self._handles = []
        for d in ("tl", "t", "tr", "r", "br", "b", "bl", "l"):
            self._handles.append(ResizeHandle(d, self))
        self._update_handle_positions()
        self._set_handles_visible(False)

        self._scene_ref = None
        self._drop_highlighted = False

    # ------------------------------------------------------------------
    # Container helpers
    # ------------------------------------------------------------------

    def is_container(self) -> bool:
        return self.type_name in LAYOUT_TYPES

    def add_child(self, child: 'CanvasItem'):
        """Adopt *child* into this layout container."""
        if child._container_parent is self:
            return
        if child._container_parent:
            child._container_parent.remove_child(child)

        child._container_parent = self
        child.setParentItem(self)
        if child not in self._container_children:
            self._container_children.append(child)
        if self.type_name == "TabWidget":
            child.tab_index = self.properties.get("currentTab", 0)
            mode = self.properties.get(
                f"_tabLayout_{child.tab_index}", "自由")
            child.setFlag(QGraphicsItem.ItemIsMovable, mode == "自由")
        else:
            child.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.relayout_children()

    def remove_child(self, child: 'CanvasItem'):
        """Detach *child* from this container."""
        if child in self._container_children:
            self._container_children.remove(child)
        child._container_parent = None
        child.setParentItem(None)
        child.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.relayout_children()

    def detach_from_parent(self):
        """Remove this item from its parent container, keeping it in the scene."""
        if self._container_parent:
            scene_pos = self.scenePos()
            self._container_parent.remove_child(self)
            self.setPos(scene_pos)

    def relayout_children(self):
        """Reposition children according to this container's layout type."""
        if not self._container_children:
            return
        r = self.rect()
        spacing = self.properties.get("spacing", 8)
        pad = 8
        title_h = 22

        if self.type_name == "HBoxLayout":
            x = pad
            avail_h = r.height() - title_h - pad
            for ch in self._container_children:
                ch.setPos(x, title_h)
                x += ch.rect().width() + spacing

        elif self.type_name in ("VBoxLayout", "GroupBox"):
            y0 = title_h if self.type_name == "VBoxLayout" else 28
            y = y0
            avail_w = r.width() - 2 * pad
            for ch in self._container_children:
                ch.setPos(pad, y)
                cr = ch.rect()
                if cr.width() != avail_w:
                    ch.set_rect(QRectF(0, 0, avail_w, cr.height()))
                y += ch.rect().height() + spacing

        elif self.type_name == "FlexLayout":
            direction = self.properties.get("direction", "row")
            if direction == "row":
                x, y, row_h = pad, title_h, 0
                for ch in self._container_children:
                    cw = ch.rect().width()
                    ch_h = ch.rect().height()
                    if x + cw > r.width() - pad and x > pad:
                        x = pad
                        y += row_h + spacing
                        row_h = 0
                    ch.setPos(x, y)
                    x += cw + spacing
                    row_h = max(row_h, ch_h)
            else:
                x, y, col_w = pad, title_h, 0
                for ch in self._container_children:
                    cw = ch.rect().width()
                    ch_h = ch.rect().height()
                    if y + ch_h > r.height() - pad and y > title_h:
                        y = title_h
                        x += col_w + spacing
                        col_w = 0
                    ch.setPos(x, y)
                    y += ch_h + spacing
                    col_w = max(col_w, cw)

        elif self.type_name == "TabWidget":
            current_tab = self.properties.get("currentTab", 0)
            mode = self.properties.get(f"_tabLayout_{current_tab}", "自由")

            tab_h = 32
            avail_w = r.width() - 2 * pad

            visible = []
            for ch in self._container_children:
                if ch.tab_index != current_tab:
                    ch.setVisible(False)
                else:
                    ch.setVisible(True)
                    visible.append(ch)

            is_free = (mode == "自由")
            for ch in visible:
                ch.setFlag(QGraphicsItem.ItemIsMovable, is_free)

            if mode == "自由":
                pass  # keep children at their current positions
            elif mode == "水平":
                x = pad
                for ch in visible:
                    ch.setPos(x, tab_h)
                    x += ch.rect().width() + spacing
            elif mode == "弹性(Flex)":
                x, row_h = pad, 0
                y = tab_h
                for ch in visible:
                    cw = ch.rect().width()
                    ch_h = ch.rect().height()
                    if x + cw > r.width() - pad and x > pad:
                        x = pad
                        y += row_h + spacing
                        row_h = 0
                    ch.setPos(x, y)
                    x += cw + spacing
                    row_h = max(row_h, ch_h)
            else:  # 垂直
                y = tab_h
                for ch in visible:
                    ch.setPos(pad, y)
                    cr = ch.rect()
                    if cr.width() != avail_w:
                        ch.set_rect(QRectF(0, 0, avail_w, cr.height()))
                    y += ch.rect().height() + spacing

        elif self.type_name == "CardContainer":
            mode = self.properties.get("layout", "自由")
            is_free = (mode == "自由")
            for ch in self._container_children:
                ch.setFlag(QGraphicsItem.ItemIsMovable, is_free)

            if mode == "水平":
                x = pad
                for ch in self._container_children:
                    ch.setPos(x, pad)
                    x += ch.rect().width() + spacing
            elif mode == "垂直":
                y = pad
                avail_w = r.width() - 2 * pad
                for ch in self._container_children:
                    ch.setPos(pad, y)
                    cr = ch.rect()
                    if cr.width() != avail_w:
                        ch.set_rect(QRectF(0, 0, avail_w, cr.height()))
                    y += ch.rect().height() + spacing

    def collect_all_ids(self) -> List[str]:
        """Recursively collect this item's ID and all children's IDs."""
        ids = [self.widget_id]
        for ch in self._container_children:
            ids.extend(ch.collect_all_ids())
        return ids

    # ------------------------------------------------------------------
    # Visual feedback for drag-over
    # ------------------------------------------------------------------

    def set_drop_highlight(self, show: bool):
        if show and self.is_container():
            self._drop_highlighted = True
            self.setPen(QPen(QColor(0, 120, 212, 180), 2, Qt.DashLine))
        else:
            self._drop_highlighted = False
            self.setPen(QPen(Qt.transparent))
        self.update()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def set_scene_ref(self, scene):
        self._scene_ref = scene

    def set_grid_size(self, size: int):
        self._grid_size = size

    def set_rect(self, rect: QRectF):
        self.setRect(rect)
        self._sync_proxy_size()
        self._update_handle_positions()
        if self._container_children:
            self.relayout_children()

    def _sync_proxy_size(self):
        r = self.rect()
        w, h = int(r.width()), int(r.height())
        self._inner_widget.setFixedSize(w, h)
        self._proxy.resize(w, h)

    def _update_handle_positions(self):
        r = self.rect()
        positions = {
            "tl": r.topLeft(), "t": QPointF(r.center().x(), r.top()),
            "tr": r.topRight(), "r": QPointF(r.right(), r.center().y()),
            "br": r.bottomRight(), "b": QPointF(r.center().x(), r.bottom()),
            "bl": r.bottomLeft(), "l": QPointF(r.left(), r.center().y()),
        }
        for h in self._handles:
            p = positions.get(h.direction)
            if p:
                h.setPos(p)

    def _set_handles_visible(self, visible: bool):
        for h in self._handles:
            h.setVisible(visible)

    def set_property(self, name: str, value: Any):
        self.properties[name] = value
        if self.type_name == "TabWidget" and name == "tabLayout":
            ct = self.properties.get("currentTab", 0)
            self.properties[f"_tabLayout_{ct}"] = value
            self.relayout_children()
            return
        if self.type_name == "RealtimeChart":
            from app.widgets.chart import _CURVE_FIELD_MAP
            if name in _CURVE_FIELD_MAP:
                ci = int(self.properties.get("currentCurve", 0))
                self.properties[f"_curve_{ci}_{_CURVE_FIELD_MAP[name]}"] = value
            if name in _CURVE_FIELD_MAP or name == "curveCount":
                if hasattr(self._inner_widget, "load_from_props"):
                    self._inner_widget.load_from_props(self.properties)
                return

        layout = self._inner_widget.layout()
        old_hint_h = layout.sizeHint().height() if layout else -1

        apply_property(self._inner_widget, self.type_name, name, value)

        if layout:
            layout.activate()
            new_hint_h = layout.sizeHint().height()
            if old_hint_h > 0 and new_hint_h > 0 and abs(new_hint_h - old_hint_h) > 5:
                meta = registry.get(self.type_name)
                min_h = meta.min_height if meta else MIN_SIZE
                r = self.rect()
                self.set_rect(QRectF(0, 0, r.width(), max(min_h, new_hint_h)))

        if self.is_container() and name in ("spacing", "direction", "currentTab", "layout"):
            self.relayout_children()

    def snap_to_grid(self):
        if self._grid_size <= 1 or self._container_parent:
            return
        p = self.pos()
        g = self._grid_size
        x = round(p.x() / g) * g
        y = round(p.y() / g) * g
        self.setPos(x, y)

    def notify_changed(self):
        if self._scene_ref and hasattr(self._scene_ref, "item_changed"):
            self._scene_ref.item_changed(self)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._set_handles_visible(bool(value))
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.snap_to_grid()

        # If this free item was dropped over a layout container, adopt it
        if not self._container_parent and not self.is_container():
            scene = self.scene()
            if scene:
                center = QPointF(
                    self.scenePos().x() + self.rect().width() / 2,
                    self.scenePos().y() + self.rect().height() / 2,
                )
                for it in scene.items(center):
                    if (isinstance(it, CanvasItem) and it is not self
                            and it.is_container()
                            and not isinstance(it, ResizeHandle)):
                        it.add_child(self)
                        break

        self.notify_changed()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None):
        if self._drop_highlighted:
            return  # pen already set via set_drop_highlight → QGraphicsRectItem draws it
        if self.isSelected():
            pen = QPen(QColor(0, 120, 212), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(self.rect().adjusted(-1, -1, 1, 1))

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        r = self.rect()
        p = self.pos()
        data = {
            "id": self.widget_id,
            "type": self.type_name,
            "geometry": {
                "x": p.x(), "y": p.y(),
                "w": r.width(), "h": r.height(),
            },
            "properties": dict(self.properties),
            "binding": self.binding,
        }
        if self.tab_index:
            data["tabIndex"] = self.tab_index
        if self._container_children:
            data["children"] = [c.to_dict() for c in self._container_children]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CanvasItem":
        props = data.get("properties", {})
        item = cls(data["type"], props, widget_id=data.get("id"))
        geo = data.get("geometry", {})
        item.setPos(geo.get("x", 0), geo.get("y", 0))
        item.set_rect(QRectF(0, 0, geo.get("w", 120), geo.get("h", 40)))
        item.binding = data.get("binding")
        item.tab_index = data.get("tabIndex", 0)
        for child_data in data.get("children", []):
            child = cls.from_dict(child_data)
            saved_tab = child_data.get("tabIndex", 0)
            item.add_child(child)
            child.tab_index = saved_tab  # restore after add_child
        if item.type_name == "TabWidget":
            item.relayout_children()
        return item
