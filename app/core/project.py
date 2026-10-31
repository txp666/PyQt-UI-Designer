# coding: utf-8
"""Project serialization: save/load .uidp files (JSON format)."""
import json
import copy
import math
import os
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.designer.canvas import DesignScene
from app.designer.canvas_item import CanvasItem
from app.common.signal_bus import signalBus
from app.core.widget_registry import registry
from PyQt5.QtCore import QSignalBlocker

PROJECT_VERSION = "1.0"
# Link cards that can carry their own frame format (properties.parserConfig).
LINK_CARD_TYPES = ("SerialConfigCard", "TcpConfigCard", "MqttConfigCard")


def _with_legacy_cards(items):
    """The widget tree with what older files leave out of a Modbus card filled in: one with a poll
    table and no pollMode keeps polling its table (modbus_card_properties)."""
    from app.core.modbus_card import modbus_card_properties
    result = []
    for item in items:
        if item.get("type") == "ModbusConfigCard" and "pollMode" not in item.get("properties", {}):
            item = {**item, "properties": modbus_card_properties(item.get("properties", {}))}
        if item.get("children"):
            item = {**item, "children": _with_legacy_cards(item["children"])}
        result.append(item)
    return result


class ProjectData:
    """In-memory representation of a .uidp project."""

    def __init__(self):
        self.version: str = PROJECT_VERSION
        self.app_name: str = "上位机"
        self.canvas_width: int = 1200
        self.canvas_height: int = 800
        self.grid_size: int = 10
        self.widgets: List[Dict[str, Any]] = []
        self.serial: Dict[str, Any] = {
            "baudRate": 115200,
            "dataBits": 8,
            "parity": "None",
            "stopBits": 1,
            "parser": "line",
            "parserConfig": {"separator": ","},
        }
        self.file_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "appName": self.app_name,
            "canvas": {
                "width": self.canvas_width,
                "height": self.canvas_height,
                "gridSize": self.grid_size,
            },
            "widgets": self.widgets,
            "serial": self.serial,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectData":
        cls.validate(data)
        proj = cls()
        proj.version = data.get("version", PROJECT_VERSION)
        proj.app_name = data.get("appName", "上位机")
        canvas = data.get("canvas", {})
        proj.canvas_width = canvas.get("width", 1200)
        proj.canvas_height = canvas.get("height", 800)
        proj.grid_size = canvas.get("gridSize", 10)
        proj.widgets = _with_legacy_cards(data.get("widgets", []))
        proj.serial.update(data.get("serial", {}))
        return proj

    @staticmethod
    def validate(data):
        """Reject invalid documents before touching the current scene."""
        if not isinstance(data, dict):
            raise ValueError("项目根节点必须是对象")
        if data.get("version", PROJECT_VERSION) != PROJECT_VERSION:
            raise ValueError("不支持的项目版本")
        if not isinstance(data.get("appName", ""), str):
            raise ValueError("应用名称必须是文本")
        canvas = data.get("canvas", {})
        if not isinstance(canvas, dict):
            raise ValueError("画布配置必须是对象")
        for name, default, limit in (("width", 1200, 9999), ("height", 800, 9999),
                                     ("gridSize", 10, 1000)):
            value = canvas.get(name, default)
            if type(value) is not int or not 1 <= value <= limit:
                raise ValueError(f"无效画布参数: {name}")
        serial = data.get("serial", {})
        if not isinstance(serial, dict):
            raise ValueError("串口配置必须是对象")
        from app.core.protocol_parser import create_parser
        project_parser = serial.get("parser", "line")
        create_parser(project_parser, serial.get("parserConfig"))
        ids = set()

        def check_card_parser(item, props):
            card = item.get("id") or ""
            config = props["parserConfig"]
            if not isinstance(config, dict):
                raise ValueError(f"卡片 {card} 的 parserConfig 必须是对象")
            mode = props.get("defaultParser", "项目设置")
            try:
                create_parser(project_parser if mode == "项目设置" else mode, config)
            except ValueError as error:
                raise ValueError(f"卡片 {card}: {error}") from None

        def walk(items, depth=0):
            if not isinstance(items, list) or depth > 64:
                raise ValueError("无效控件树")
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                    raise ValueError("控件缺少有效类型")
                if not registry.get(item["type"]):
                    raise ValueError(f"未知控件类型: {item['type']}")
                wid = item.get("id")
                if wid is not None:
                    if not isinstance(wid, str) or not wid or wid in ids:
                        raise ValueError("控件 ID 无效或重复")
                    ids.add(wid)
                props = item.get("properties", {})
                if not isinstance(props, dict):
                    raise ValueError("控件属性必须是对象")
                if item["type"] in LINK_CARD_TYPES and "parserConfig" in props:
                    check_card_parser(item, props)
                if item.get("binding") is not None and not isinstance(item["binding"], dict):
                    raise ValueError("控件绑定必须是对象")
                geo = item.get("geometry", {})
                if not isinstance(geo, dict):
                    raise ValueError("控件位置必须是对象")
                for key, value in geo.items():
                    if key in ("x", "y", "w", "h"):
                        if type(value) not in (int, float) or not math.isfinite(value):
                            raise ValueError("控件位置必须是有限数值")
                        if key in ("w", "h") and value <= 0:
                            raise ValueError("控件尺寸必须大于零")
                tab = item.get("tabIndex", 0)
                if type(tab) is not int or tab < 0:
                    raise ValueError("无效选项卡索引")
                walk(item.get("children", []), depth + 1)

        walk(data.get("widgets", []))


