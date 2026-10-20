"""Regressions for host/export parity and platform-specific packaging."""
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QKeyEvent, QWheelEvent
from PyQt5.QtWidgets import QApplication

from app.common.build_support import archive_build, build_nuitka_command
from app.core import serial_manager
from app.core.code_generator import _gen_serial_handler, generate_project
from app.core.project import ProjectData


class SerialPortTests(unittest.TestCase):
    def test_host_and_export_preserve_posix_paths(self):
        generated = {}
        exec(_gen_serial_handler({}), generated)
        for platform, device, expected in (
            ("darwin", "/dev/cu.usbserial-AbC123", "/dev/cu.usbserial-AbC123"),
            ("linux", "/dev/ttyUSB0", "/dev/ttyUSB0"),
        ):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform), \
                 patch("serial.tools.list_ports.comports", return_value=[
                     SimpleNamespace(device=device, description="USB UART")
                 ]):
                self.assertEqual(serial_manager._list_all_ports()[0]["port"], expected)
                self.assertEqual(generated["_list_all_ports"]()[0][0], expected)

    def test_windows_keeps_com_normalization_and_numeric_order(self):
        generated = {}
        exec(_gen_serial_handler({}), generated)
        fake_registry = SimpleNamespace(HKEY_LOCAL_MACHINE=0,
                                        OpenKey=lambda *args: (_ for _ in ()).throw(OSError()))
        with patch.object(sys, "platform", "win32"), \
             patch.dict(sys.modules, {"winreg": fake_registry}), \
             patch("serial.tools.list_ports.comports", return_value=[
                 SimpleNamespace(device="com10", description="ten"),
                 SimpleNamespace(device="com2", description="two"),
             ]):
            self.assertEqual([p["port"] for p in serial_manager._list_all_ports()],
                             ["COM2", "COM10"])
            self.assertEqual([p[0] for p in generated["_list_all_ports"]()],
                             ["COM2", "COM10"])


class PackagingTests(unittest.TestCase):
    def test_platform_flags_and_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for name in ("logo.ico", "logo.png"):
                (root / name).touch()
            for platform in ("darwin", "win32", "linux"):
                args = build_nuitka_command(root, ["python"], "测试应用", platform=platform)
                self.assertIn(f"--include-data-files={root / 'logo.png'}=logo.png", args)
                self.assertEqual(any(arg.startswith("--windows-") for arg in args),
                                 platform == "win32")
                self.assertEqual("--macos-create-app-bundle" in args, platform == "darwin")
                self.assertNotIn("--mingw64", args)  # Compiler follows the selected Python.

    def test_missing_output_never_reuses_old_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / "build" / "Old.app"
            old.mkdir(parents=True)
            with self.assertRaises(FileNotFoundError):
                archive_build(folder, "Old", platform="darwin")
            self.assertTrue(old.exists())

    @unittest.skipUnless(sys.platform == "darwin", "macOS ditto preserves app bundles")
    def test_mac_archive_round_trip_keeps_links_and_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / "build/main.app/Contents/MacOS"
            bundle.mkdir(parents=True)
            binary = bundle / "main"
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o755)
            (bundle / "linked").symlink_to("main")
            _, archive = archive_build(folder, "测试 App")
            extracted = Path(folder) / "unpacked"
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), str(extracted)],
                           check=True)
            target = extracted / "测试 App.app/Contents/MacOS"
            self.assertTrue((target / "linked").is_symlink())
            self.assertTrue((target / "main").stat().st_mode & stat.S_IXUSR)

    def test_empty_project_export_is_runnable_python_with_png_icon(self):
        with tempfile.TemporaryDirectory() as folder:
            generate_project(ProjectData(), folder)
            for source in Path(folder).glob("*.py"):
                compile(source.read_text(encoding="utf-8"), str(source), "exec")
            self.assertTrue((Path(folder) / "logo.png").is_file())


class CanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from app.widgets.basic import register_basic_widgets
        register_basic_widgets()

    def setUp(self):
        from app.designer.canvas import DesignScene, DesignView
        self.scene = DesignScene()
        self.view = DesignView(self.scene)

    def tearDown(self):
        self.view.close()

    def test_mac_delete_key_removes_selected_widget(self):
        from app.designer.canvas_item import CanvasItem
        item = CanvasItem("PushButton", {})
        self.scene.add_canvas_item(item)
        item.setSelected(True)
        with patch.object(sys, "platform", "darwin"):
            self.view.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Backspace, Qt.NoModifier))
        self.assertEqual(self.scene.all_canvas_items(), [])

    def test_mac_scroll_pans_and_command_scroll_zooms(self):
        def wheel(modifier, delta=120):
            return QWheelEvent(QPointF(100, 100), QPointF(100, 100),
                               QPoint(), QPoint(0, delta), Qt.NoButton,
                               modifier, Qt.NoScrollPhase, False)
        with patch.object(sys, "platform", "darwin"):
            self.view.wheelEvent(wheel(Qt.NoModifier))
            self.assertEqual(self.view._zoom, 1.0)
            self.view.wheelEvent(wheel(Qt.ControlModifier))
            self.assertAlmostEqual(self.view._zoom, 1.15)
            self.view.wheelEvent(wheel(Qt.ControlModifier, 0))
            self.assertAlmostEqual(self.view._zoom, 1.15)


if __name__ == "__main__":
    unittest.main()
