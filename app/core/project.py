# coding: utf-8
"""Project serialization: save/load .uidp files (JSON format)."""
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.designer.canvas import DesignScene
from app.designer.canvas_item import CanvasItem
from app.common.signal_bus import signalBus

PROJECT_VERSION = "1.0"


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
        proj = cls()
        proj.version = data.get("version", PROJECT_VERSION)
        proj.app_name = data.get("appName", "上位机")
        canvas = data.get("canvas", {})
        proj.canvas_width = canvas.get("width", 1200)
        proj.canvas_height = canvas.get("height", 800)
        proj.grid_size = canvas.get("gridSize", 10)
        proj.widgets = data.get("widgets", [])
        proj.serial = data.get("serial", proj.serial)
        return proj


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
        if app_name is not None:
            self._current.app_name = app_name
        self._current.canvas_width = int(scene.sceneRect().width())
        self._current.canvas_height = int(scene.sceneRect().height())
        self._current.grid_size = scene.grid_size
        self._current.widgets = [
            item.to_dict() for item in scene.top_level_canvas_items()
        ]
        self._current.file_path = path

        data = self._current.to_dict()
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._dirty = False
        signalBus.projectSaved.emit(path)

    def load_to_scene(self, scene: DesignScene, path: str):
        """Load a .uidp file and populate the scene."""
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
        self._current = ProjectData.from_dict(data)
        self._current.file_path = path

        scene.clear_all()
        scene.set_canvas_size(self._current.canvas_width, self._current.canvas_height)
        scene.set_grid_size(self._current.grid_size)

        for wd in self._current.widgets:
            item = CanvasItem.from_dict(wd)
            scene.add_canvas_item(item)

        self._dirty = False
        signalBus.projectLoaded.emit(path)

    def export_scene_data(self, scene: DesignScene, app_name: str = None) -> ProjectData:
        """Capture current scene state into ProjectData (without saving to file)."""
        if app_name is not None:
            self._current.app_name = app_name
        self._current.canvas_width = int(scene.sceneRect().width())
        self._current.canvas_height = int(scene.sceneRect().height())
        self._current.grid_size = scene.grid_size
        self._current.widgets = [
            item.to_dict() for item in scene.top_level_canvas_items()
        ]
        return self._current
