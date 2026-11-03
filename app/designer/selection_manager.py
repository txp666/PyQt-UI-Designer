# coding: utf-8
"""Selection and alignment helpers for the design canvas."""
from typing import List
from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QGraphicsItem
from app.designer.canvas_item import CanvasItem
from app.designer.canvas import DesignScene


def selected_items(scene: DesignScene) -> List[CanvasItem]:
    """Only move independent free items; managed children belong to their layout."""
    selected = {i for i in scene.selectedItems() if isinstance(i, CanvasItem)}
    items = []
    for item in selected:
        if not item.flags() & QGraphicsItem.ItemIsMovable:
            continue
        parent = item._container_parent
        while parent is not None and parent not in selected:
            parent = parent._container_parent
        if parent is None:
            items.append(item)
    return items


def _move_by_scene_delta(item: CanvasItem, delta: QPointF):
    position = item.scenePos() + delta
    parent = item.parentItem()
    item.setPos(parent.mapFromScene(position) if parent else position)
    item.notify_changed()


def _align(scene: DesignScene, edge: str):
    items = selected_items(scene)
    if len(items) < 2:
        return
    coordinates = [(item, getattr(item.mapRectToScene(item.rect()), edge)())
                   for item in items]
    values = [coordinate for _, coordinate in coordinates]
    target = max(values) if edge in ("right", "bottom") else min(values)
    for item, coordinate in coordinates:
        delta = target - coordinate
        _move_by_scene_delta(item, QPointF(delta, 0) if edge in ("left", "right")
                            else QPointF(0, delta))


def align_left(scene: DesignScene):
    _align(scene, "left")


def align_top(scene: DesignScene):
    _align(scene, "top")


def align_right(scene: DesignScene):
    _align(scene, "right")


def align_bottom(scene: DesignScene):
    _align(scene, "bottom")


def _align_center(scene: DesignScene, horizontal: bool):
    """Centre the selection on the middle of its bounding box, across or down."""
    items = selected_items(scene)
    if len(items) < 2:
        return
    rects = [(item, item.mapRectToScene(item.rect())) for item in items]
    if horizontal:
        middle = (min(r.left() for _, r in rects) + max(r.right() for _, r in rects)) / 2
        for item, rect in rects:
            _move_by_scene_delta(item, QPointF(middle - rect.center().x(), 0))
    else:
        middle = (min(r.top() for _, r in rects) + max(r.bottom() for _, r in rects)) / 2
        for item, rect in rects:
            _move_by_scene_delta(item, QPointF(0, middle - rect.center().y()))


def align_horizontal_center(scene: DesignScene):
    _align_center(scene, True)


def align_vertical_center(scene: DesignScene):
    _align_center(scene, False)


def _distribute(scene: DesignScene, horizontal: bool):
    """Equal gaps between the selected widgets, the outermost two staying where they are."""
    items = selected_items(scene)
    if len(items) < 3:
        return
    rects = sorted(((item, item.mapRectToScene(item.rect())) for item in items),
                   key=lambda entry: ((entry[1].left() if horizontal else entry[1].top()), entry[0].widget_id))
    start = min(r.left() if horizontal else r.top() for _, r in rects)
    stop = max(r.right() if horizontal else r.bottom() for _, r in rects)
    sizes = sum(r.width() if horizontal else r.height() for _, r in rects)
    gap = (stop - start - sizes) / (len(rects) - 1)
    cursor = start
    for item, rect in rects:
        delta = cursor - (rect.left() if horizontal else rect.top())
        _move_by_scene_delta(item, QPointF(delta, 0) if horizontal else QPointF(0, delta))
        cursor += (rect.width() if horizontal else rect.height()) + gap


def distribute_horizontal(scene: DesignScene):
    _distribute(scene, True)


def distribute_vertical(scene: DesignScene):
    _distribute(scene, False)
