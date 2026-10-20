"""Real window actions must retire stale preview commands without losing cancellations."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_RUN_WINDOW = r"""
import json
from pathlib import Path
import sys
import tempfile
from contextlib import ExitStack
from unittest.mock import patch
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox
from qfluentwidgets import InfoBar
from app.core.data_binding import bindingEngine
from app.core.project import ProjectData
from app.core.serial_manager import serialManager
from app.view.main_window import MainWindow

errors = []
sys.excepthook = lambda kind, value, traceback: errors.append(repr(value))

class MemoryPort:
    def __init__(self):
        self.sent = []
        self.is_open = True
    def write(self, data):
        self.sent.append(data)
        return len(data)
    def close(self):
        self.is_open = False

app = QApplication([])
with ExitStack() as stack, tempfile.TemporaryDirectory() as folder:
    if sys.platform == "darwin":
        from qframelesswindow.mac import MacFramelessWindow
        for name in ("updateFrameless", "_hideSystemTitleBar",
                     "setSystemTitleBarButtonVisible"):
            stack.enter_context(patch.object(MacFramelessWindow, name,
                                            lambda *args, **kwargs: None))
    for name in ("success", "error", "warning"):
        stack.enter_context(patch.object(InfoBar, name))
    window = MainWindow()
    root = Path(folder)
    for name, command in (("A", "OLD_WRITE"), ("B", "NEW_READ")):
        project = ProjectData()
        project.widgets = [
            {"id": "button", "type": "PushButton",
             "geometry": {"x": 10, "y": 10, "w": 160, "h": 36},
             "properties": {"text": name, "command": command}},
            {"id": "value", "type": "Label", "binding": {"key": "value"},
             "geometry": {"x": 10, "y": 60, "w": 160, "h": 36}},
        ]
        (root / (name + ".uidp")).write_text(
            json.dumps(project.to_dict()), encoding="utf-8")
    window._project_mgr.load_to_scene(window.designer_interface.scene, str(root / "A.uidp"))
    window._sync_preview()
    preview = window.preview_interface
    preview._start_preview()
    port = MemoryPort()
    serialManager._port = port
    original = preview._preview_canvas._widgets[0]
    original.click()
    assert port.sent == [b"OLD_WRITE\r\n"]
    assert preview._running and bindingEngine._active
__CHECKS__
    assert not errors, errors
    window._project_mgr._dirty = False
    window.close()
    # QWidget.close() only hides the window. Destroy Qt objects while the
    # application and patched native bridge are still alive.
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not errors, errors
    print("PREVIEW_PROJECT_LIFECYCLE_OK")
