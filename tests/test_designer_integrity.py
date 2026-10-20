"""Editing, dragging and saving must preserve a valid designer widget tree."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QMimeData, QPointF, QRectF, Qt
from PyQt5.QtGui import QDropEvent
from PyQt5.QtWidgets import QApplication, QGraphicsItem

from app.core.project import ProjectData, ProjectManager
from app.core.widget_registry import registry
from app.designer.canvas import DesignScene, DesignView, MIME_WIDGET_TYPE
from app.designer.canvas_item import CanvasItem
from app.designer.property_editor import PropertyEditor
from app.widgets.basic import register_basic_widgets
from app.widgets.layout import register_layout_widgets


class DesignerIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        register_basic_widgets()
        register_layout_widgets()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "design.uidp"
        self.scene = DesignScene()
        self.addCleanup(self.scene.clear)

    def make_item(self, type_name, **props):
        properties = registry.get(type_name).get_default_props()
        properties.update(props)
        item = CanvasItem(type_name, properties)
        self.scene.add_canvas_item(item)
        return item

    def test_dimension_editors_enforce_widget_minimums_and_roundtrip(self):
        editor = PropertyEditor()
        try:
            for type_name in ("PushButton", "Separator", "HBoxLayout", "VBoxLayout",
                              "FlexLayout", "GroupBox", "TabWidget", "CardContainer"):
                with self.subTest(type_name=type_name):
                    item = self.make_item(type_name)
                    meta = registry.get(type_name)
                    editor._load_item(item)
                    editor._editors["geo_w"].setValue(0)
                    editor._editors["geo_h"].setValue(0)
                    self.assertEqual(item.rect().width(), meta.min_width)
                    self.assertEqual(item.rect().height(), meta.min_height)
            before = {item.widget_id: item.to_dict()
                      for item in self.scene.top_level_canvas_items()}
            manager = ProjectManager()
            manager.save_from_scene(self.scene, str(self.path))
            manager.load_to_scene(self.scene, str(self.path))
            self.assertEqual({item.widget_id: item.to_dict()
                              for item in self.scene.top_level_canvas_items()}, before)
        finally:
            editor.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_nested_vertical_containers_keep_positive_minimum_width(self):
        root = self.make_item("VBoxLayout")
        containers = [root]
        for _ in range(4):
            child = self.make_item("VBoxLayout")
            containers[-1].add_child(child)
            containers.append(child)
        button = self.make_item("PushButton")
        containers[-1].add_child(button)
        editor = PropertyEditor()
        try:
            editor._load_item(root)
            editor._editors["geo_w"].setValue(0)
            for item in containers + [button]:
                self.assertGreaterEqual(item.rect().width(),
                                        registry.get(item.type_name).min_width)
            manager = ProjectManager()
            manager.save_from_scene(self.scene, str(self.path))
            manager.load_to_scene(self.scene, str(self.path))
            ProjectData.validate(manager.current.to_dict())
        finally:
            editor.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_invalid_save_preserves_existing_file_and_project_state(self):
        item = self.make_item("PushButton")
        manager = ProjectManager()
        manager.save_from_scene(self.scene, str(self.path))
        previous = self.path.read_bytes()
        manager.mark_dirty()
        original = manager.current
        valid = item.to_dict()
        invalid_items = []
        for dimension in ("w", "h"):
            for value in (0, -1, float("inf"), float("nan")):
                invalid = copy.deepcopy(valid)
                invalid["geometry"][dimension] = value
                invalid_items.append(invalid)
        invalid = copy.deepcopy(valid)
        invalid["children"] = [copy.deepcopy(valid)]  # duplicate ID
        invalid_items.append(invalid)
        invalid = copy.deepcopy(valid)
        invalid["properties"]["value"] = float("nan")
        invalid_items.append(invalid)
        for invalid in invalid_items:
            with self.subTest(item=invalid), patch.object(item, "to_dict", return_value=invalid):
                with self.assertRaises(ValueError):
                    manager.save_from_scene(self.scene, str(self.path), "must not replace")
            self.assertEqual(self.path.read_bytes(), previous)
            self.assertIs(manager.current, original)
            self.assertTrue(manager.is_dirty)
            self.assertEqual(list(Path(self.temp.name).iterdir()), [self.path])

    def test_mixed_tab_layouts_preserve_hidden_free_page_on_save_reload(self):
        for managed_page in (0, 1):
            for mode in ("垂直", "水平", "弹性(Flex)"):
                for reverse_children in (False, True):
                    with self.subTest(page=managed_page, mode=mode, reverse=reverse_children):
                        self.scene.clear()
                        free_page = 1 - managed_page
                        tabs = self.make_item(
                            "TabWidget", tabNames="布局页\n自由页", currentTab=free_page,
                            **{f"_tabLayout_{free_page}": "自由",
                               f"_tabLayout_{managed_page}": mode},
                        )
                        tabs.setPos(200, 100)
                        free = self.make_item("PushButton", text="自由页位置")
                        tabs.add_child(free)
                        free.setPos(73.5, 91.25)
                        free.set_rect(QRectF(0, 0, 123, 47))
                        tabs.set_property("currentTab", managed_page)
                        managed = self.make_item("PushButton", text="自动布局")
                        tabs.add_child(managed)
                        if reverse_children:
                            tabs._container_children.reverse()
                        before = tabs.to_dict()
                        manager = ProjectManager()
                        manager.save_from_scene(self.scene, str(self.path))
                        manager.load_to_scene(self.scene, str(self.path))
                        restored = self.scene.get_item_by_id(tabs.widget_id)
                        self.assertEqual(restored.to_dict(), before)
                        restored_free = self.scene.get_item_by_id(free.widget_id)
                        self.assertFalse(restored_free.isVisible())
                        restored.set_property("currentTab", free_page)
                        self.assertTrue(restored_free.isVisible())
                        self.assertTrue(restored_free.flags() & QGraphicsItem.ItemIsMovable)
                        self.assertEqual(restored_free.pos(), QPointF(73.5, 91.25))
                        self.assertEqual(restored_free.rect(), QRectF(0, 0, 123, 47))

    def test_nested_free_layout_load_keeps_parent_relative_geometry(self):
        document = {
            "id": "outer", "type": "CardContainer",
            "properties": {"layout": "自由"},
            "geometry": {"x": 200, "y": 100, "w": 600, "h": 400},
            "binding": None,
            "children": [{
                "id": "inner", "type": "CardContainer",
                "properties": {"layout": "自由"},
                "geometry": {"x": 50, "y": 70, "w": 300, "h": 200},
                "binding": None,
                "children": [{
                    "id": "label", "type": "Label", "properties": {"text": "位置"},
                    "geometry": {"x": 40, "y": 60, "w": 100, "h": 30},
                    "binding": None,
                }],
            }],
        }
        restored = CanvasItem.from_dict(document)
        self.scene.add_canvas_item(restored)
        self.assertEqual(restored.to_dict(), document)
        self.assertEqual(self.scene.get_item_by_id("label").scenePos(), QPointF(290, 230))

    def test_palette_drop_into_offset_free_containers_keeps_drop_position(self):
        view = DesignView(self.scene)
        view.resize(900, 700)
        try:
            for container_type in ("CardContainer", "TabWidget"):
                for nested in (False, True):
                    with self.subTest(container_type=container_type, nested=nested):
                        self.scene.clear()
                        container = self.make_item(container_type, currentTab=1,
                                                   **{"_tabLayout_1": "自由"})
                        container.setPos(100, 120)
                        if nested:
                            outer = self.make_item("CardContainer")
                            outer.setPos(40, 50)
                            outer.set_rect(QRectF(0, 0, 600, 500))
                            outer.add_child(container)
                        view.resetTransform()
                        view.scale(1.25, 1.25)
                        point = container.mapToScene(QPointF(80, 90))
                        viewport_point = view.mapFromScene(point)
                        scene_point = view.mapToScene(viewport_point)
                        grid = self.scene.grid_size
                        expected = QPointF(round(scene_point.x() / grid) * grid,
                                           round(scene_point.y() / grid) * grid)
                        mime = QMimeData()
                        mime.setData(MIME_WIDGET_TYPE, b"PushButton")
                        event = QDropEvent(QPointF(viewport_point), Qt.CopyAction,
                                           mime, Qt.LeftButton, Qt.NoModifier)
                        view.dropEvent(event)
                        self.assertTrue(event.isAccepted())
                        self.assertEqual(len(container._container_children), 1)
                        dropped = container._container_children[0]
                        self.assertEqual(dropped.scenePos(), expected)
                        self.assertEqual(dropped.pos(), container.mapFromScene(expected))
                        if container_type == "TabWidget":
                            self.assertEqual(dropped.tab_index, 1)
        finally:
            view.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_reparent_and_detach_preserve_scene_position(self):
        first = self.make_item("CardContainer")
        first.setPos(100, 120)
        second = self.make_item("CardContainer")
        second.setPos(500, 300)
        child = self.make_item("PushButton")
        child.setPos(180, 210)
        expected = child.scenePos()
        first.add_child(child)
        self.assertEqual(child.scenePos(), expected)
        second.add_child(child)
        self.assertEqual(child.scenePos(), expected)
        self.assertEqual(first._container_children, [])
        child.detach_from_parent()
        self.assertEqual(child.scenePos(), expected)
        self.assertIsNone(child.parentItem())


if __name__ == "__main__":
    unittest.main()
