"""Failed/cancelled project operations must preserve the user's work."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox

from app.common.signal_bus import signalBus
from app.core.project import ProjectManager
from app.designer.canvas import DesignScene
from app.designer.canvas_item import CanvasItem
from app.view.main_window import MainWindow
from app.widgets.basic import register_basic_widgets


class ProjectSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        register_basic_widgets()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "project.uidp"
        self.scene = DesignScene()
        self.item = CanvasItem("PushButton", {"text": "unsaved"})
        self.scene.add_canvas_item(self.item)
        self.manager = ProjectManager()
        self.manager.mark_dirty()
        self.original = self.manager.current
        self.addCleanup(self.scene.clear)

    def assert_untouched(self):
        self.assertEqual(self.scene.top_level_canvas_items(), [self.item])
        self.assertIs(self.manager.current, self.original)
        self.assertTrue(self.manager.is_dirty)

    def test_invalid_document_and_nested_widget_preserve_scene(self):
        for text in (
            "{",
            json.dumps({"widgets": [{}]}),
            json.dumps({"widgets": [{"type": "NoSuchWidget"}]}),
            json.dumps({"canvas": {"width": -1}}),
            json.dumps({"widgets": [{"type": "PushButton", "children": [{}]}]}),
        ):
            with self.subTest(text=text):
                self.path.write_text(text)
                with self.assertRaises(ValueError):
                    self.manager.load_to_scene(self.scene, str(self.path))
                self.assert_untouched()

    def test_widget_construction_failure_preserves_scene(self):
        self.path.write_text(json.dumps({"widgets": [{"type": "PushButton"}]}))
        with patch.object(CanvasItem, "from_dict", side_effect=RuntimeError("construction")):
            with self.assertRaises(RuntimeError):
                self.manager.load_to_scene(self.scene, str(self.path))
        self.assert_untouched()

    def test_scene_application_failure_rolls_back(self):
        self.path.write_text(json.dumps({"canvas": {"width": 500, "height": 600},
                                         "widgets": [{"type": "PushButton"}]}))
        old_rect = self.scene.sceneRect()
        add = self.scene.add_canvas_item
        calls = []
        def fail_once(item):
            calls.append(item)
            if len(calls) == 1:
                raise RuntimeError("scene insert")
            add(item)
        with patch.object(self.scene, "add_canvas_item", side_effect=fail_once):
            with self.assertRaises(RuntimeError):
                self.manager.load_to_scene(self.scene, str(self.path))
        self.assert_untouched()
        self.assertEqual(self.scene.sceneRect(), old_rect)

    def test_failed_atomic_save_keeps_file_and_dirty_state(self):
        self.path.write_text("previous contents")
        for operation in ("os.replace", "os.fsync"):
            with self.subTest(operation=operation), \
                 patch(f"app.core.project.{operation}", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    self.manager.save_from_scene(self.scene, str(self.path), "new name")
                self.assertEqual(self.path.read_text(), "previous contents")
                self.assert_untouched()
                self.assertIsNone(self.manager.current.file_path)
                self.assertEqual(list(Path(self.temp.name).iterdir()), [self.path])

    def test_successful_save_load_roundtrip_is_clean(self):
        self.manager.save_from_scene(self.scene, str(self.path), "测试")
        self.assertFalse(self.manager.is_dirty)
        self.scene.set_canvas_size(300, 300)
        # Loading should not emit edit events or leave the old selection active.
        edits = Mock()
        deselect = Mock()
        signalBus.canvasChanged.connect(edits)
        signalBus.widgetDeselected.connect(deselect)
        try:
            self.manager.load_to_scene(self.scene, str(self.path))
            self.assertEqual(self.manager.current.app_name, "测试")
            self.assertFalse(self.manager.is_dirty)
            self.assertEqual(self.scene.sceneRect().width(), 1200)
            self.assertEqual(self.scene.top_level_canvas_items()[0].properties["text"], "unsaved")
            edits.assert_not_called()
            deselect.assert_called_once()
        finally:
            signalBus.canvasChanged.disconnect(edits)
            signalBus.widgetDeselected.disconnect(deselect)


class WindowHarness(QWidget):
    """Only project actions; a native frameless window is not needed here."""
    _confirm_unsaved_changes = MainWindow._confirm_unsaved_changes
    _save_project = MainWindow._save_project
    _open_project = MainWindow._open_project
    _new_project = MainWindow._new_project
    _update_title = Mock()

    def __init__(self):
        super().__init__()
        self._project_mgr = ProjectManager()
        self._project_mgr.mark_dirty()
        self.designer_interface = SimpleNamespace(scene=DesignScene(), app_name="test")


class UnsavedPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = WindowHarness()
        self.addCleanup(self.window.deleteLater)

    def test_cancel_open_and_new_leave_project_untouched(self):
        original = self.window._project_mgr.current
        with patch("app.view.main_window.QMessageBox.question", return_value=QMessageBox.Cancel), \
             patch("app.view.main_window.QFileDialog.getOpenFileName") as dialog:
            self.window._open_project()
            self.window._new_project()
            dialog.assert_not_called()
        self.assertIs(self.window._project_mgr.current, original)
        self.assertTrue(self.window._project_mgr.is_dirty)

    def test_save_cancel_failure_and_success_control_navigation(self):
        for saved in (False, True):
            with patch("app.view.main_window.QMessageBox.question", return_value=QMessageBox.Save), \
                 patch.object(self.window, "_save_project", return_value=saved):
                self.assertEqual(self.window._confirm_unsaved_changes(), saved)
        with patch("app.view.main_window.QMessageBox.question", return_value=QMessageBox.Discard):
            self.assertTrue(self.window._confirm_unsaved_changes())

    def test_cancel_save_dialog_is_not_treated_as_success(self):
        with patch("app.view.main_window.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertFalse(self.window._save_project())
        self.assertTrue(self.window._project_mgr.is_dirty)

    def test_close_cancel_does_not_stop_preview(self):
        self.window.preview_interface = Mock()
        event = Mock()
        with patch("app.view.main_window.QMessageBox.question", return_value=QMessageBox.Cancel):
            MainWindow.closeEvent(self.window, event)
        event.ignore.assert_called_once()
        self.window.preview_interface._stop_preview.assert_not_called()

    def test_new_project_resets_scene_size_and_is_clean(self):
        self.window.designer_interface.scene.set_canvas_size(500, 600)
        with patch("app.view.main_window.QMessageBox.question", return_value=QMessageBox.Discard), \
             patch("app.view.main_window.InfoBar.success"):
            self.window._new_project()
        self.assertEqual(self.window.designer_interface.scene.sceneRect().width(), 1200)
        self.assertFalse(self.window._project_mgr.is_dirty)
