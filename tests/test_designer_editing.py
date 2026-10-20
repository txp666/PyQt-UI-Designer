"""Tab edits and selection tools preserve the editable widget hierarchy."""
import copy
import json
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QRectF, Qt
from PyQt5.QtGui import QFocusEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QWidget

from app.core.code_generator import _gen_ui
from app.common.signal_bus import signalBus
from app.core.project import ProjectData, ProjectManager
from app.core.widget_registry import registry
from app.designer import selection_manager as selection
from app.designer.canvas import DesignScene
from app.designer.canvas_item import CanvasItem
from app.designer.property_editor import PropertyEditor
from app.view.preview_interface import PreviewCanvas
from app.widgets.basic import register_basic_widgets
from app.widgets.layout import TabContainer, register_layout_widgets


class DesignerEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        register_basic_widgets()
        register_layout_widgets()

    def setUp(self):
        self.scene = DesignScene()
        self.addCleanup(self.scene.clear)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "edited.uidp"

    def make_item(self, type_name, x=0, y=0, **props):
        properties = registry.get(type_name).get_default_props()
        properties.update(props)
        item = CanvasItem(type_name, properties)
        item.setPos(x, y)
        self.scene.add_canvas_item(item)
        return item

    def roundtrip(self):
        before = {item.widget_id: item.to_dict()
                  for item in self.scene.top_level_canvas_items()}
        manager = ProjectManager()
        manager.save_from_scene(self.scene, str(self.path))
        manager.load_to_scene(self.scene, str(self.path))
        self.assertEqual({item.widget_id: item.to_dict()
                          for item in self.scene.top_level_canvas_items()}, before)

    def test_renaming_tabs_preserves_active_page_widgets_and_child_visibility(self):
        tabs = self.make_item("TabWidget", tabNames="A\nB", currentTab=1)
        active = self.make_item("PushButton", 30, 70)
        tabs.add_child(active)
        hidden = self.make_item("PushButton", 40, 80)
        tabs.add_child(hidden, tab_index=0)
        pages = [tabs._inner_widget.widget(i) for i in range(2)]
        tabs.set_property("tabNames", "Renamed A\nRenamed B")
        self.assertEqual(tabs.properties["currentTab"], 1)
        self.assertEqual(tabs._inner_widget.currentIndex(), 1)
        self.assertEqual([tabs._inner_widget.widget(i) for i in range(2)], pages)
        self.assertTrue(active.isVisible())
        self.assertFalse(hidden.isVisible())
        self.assertEqual(tabs._inner_widget.tabText(1), "Renamed B")
        self.roundtrip()

    def test_page_reduction_preserves_contents_and_updates_property_editor(self):
        tabs = self.make_item("TabWidget", tabNames="A\nB\nC", currentTab=2)
        children = []
        for page in range(3):
            child = self.make_item("PushButton", 20 + page * 30, 50 + page * 40)
            tabs.add_child(child, tab_index=page)
            children.append(child)
        original_positions = [child.pos() for child in children]
        tabs.properties["_tabLayout_2"] = "垂直"
        editor = PropertyEditor()
        self.addCleanup(lambda: sip.delete(editor))
        editor._load_item(tabs)
        self.assertEqual(editor._editors["currentTab"].maximum(), 2)
        editor._editors["tabNames"].setPlainText("A\nB")
        self.app.sendEvent(editor._editors["tabNames"], QFocusEvent(QEvent.FocusOut))
        self.assertEqual([child.tab_index for child in children], [0, 1, 1])
        self.assertEqual(tabs.properties["currentTab"], 1)
        self.assertEqual(tabs._inner_widget.currentIndex(), 1)
        self.assertEqual(editor._editors["currentTab"].value(), 1)
        self.assertEqual(editor._editors["currentTab"].maximum(), 1)
        self.assertEqual(editor._editors["tabLayout"].currentText(), "自由")
        self.assertNotIn("_tabLayout_2", tabs.properties)
        editor._editors["currentTab"].setValue(19)
        self.assertEqual(tabs.properties["currentTab"], 1)
        editor._editors["tabNames"].setPlainText("")
        self.app.sendEvent(editor._editors["tabNames"], QFocusEvent(QEvent.FocusOut))
        self.assertEqual(tabs._inner_widget.count(), 1)
        self.assertEqual(tabs._inner_widget.tabText(0), "标签1")
        self.assertEqual(editor._editors["currentTab"].maximum(), 0)
        self.assertEqual([child.tab_index for child in children], [0, 0, 0])
        self.assertEqual([child.pos() for child in children], original_positions)
        self.assertTrue(all(child.isVisible() for child in children))
        self.roundtrip()

    def test_typing_names_does_not_move_children_and_save_commits_without_focus_loss(self):
        tabs = self.make_item("TabWidget", tabNames="A\nB", currentTab=1)
        child = self.make_item("PushButton", 30, 70)
        tabs.add_child(child)
        editor = PropertyEditor()
        self.addCleanup(lambda: sip.delete(editor))
        editor.set_scene(self.scene)
        editor._load_item(tabs)
        editor.show()
        names = editor._editors["tabNames"]
        names.setFocus()
        self.app.processEvents()
        manager = ProjectManager()
        signalBus.canvasChanged.connect(manager.mark_dirty)
        self.addCleanup(lambda: signalBus.canvasChanged.disconnect(manager.mark_dirty))
        names.selectAll()
        QTest.keyClicks(names, "First")
        self.assertEqual(child.tab_index, 1)
        self.assertEqual(tabs._inner_widget.count(), 2)
        self.assertTrue(manager.is_dirty)
        QTest.keyClick(names, Qt.Key_Return)
        QTest.keyClicks(names, "Second")
        self.assertTrue(names.hasFocus())
        manager.save_from_scene(self.scene, str(self.path))
        self.assertTrue(names.hasFocus())
        saved = json.loads(self.path.read_text(encoding="utf-8"))["widgets"][0]
        self.assertEqual(saved["properties"]["tabNames"], "First\nSecond")
        self.assertEqual(saved["properties"]["currentTab"], 1)
        self.assertEqual(saved["children"][0]["tabIndex"], 1)
        self.assertFalse(manager.is_dirty)
        self.roundtrip()

    def test_export_capture_and_changing_selection_commit_pending_names(self):
        tabs = self.make_item("TabWidget", tabNames="A\nB", currentTab=1)
        child = self.make_item("PushButton", 30, 70)
        tabs.add_child(child)
        editor = PropertyEditor()
        self.addCleanup(lambda: sip.delete(editor))
        editor.set_scene(self.scene)
        editor._load_item(tabs)
        editor._editors["tabNames"].setPlainText("Changed A\nChanged B")
        project = ProjectManager().export_scene_data(self.scene)
        self.assertEqual(project.widgets[0]["properties"]["tabNames"], "Changed A\nChanged B")
        self.assertEqual(child.tab_index, 1)
        editor._editors["tabNames"].setPlainText("Only page")
        editor._load_item(child)
        self.assertEqual(child.tab_index, 0)
        self.assertEqual(tabs.properties["currentTab"], 0)
        self.assertEqual(tabs._inner_widget.count(), 1)
        self.roundtrip()

    def test_replacing_project_discards_pending_edits_to_removed_items(self):
        for operation in ("load", "new"):
            with self.subTest(operation=operation):
                self.scene.clear()
                tabs = self.make_item("TabWidget", tabNames="A\nB", currentTab=1)
                child = self.make_item("PushButton", 30, 70)
                tabs.add_child(child)
                original = tabs.to_dict()
                editor = PropertyEditor()
                editor.set_scene(self.scene)
                editor._load_item(tabs)
                names = editor._editors["tabNames"]
                manager = ProjectManager()
                signalBus.canvasChanged.connect(manager.mark_dirty)
                try:
                    names.setPlainText("Uncommitted replacement")
                    self.assertTrue(manager.is_dirty)
                    self.assertEqual(tabs.to_dict(), original)
                    if operation == "load":
                        self.path.write_text(json.dumps({
                            "appName": "Replacement",
                            "widgets": [{"id": "replacement", "type": "PushButton"}],
                        }), encoding="utf-8")
                        manager.load_to_scene(self.scene, str(self.path))
                        self.assertEqual(manager.current.app_name, "Replacement")
                        self.assertIsNotNone(self.scene.get_item_by_id("replacement"))
                    else:
                        self.scene.clear_all()
                        manager.new_project()
                        signalBus.widgetDeselected.emit()
                        self.assertEqual(self.scene.top_level_canvas_items(), [])
                    self.assertIsNone(editor._current_item)
                    self.assertFalse(manager.is_dirty)
                    self.assertEqual(tabs.to_dict(), original)
                    # A delayed focus event from the old editor must also do nothing.
                    self.app.sendEvent(names, QFocusEvent(QEvent.FocusOut))
                    self.assertFalse(manager.is_dirty)
                    self.assertEqual(tabs.to_dict(), original)
                finally:
                    signalBus.canvasChanged.disconnect(manager.mark_dirty)
                    sip.delete(editor)
                    sip.delete(tabs)

    def test_native_tab_page_reduction_reparents_contents_without_losing_geometry(self):
        tabs = TabContainer()
        self.addCleanup(lambda: sip.delete(tabs))
        tabs.set_tab_names("A\nB\nC")
        children = [QWidget(tabs.widget(i)) for i in range(3)]
        for index, child in enumerate(children):
            child.setGeometry(20 + index * 10, 40, 90, 30)
        geometry = [child.geometry() for child in children]
        tabs.setCurrentIndex(2)
        tabs.set_tab_names("A")
        self.assertEqual(tabs.count(), 1)
        self.assertEqual(tabs.currentIndex(), 0)
        self.assertTrue(all(child.parentWidget() is tabs.widget(0) for child in children))
        self.assertEqual([child.geometry() for child in children], geometry)

    def test_legacy_tab_indices_are_safe_in_designer_preview_and_generated_widgets(self):
        for names, expected_count in (("A\nB", 2), ("", 1)):
            with self.subTest(names=names):
                document = {
                    "type": "TabWidget", "id": "tabs",
                    "geometry": {"x": 20, "y": 30, "w": 350, "h": 250},
                    "properties": {"tabNames": names, "currentTab": 19},
                    "children": [{
                        "type": "PushButton", "id": "button", "tabIndex": 19,
                        "properties": {"text": "Keep me"},
                        "geometry": {"x": 30, "y": 70, "w": 120, "h": 36},
                    }],
                }
                original = copy.deepcopy(document)
                item = CanvasItem.from_dict(document)
                self.scene.add_canvas_item(item)
                self.assertEqual(item.properties["currentTab"], expected_count - 1)
                self.assertEqual(item._container_children[0].tab_index, expected_count - 1)
                self.assertTrue(item._container_children[0].isVisible())
                self.roundtrip()
                self.scene.clear()

                preview = PreviewCanvas()
                try:
                    project = ProjectData.from_dict({"widgets": [document]})
                    preview.build_from_project(project)
                    tabs, button = preview._widgets
                    self.assertEqual(tabs.count(), expected_count)
                    self.assertEqual(tabs.currentIndex(), expected_count - 1)
                    self.assertIs(button.parentWidget(), tabs.widget(expected_count - 1))
                    self.assertFalse(button.isWindow())
                finally:
                    preview.clear()
                    sip.delete(preview)

                # Execute the exported creation method with real Qt widgets.
                # A QWidget host avoids requiring native frameless-window APIs.
                serial_module = ModuleType("serial_handler")
                serial_module._list_all_ports = lambda: []
                namespace = {"__file__": str(Path(self.temp.name) / "ui.py")}
                with patch.dict("sys.modules", {"serial_handler": serial_module}):
                    exec(_gen_ui([document], 500, 350), namespace)
                host = SimpleNamespace(_page=QWidget(), widgets={}, _theme_containers=[])
                try:
                    namespace["MainUI"]._create_widgets(host)
                    tabs, button = host.widgets["tabs"], host.widgets["button"]
                    self.assertEqual(tabs.count(), expected_count)
                    self.assertEqual(tabs.currentIndex(), expected_count - 1)
                    self.assertIs(button.parentWidget(), tabs.widget(expected_count - 1))
                    self.assertFalse(button.isWindow())
                finally:
                    sip.delete(host._page)
                self.assertEqual(document, original)

    def test_alignment_uses_scene_edges_across_nested_free_containers(self):
        for action, edge in (
                (selection.align_left, "left"), (selection.align_right, "right"),
                (selection.align_top, "top"), (selection.align_bottom, "bottom")):
            with self.subTest(edge=edge):
                self.scene.clear()
                outer = self.make_item("CardContainer", 200, 100)
                inner = self.make_item("CardContainer", 250, 150)
                outer.add_child(inner)
                nested = self.make_item("PushButton", 290, 210)
                inner.add_child(nested)
                standalone = self.make_item("PushButton", 20, 400)
                standalone.set_rect(QRectF(0, 0, 160, 50))
                nested.setSelected(True)
                standalone.setSelected(True)
                before = [getattr(item.mapRectToScene(item.rect()), edge)()
                          for item in (nested, standalone)]
                expected = max(before) if edge in ("right", "bottom") else min(before)
                action(self.scene)
                for item in (nested, standalone):
                    self.assertEqual(getattr(item.mapRectToScene(item.rect()), edge)(),
                                     expected)
                self.roundtrip()

    def test_distribution_uses_scene_positions_across_container_boundaries(self):
        for action, axis in ((selection.distribute_horizontal, "x"),
                             (selection.distribute_vertical, "y")):
            with self.subTest(axis=axis):
                self.scene.clear()
                parent = self.make_item("CardContainer", 200, 150)
                nested = self.make_item("PushButton", 270, 210)
                parent.add_child(nested)
                first = self.make_item("PushButton", 20, 50)
                last = self.make_item("PushButton", 500, 600)
                for item in (first, nested, last):
                    item.setSelected(True)
                action(self.scene)
                positions = [getattr(item.scenePos(), axis)() for item in (first, nested, last)]
                self.assertEqual(positions[1], (positions[0] + positions[2]) / 2)
                self.roundtrip()

    def test_selection_tools_skip_managed_children_and_selected_descendants(self):
        automatic = self.make_item("VBoxLayout", 600, 200)
        managed = self.make_item("PushButton")
        automatic.add_child(managed)
        managed_before = managed.pos()
        card = self.make_item("CardContainer", 250, 300)
        nested = self.make_item("PushButton", 280, 350)
        card.add_child(nested)
        local_before = nested.pos()
        other = self.make_item("PushButton", 50, 50)
        for item in (managed, card, nested, other):
            item.setSelected(True)
        selection.align_left(self.scene)
        self.assertEqual(card.scenePos().x(), other.scenePos().x())
        self.assertEqual(nested.pos(), local_before)
        self.assertEqual(managed.pos(), managed_before)
        selection.align_top(self.scene)
        self.assertEqual(card.scenePos().y(), other.scenePos().y())
        self.assertEqual(nested.pos(), local_before)
        self.assertEqual(managed.pos(), managed_before)
        self.roundtrip()


if __name__ == "__main__":
    unittest.main()