class ProjectManager:
    """Handles project new/save/load operations."""

    def __init__(self):
        self._current: ProjectData = ProjectData()
        self._dirty: bool = False

    @property
    def current(self) -> ProjectData:
        return self._current

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self):
        self._dirty = True

    def new_project(self):
        self._current = ProjectData()
        self._dirty = False
        signalBus.projectNew.emit()

    def save_from_scene(self, scene: DesignScene, path: str, app_name: str = None):
        """Serialize current scene to .uidp file."""
        scene.aboutToSerialize.emit()
        candidate = copy.deepcopy(self._current)
        if app_name is not None:
            candidate.app_name = app_name
        candidate.canvas_width = int(scene.sceneRect().width())
        candidate.canvas_height = int(scene.sceneRect().height())
        candidate.grid_size = scene.grid_size
        candidate.widgets = [
            item.to_dict() for item in scene.top_level_canvas_items()
        ]
        old_base = (Path(self._current.file_path).expanduser().resolve().parent
                    if self._current.file_path else Path.cwd())
        new_base = Path(path).expanduser().resolve().parent
        if old_base != new_base:
            self._rebase_image_paths(candidate.widgets, old_base, new_base)
        candidate.file_path = path
        document = candidate.to_dict()
        ProjectData.validate(document)
        payload = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False)
        target = Path(path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                             dir=target.parent, prefix=f".{target.name}.",
                                             suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._current = candidate
        scene._asset_base_dir = new_base
        images = {}
        def collect_images(items):
            for item in items:
                if item["type"] == "ImageDisplay":
                    images[item["id"]] = item.get("properties", {}).get("imagePath", "")
                collect_images(item.get("children", []))
        collect_images(candidate.widgets)
        def update_images(items):
            for item in items:
                if item.widget_id in images:
                    item.properties["imagePath"] = images[item.widget_id]
                item.set_asset_base_dir(new_base)
                update_images(item._container_children)
        update_images(scene.top_level_canvas_items())
        self._dirty = False
        signalBus.projectSaved.emit(path)

    @staticmethod
    def _rebase_image_paths(items, old_base, new_base):
        for item in items:
            props = item.get("properties", {})
            path = props.get("imagePath", "")
            if item["type"] == "ImageDisplay" and path:
                source = Path(path).expanduser()
                if not source.is_absolute():
                    source = (old_base / source).resolve()
                    try:
                        props["imagePath"] = Path(os.path.relpath(source, new_base)).as_posix()
                    except ValueError:
                        # Windows paths on another drive cannot be made relative.
                        props["imagePath"] = str(source)
            ProjectManager._rebase_image_paths(item.get("children", []), old_base, new_base)

    def load_to_scene(self, scene: DesignScene, path: str):
        """Load a .uidp file and populate the scene."""
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
        candidate = ProjectData.from_dict(data)
        candidate.file_path = path
        base_dir = Path(path).expanduser().resolve().parent
        # Construct every widget before removing any existing item. Block global
        # edit notifications while building/applying the replacement.
        with QSignalBlocker(signalBus), QSignalBlocker(scene):
            staged = [CanvasItem.from_dict(wd, asset_base_dir=base_dir)
                      for wd in candidate.widgets]
            old_items = scene.top_level_canvas_items()
            old_rect, old_grid = scene.sceneRect(), scene.grid_size
            old_base = getattr(scene, "_asset_base_dir", None)
            try:
                scene.clear_all()
                scene._asset_base_dir = base_dir
                scene.set_canvas_size(candidate.canvas_width, candidate.canvas_height)
                scene.set_grid_size(candidate.grid_size)
                for item in staged:
                    scene.add_canvas_item(item)
            except Exception:
                scene.clear_all()
                scene._asset_base_dir = old_base
                scene.set_canvas_size(old_rect.width(), old_rect.height())
                scene.set_grid_size(old_grid)
                for item in old_items:
                    scene.add_canvas_item(item)
                raise
        # The blocker also hid the new canvas size from the views, which would keep the old scroll range
        # and show a smaller project shifted off to one side.
        scene.sceneRectChanged.emit(scene.sceneRect())
        self._current = candidate
        self._dirty = False
        scene.clearSelection()
        signalBus.widgetDeselected.emit()
        signalBus.projectLoaded.emit(path)

    def export_scene_data(self, scene: DesignScene, app_name: str = None) -> ProjectData:
        """Capture current scene state into ProjectData (without saving to file)."""
        scene.aboutToSerialize.emit()
        if app_name is not None:
            self._current.app_name = app_name
        self._current.canvas_width = int(scene.sceneRect().width())
        self._current.canvas_height = int(scene.sceneRect().height())
        self._current.grid_size = scene.grid_size
        self._current.widgets = [
            item.to_dict() for item in scene.top_level_canvas_items()
        ]
        return self._current