"""


class PreviewProjectLifecycleTests(unittest.TestCase):
    def exercise(self, checks):
        script = _RUN_WINDOW.replace(
            "__CHECKS__", textwrap.indent(textwrap.dedent(checks).strip(), "    "))
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=_ROOT,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                 "PYTHONFAULTHANDLER": "1"},
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PREVIEW_PROJECT_LIFECYCLE_OK", result.stdout)

    def test_opening_another_project_disconnects_and_only_new_commands_can_restart(self):
        self.exercise("""
            with patch.object(QFileDialog, "getOpenFileName",
                              return_value=(str(root / "B.uidp"), "")):
                window._open_project()
            assert not preview._running and not bindingEngine._active
            assert not port.is_open and not serialManager.is_connected
            assert preview._run_btn.isEnabled() and not preview._stop_btn.isEnabled()
            assert preview._preview_canvas._widgets == []
            original.click()
            assert port.sent == [b"OLD_WRITE\\r\\n"]
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
            # Restart directly on the existing page; it must refresh project data.
            preview._start_preview()
            current = preview._preview_canvas._widgets[0]
            assert current.text() == "B"
            new_port = MemoryPort()
            serialManager._port = new_port
            current.click()
            serialManager.dataReceived.emit({"value": 42})
            assert new_port.sent == [b"NEW_READ\\r\\n"]
            assert preview._preview_canvas._widgets[1].text() == "42"
        """)

    def test_new_project_stops_preview_and_cannot_restart_the_old_design(self):
        self.exercise("""
            window._new_project()
            assert window._project_mgr.current.widgets == []
            assert not preview._running and not bindingEngine._active
            assert not port.is_open and not serialManager.is_connected
            assert preview._preview_canvas._widgets == []
            original.click()
            preview._start_preview()
            assert not preview._running and port.sent == [b"OLD_WRITE\\r\\n"]
        """)

    def test_property_editor_change_stops_old_commands_and_refreshes_on_run(self):
        self.exercise("""
            editor = window.designer_interface._prop_editor
            editor._on_widget_selected("button")
            editor._editors["command"].setText("UPDATED")
            assert window._project_mgr.is_dirty
            assert not preview._running and not bindingEngine._active
            assert not port.is_open and not serialManager.is_connected
            assert preview._project_data is None
            original.click()
            assert port.sent == [b"OLD_WRITE\\r\\n"]
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
            preview._start_preview()
            new_port = MemoryPort()
            serialManager._port = new_port
            preview._preview_canvas._widgets[0].click()
            assert new_port.sent == [b"UPDATED\\r\\n"]
        """)

    def test_cancelled_and_failed_open_preserve_running_widgets_connection_and_bindings(self):
        self.exercise("""
            document = window._project_mgr.current
            window._project_mgr.mark_dirty()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel), \\
                 patch.object(QFileDialog, "getOpenFileName") as dialog:
                window._open_project()
                window._new_project()
                dialog.assert_not_called()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Save), \\
                 patch.object(window, "_save_project", return_value=False), \\
                 patch.object(QFileDialog, "getOpenFileName") as dialog:
                window._open_project()
                dialog.assert_not_called()
            window._project_mgr._dirty = False
            with patch.object(QFileDialog, "getOpenFileName", return_value=("", "")):
                window._open_project()
            (root / "invalid.uidp").write_text("{", encoding="utf-8")
            with patch.object(QFileDialog, "getOpenFileName",
                              return_value=(str(root / "invalid.uidp"), "")):
                window._open_project()
            from app.designer.canvas_item import CanvasItem
            with patch.object(QFileDialog, "getOpenFileName",
                              return_value=(str(root / "B.uidp"), "")), \\
                 patch.object(CanvasItem, "from_dict", side_effect=ValueError("bad widget")):
                window._open_project()
            assert window._project_mgr.current is document
            assert preview._running and bindingEngine._active
            assert serialManager.is_connected and port.is_open
            assert preview._preview_canvas._widgets[0] is original
            serialManager.dataReceived.emit({"value": 17})
            assert preview._preview_canvas._widgets[1].text() == "17"
            original.click()
            assert port.sent == [b"OLD_WRITE\\r\\n", b"OLD_WRITE\\r\\n"]
        """)

    def test_unchanged_sync_and_save_keep_runtime_but_same_object_changes_invalidate(self):
        self.exercise("""
            window._sync_preview()
            assert window._save_project()
            window._sync_preview()
            assert preview._running and serialManager.is_connected
            assert preview._preview_canvas._widgets[0] is original
            document = window._project_mgr.current
            assert preview._project_data is not document
            document.widgets[0]["properties"]["command"] = "DIFFERENT"
            preview.set_project_data(document)
            assert not preview._running and not bindingEngine._active
            assert not serialManager.is_connected and not port.is_open
            assert preview._project_data.widgets[0]["properties"]["command"] == "DIFFERENT"
        """)

    def test_pack_captures_latest_scene_without_starting_or_reconnecting_preview(self):
        self.exercise("""
            editor = window.designer_interface._prop_editor
            editor._on_widget_selected("button")
            editor._editors["command"].setText("PACK_UPDATED")
            output = root / "packed-project"
            with patch.object(QFileDialog, "getExistingDirectory", return_value=str(output)), \\
                 patch("app.view.preview_interface.NuitkaPackDialog") as dialog:
                preview._on_pack()
                dialog.return_value.exec_.assert_called_once()
            source = (output / "ui.py").read_text(encoding="utf-8")
            assert "PACK_UPDATED" in source and "OLD_WRITE" not in source
            assert not preview._running and not serialManager.is_connected
            assert not port.is_open and port.sent == [b"OLD_WRITE\\r\\n"]
        """)
