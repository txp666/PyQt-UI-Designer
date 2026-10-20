"""An exported project must retain images and arbitrary protocol keys on its own."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor, QImage

from app.core.code_generator import generate_project
from app.core.project import ProjectData


def image_widget(widget_id, path):
    return {
        "id": widget_id,
        "type": "ImageDisplay",
        "properties": {"imagePath": str(path)},
        "geometry": {"x": 0, "y": 0, "w": 120, "h": 80},
    }


def write_image(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor(color))
    if not image.save(str(path)):
        raise RuntimeError(f"Unable to create test image: {path}")


class ExportPortabilityTests(unittest.TestCase):
    def run_standalone(self, output, code, cwd):
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", code, str(output)],
            cwd=cwd,
            env={**os.environ, "PYTHONPATH": "", "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_absolute_and_nested_relative_images_survive_relocation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_dir = root / "original"
            relative_image = source_dir / "pictures" / "sample.png"
            absolute_image = source_dir / "other" / "sample.png"
            write_image(relative_image, "#ff0000")
            write_image(absolute_image, "#0000ff")
            project = ProjectData()
            project.file_path = str(source_dir / "project.uidp")
            project.widgets = [
                image_widget("absolute", absolute_image),
                {"id": "group", "type": "GroupBox", "children": [
                    image_widget("relative", "pictures/sample.png"),
                    image_widget("duplicate", "pictures/sample.png"),
                ]},
            ]
            original_widgets = copy.deepcopy(project.widgets)
            output = root / "export"
            generate_project(project, output, theme_mode="Light")
            self.assertEqual(project.widgets, original_widgets)
            self.assertEqual(len(list((output / "assets").iterdir())), 2)
            self.assertNotIn(str(source_dir), (output / "ui.py").read_text(encoding="utf-8"))

            moved = root / "moved"
            shutil.move(output, moved)
            shutil.rmtree(source_dir)
            # Keep the working directory separate from both the source and export.
            unrelated = root / "working-directory"
            unrelated.mkdir()
            code = r'''
import sys
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication
sys.path.insert(0, sys.argv[1])
app = QApplication([])
with ExitStack() as stack:
    if sys.platform == "darwin":
        from qframelesswindow.mac import MacFramelessWindow
        for name in ("updateFrameless", "_hideSystemTitleBar",
                     "setSystemTitleBarButtonVisible"):
            stack.enter_context(patch.object(
                MacFramelessWindow, name, lambda *args, **kwargs: None))
    from ui import MainUI
    window = MainUI()
    app.processEvents()
    for name, color in (("absolute", "#0000ff"), ("relative", "#ff0000"),
                        ("duplicate", "#ff0000")):
        widget = window.widgets[name]
        pixmap = widget._label.pixmap()
        assert pixmap is not None and not pixmap.isNull(), name
        assert pixmap.toImage().pixelColor(0, 0).name() == color, name
        assert Path(widget._path).is_relative_to(Path(sys.argv[1]).resolve())
    assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
print("RELOCATED_IMAGES_OK")
'''
            self.assertIn("RELOCATED_IMAGES_OK",
                          self.run_standalone(moved, code, unrelated))

    def test_unsaved_project_resolves_relative_images_from_working_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_image(root / "picture.png", "#12ab34")
            project = ProjectData()
            project.widgets = [image_widget("image", "picture.png")]
            with patch("app.core.code_generator.Path.cwd", return_value=root):
                generate_project(project, root / "export")
            exported = list((root / "export" / "assets").iterdir())
            self.assertEqual(len(exported), 1)
            self.assertEqual(exported[0].read_bytes(), (root / "picture.png").read_bytes())
            self.assertEqual(project.widgets[0]["properties"]["imagePath"], "picture.png")

    def test_missing_or_directory_image_fails_before_overwriting_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "export"
            output.mkdir()
            main = output / "main.py"
            main.write_text("existing application\n")
            write_image(root / "valid.png", "#ffffff")
            for invalid in ("missing.png", "."):
                with self.subTest(path=invalid):
                    project = ProjectData()
                    project.file_path = str(root / "source.uidp")
                    project.widgets = [
                        image_widget("valid", root / "valid.png"),
                        {"id": "group", "type": "GroupBox", "children": [
                            image_widget("invalid", invalid),
                        ]},
                    ]
                    before = copy.deepcopy(project.widgets)
                    with self.assertRaisesRegex(ValueError, "无法导出图片.*invalid"):
                        generate_project(project, output)
                    self.assertEqual(main.read_text(), "existing application\n")
                    self.assertFalse((output / "assets").exists())
                    self.assertEqual(project.widgets, before)

    def test_binding_keys_with_quotes_newlines_and_backslashes_run_standalone(self):
        keys = ["sensor's temp", 'line\n"pressure"\\value', "中文温度"]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "export"
            project = ProjectData()
            project.widgets = [
                {"id": f"label_{index}", "type": "Label",
                 "binding": {"parseMode": "键值匹配", "key": key}}
                for index, key in enumerate(keys)
            ]
            generate_project(project, output)
            for source in output.glob("*.py"):
                compile(source.read_text(encoding="utf-8"), str(source), "exec")
            code = f"KEYS = {keys!r}\n" + r'''
import sys
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0, sys.argv[1])
from serial_handler import SerialHandler
from data_binding import DataBinding
handler = SerialHandler()
widgets = {f"label_{index}": Mock() for index in range(len(KEYS))}
binding = DataBinding(SimpleNamespace(widgets=widgets), handler)
handler.dataReceived.emit({key: index + 10 for index, key in enumerate(KEYS)})
for index, widget in enumerate(widgets.values()):
    widget.setText.assert_called_once_with(str(index + 10))
assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
print("ARBITRARY_KEYS_OK")
'''
            self.assertIn("ARBITRARY_KEYS_OK", self.run_standalone(output, code, root))

    def test_imported_widget_ids_remain_literal_keys_in_standalone_runtime(self):
        from app.widgets.basic import register_basic_widgets
        from app.widgets.layout import register_layout_widgets
        register_basic_widgets()
        register_layout_widgets()
        ids = ["tab's\n页面\\", "label's\n值\\", "mode-control", "mode control",
               "button';not_python()#"]
        project = ProjectData.from_dict({"widgets": [{
            "id": ids[0], "type": "TabWidget",
            "properties": {"tabNames": "采集", "currentTab": 0},
            "children": [
                {"id": ids[1], "type": "Label", "binding": {"key": "sample"}},
                {"id": ids[2], "type": "ComboBox", "properties": {
                    "items": "A\nB", "commands": "A0\nA1", "sendOnSelect": True,
                }},
                {"id": ids[3], "type": "ComboBox", "properties": {
                    "items": "C\nD", "commands": "B0\nB1", "sendOnSelect": True,
                }},
                {"id": ids[4], "type": "PushButton", "properties": {
                    "command": "READ", "notify": True, "notifyType": "成功",
                }},
            ],
        }]})
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "export"
            generate_project(project, output)
            code = f"IDS = {ids!r}\n" + r'''
import sys
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PyQt5 import sip
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication
sys.path.insert(0, sys.argv[1])
app = QApplication([])
with ExitStack() as stack:
    if sys.platform == "darwin":
        from qframelesswindow.mac import MacFramelessWindow
        for name in ("updateFrameless", "_hideSystemTitleBar",
                     "setSystemTitleBarButtonVisible"):
            stack.enter_context(patch.object(
                MacFramelessWindow, name, lambda *args, **kwargs: None))
    import ui
    from serial_handler import SerialHandler
    from data_binding import DataBinding
    window = ui.MainUI()
    handler = SerialHandler()
    binding = DataBinding(window, handler)
    sent = []
    handler._port = SimpleNamespace(
        is_open=True, write=lambda data: sent.append(data) or len(data),
        close=lambda: None)
    assert set(window.widgets) == set(IDS)
    page = window.widgets[IDS[0]].widget(0)
    for name in IDS[1:]:
        assert window.widgets[name].parentWidget() is page
    handler.dataReceived.emit({"sample": 42})
    assert window.widgets[IDS[1]].text() == "42"
    window.widgets[IDS[2]].setCurrentIndex(1)
    window.widgets[IDS[3]].setCurrentIndex(1)
    notice = stack.enter_context(patch.object(ui.InfoBar, "success"))
    window.widgets[IDS[4]].click()
    notice.assert_called_once()
    assert sent == [b"A1\r\n", b"B1\r\n", b"READ\r\n"], sent
    handler.disconnect()
    assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
    # Mirror main.py's ordered shutdown rather than handing live Qt wrappers
    # to Python's atexit cleanup. Exercise a still-pending tab geometry update.
    geometry = window.widgets[IDS[0]]._designer_child_geometry
    geometry.schedule()
    assert geometry._pending
    window.deleteLater()
    handler.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(window) and sip.isdeleted(handler) and sip.isdeleted(geometry)
    app.processEvents()
print("ARBITRARY_WIDGET_IDS_OK")
'''
            self.assertIn("ARBITRARY_WIDGET_IDS_OK",
                          self.run_standalone(output, code, Path(folder)))

    def test_late_generation_failure_preserves_existing_export_and_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "export"
            project = ProjectData()
            generate_project(project, output)
            (output / "custom.py").write_text("# user extension\n", encoding="utf-8")
            before = {str(p.relative_to(output)): p.read_bytes()
                      for p in output.rglob("*") if p.is_file()}
            write_image(root / "new.png", "#012345")
            project.app_name = "New application"
            project.widgets = [
                image_widget("image", root / "new.png"),
                {"id": "value", "type": "Label",
                 "binding": {"parseMode": "HEX字节提取", "byteOffset": "invalid"}},
            ]
            with self.assertRaises(ValueError):
                generate_project(project, output)
            after = {str(p.relative_to(output)): p.read_bytes()
                     for p in output.rglob("*") if p.is_file()}
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
