# coding: utf-8
"""Copy and paste of designer widgets, in the clipboard format FluentHMI Studio shares."""
import copy
import json
import uuid
from pathlib import Path

from PyQt5.QtCore import Qt

from app.core.project import PROJECT_VERSION, ProjectData, resolved_asset_path
from app.designer.canvas_item import CanvasItem

CLIPBOARD_MIME = "application/x-fluenthmi-widgets"


def copied_items(scene):
    """The selected widgets to copy, back to front: a container brings its children, so a selected child of
    a selected container is not copied again."""
    selected = {it for it in scene.selectedItems() if isinstance(it, CanvasItem)}

    def has_selected_container(item):
        parent = item._container_parent
        while parent is not None and parent not in selected:
            parent = parent._container_parent
        return parent is not None

    return [it for it in scene.items(Qt.AscendingOrder)
            if it in selected and not has_selected_container(it)]


def _absolute_images(data, base_dir):
    props = data.get("properties", {})
    if data.get("type") == "ImageDisplay" and props.get("imagePath"):
        props["imagePath"] = resolved_asset_path(props["imagePath"], base_dir)
    for child in data.get("children", []):
        _absolute_images(child, base_dir)


def clipboard_text(items, base_dir) -> str:
    """The JSON that copying ``items`` puts on the clipboard: top-level widgets at canvas positions and
    without a tab page, image paths absolute so another project can use them."""
    widgets = []
    for item in items:
        data = copy.deepcopy(item.to_dict())
        position = item.scenePos()
        data["geometry"]["x"], data["geometry"]["y"] = position.x(), position.y()
        data.pop("tabIndex", None)
        _absolute_images(data, base_dir)
        widgets.append(data)
    return json.dumps({"version": PROJECT_VERSION, "widgets": widgets}, ensure_ascii=False, indent=2)


def _widget_list(text):
    """The widgets in clipboard text: the clipboard object, a bare array of widgets or one widget."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("widgets"), list):
        return data["widgets"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "type" in data:
        return [data]
    return None


def pasted_widgets(mime, serial):
    """(text, widgets) from the clipboard, checked as opening a project checks them; None when there is
    nothing to paste. ``serial`` is the project's frame format, which a link card's own is checked against."""
    candidates = []
    if mime is not None and mime.hasFormat(CLIPBOARD_MIME):
        candidates.append(bytes(mime.data(CLIPBOARD_MIME)).decode("utf-8", "replace"))
    if mime is not None and mime.hasText():
        candidates.append(mime.text())
    for text in candidates:
        widgets = _widget_list(text)
        if not widgets:
            continue
        try:
            ProjectData.validate({"serial": serial, "widgets": widgets})
        except ValueError:
            continue
        return text, copy.deepcopy(widgets)
    return None


def assign_ids(widgets, taken):
    """Keep each pasted widget's id unless the project has it already, else give it a new one the way the
    designer names a new widget. ``taken`` grows by the ids handed out."""
    for data in widgets:
        wid = data.get("id")
        while not wid or wid in taken:
            wid = f"{data['type']}_{uuid.uuid4().hex[:6]}"
        data["id"] = wid
        taken.add(wid)
        assign_ids(data.get("children", []), taken)


def _box(widgets):
    """The bounding box (left, top, right, bottom) of top-level widgets, with CanvasItem.from_dict's defaults."""
    rects = []
    for data in widgets:
        geo = data.get("geometry", {})
        x, y = geo.get("x", 0), geo.get("y", 0)
        rects.append((x, y, x + geo.get("w", 120), y + geo.get("h", 40)))
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


def _fit(offset, low, high, limit):
    """Shift ``offset`` so that low..high plus it stays within 0..limit, when it fits."""
    if high - low > limit:
        return offset
    return max(-low, min(offset, limit - high))


def top_level_offset(widgets, step, canvas_width, canvas_height):
    """How far pasted top-level widgets move from where they were copied: ``step`` each way, kept on the canvas."""
    left, top, right, bottom = _box(widgets)
    return (_fit(step, left, right, canvas_width), _fit(step, top, bottom, canvas_height))


def container_positions(widgets, step, area):
    """Local positions of widgets pasted into a container, the group's top-left ``step`` into ``area``
    (x, y, width, height in the container), kept inside it."""
    left, top, right, bottom = _box(widgets)
    ax, ay, aw, ah = area
    dx = _fit(step, 0, right - left, aw)
    dy = _fit(step, 0, bottom - top, ah)
    return [(ax + dx + data.get("geometry", {}).get("x", 0) - left,
             ay + dy + data.get("geometry", {}).get("y", 0) - top) for data in widgets]


def image_base(scene):
    return getattr(scene, "_asset_base_dir", None) or Path.cwd()
