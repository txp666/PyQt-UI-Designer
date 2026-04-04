# coding: utf-8
"""Selection and alignment helpers for the design canvas."""
from typing import List
from app.designer.canvas_item import CanvasItem
from app.designer.canvas import DesignScene


def selected_items(scene: DesignScene) -> List[CanvasItem]:
    return [i for i in scene.selectedItems() if isinstance(i, CanvasItem)]


def align_left(scene: DesignScene):
    items = selected_items(scene)
    if len(items) < 2:
        return
    target_x = min(i.pos().x() for i in items)
    for i in items:
        i.setPos(target_x, i.pos().y())
        i.notify_changed()


def align_top(scene: DesignScene):
    items = selected_items(scene)
    if len(items) < 2:
        return
    target_y = min(i.pos().y() for i in items)
    for i in items:
        i.setPos(i.pos().x(), target_y)
        i.notify_changed()


def align_right(scene: DesignScene):
    items = selected_items(scene)
    if len(items) < 2:
        return
    target_x = max(i.pos().x() + i.rect().width() for i in items)
    for i in items:
        i.setPos(target_x - i.rect().width(), i.pos().y())
        i.notify_changed()


def align_bottom(scene: DesignScene):
    items = selected_items(scene)
    if len(items) < 2:
        return
    target_y = max(i.pos().y() + i.rect().height() for i in items)
    for i in items:
        i.setPos(i.pos().x(), target_y - i.rect().height())
        i.notify_changed()


def distribute_horizontal(scene: DesignScene):
    items = selected_items(scene)
    if len(items) < 3:
        return
    items.sort(key=lambda i: i.pos().x())
    left = items[0].pos().x()
    right = items[-1].pos().x()
    spacing = (right - left) / (len(items) - 1)
    for idx, item in enumerate(items):
        item.setPos(left + idx * spacing, item.pos().y())
        item.notify_changed()


def distribute_vertical(scene: DesignScene):
    items = selected_items(scene)
    if len(items) < 3:
        return
    items.sort(key=lambda i: i.pos().y())
    top = items[0].pos().y()
    bottom = items[-1].pos().y()
    spacing = (bottom - top) / (len(items) - 1)
    for idx, item in enumerate(items):
        item.setPos(item.pos().x(), top + idx * spacing)
        item.notify_changed()
