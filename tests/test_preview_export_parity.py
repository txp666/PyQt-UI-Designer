"""The preview and standalone export must preserve controls and wire bytes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.code_generator import generate_project
from app.core.project import ProjectData


_ROOT = Path(__file__).resolve().parent.parent
_RUN_APPLICATION = r"""
import json
import os
import runpy
import sys
import traceback
from contextlib import ExitStack
from unittest.mock import patch
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

errors = []
def capture_exception(kind, value, tb):
    errors.append(repr(value))
    traceback.print_exception(kind, value, tb)
sys.excepthook = capture_exception

class MemoryPort:
    is_open = True
    def __init__(self):
        self.writes = []
    def write(self, payload):
        self.writes.append(payload)
        return len(payload)
    def close(self):
        self.is_open = False

def exercise(window, widgets, serial):
    app = QApplication.instance()
    app.processEvents()
    port = MemoryPort()
    serial._port = port
    sent = []
    serial.dataSent.connect(sent.append)
    def check_payloads(expected):
        assert not errors, errors
        assert port.writes == expected, (port.writes, expected)
        assert sent == expected, (sent, expected)
    def click_switch(name):
        switch = widgets[name]._switch
        QTest.mouseClick(switch.indicator, Qt.LeftButton)
        app.processEvents()
        assert not errors, errors
    check_payloads([])
__CHECKS__
    assert not errors, errors
    serial.disconnect()
    print("PREVIEW_EXPORT_PARITY_OK")
    return 0

if os.environ["APPLICATION_MODE"] == "preview":
    sys.path.insert(0, os.environ["DESIGNER_ROOT"])
    from app.core.project import ProjectData
    from app.core.serial_manager import serialManager
    from app.view.preview_interface import PreviewCanvas
    app = QApplication([])
    project = ProjectData()
    project.widgets = json.loads(os.environ["PROJECT_WIDGETS"])
    window = PreviewCanvas()
    window.build_from_project(project)
    window.show()
    widgets = {item["id"]: widget for item, widget
               in zip(project.widgets, window._widgets)}
    exercise(window, widgets, serialManager)
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
else:
    def exercise_export():
        app = QApplication.instance()
        window = next(w for w in app.topLevelWidgets() if hasattr(w, "widgets"))
        result = exercise(window, window.widgets, window._comm_hub.serial)
        assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
        return result
    with ExitStack() as stack:
        # Cocoa's native title-bar bridge is unavailable with Qt's offscreen plugin.
        if sys.platform == "darwin":
            from qframelesswindow.mac import MacFramelessWindow
            for name in ("updateFrameless", "_hideSystemTitleBar",
                         "setSystemTitleBarButtonVisible"):
                stack.enter_context(patch.object(
                    MacFramelessWindow, name, lambda *args, **kwargs: None))
        stack.enter_context(patch.object(
            QApplication, "exec", staticmethod(exercise_export)))
        runpy.run_path("main.py", run_name="__main__")
"""


def control(name, kind, properties, row=0):
    return {
        "id": name, "type": kind, "properties": properties,
        "geometry": {"x": 20, "y": 20 + 60 * row, "w": 280, "h": 40},
    }


class PreviewExportParityTests(unittest.TestCase):
    def run_both(self, widgets, checks):
        project = ProjectData()
        project.widgets = widgets
        script = _RUN_APPLICATION.replace(
            "__CHECKS__", textwrap.indent(textwrap.dedent(checks).strip(), "    "))
        with tempfile.TemporaryDirectory() as folder:
            generate_project(project, folder, theme_mode="Light")
            for mode in ("preview", "export"):
                with self.subTest(mode=mode):
                    result = subprocess.run(
                        [sys.executable, "-c", script], cwd=folder,
                        env={
                            **os.environ, "PYTHONPATH": "",
                            "QT_QPA_PLATFORM": "offscreen",
                            "APPLICATION_MODE": mode, "DESIGNER_ROOT": str(_ROOT),
                            "PROJECT_WIDGETS": json.dumps(widgets),
                        },
                        capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("PREVIEW_EXPORT_PARITY_OK", result.stdout)

    def test_initial_states_and_real_input_preserve_command_behavior(self):
        self.run_both([
            control("disabled", "PushButton", {
                "text": "禁止操作", "enabled": False, "command": "DANGER",
            }),
            control("enabled", "PushButton", {
                "text": "读取", "enabled": True, "command": "READ",
            }, 1),
            control("readonly", "LineEdit", {
                "text": "CONFIRMED", "readOnly": True, "placeholderText": "固定值",
            }, 2),
            control("editable", "LineEdit", {
                "text": "READY", "readOnly": False, "sendOnEnter": True,
            }, 3),
            control("selection", "ComboBox", {
                "items": "Low\nHigh", "currentIndex": 1,
                "sendOnSelect": True, "commands": "LOW\nHIGH",
            }, 4),
        ], r"""
            disabled = widgets["disabled"]
            assert disabled.text() == "禁止操作"
            assert not disabled.isEnabled()
            QTest.mouseClick(disabled, Qt.LeftButton)
            app.processEvents()
            check_payloads([])

            readonly = widgets["readonly"]
            assert readonly.text() == "CONFIRMED"
            assert readonly.placeholderText() == "固定值"
            assert readonly.isReadOnly()
            readonly.setFocus()
            readonly.selectAll()
            QTest.keyClicks(readonly, "CHANGED")
            QTest.keyClick(readonly, Qt.Key_Backspace)
            assert readonly.text() == "CONFIRMED"
            check_payloads([])

            selection = widgets["selection"]
            assert selection.currentIndex() == 1
            assert selection.currentText() == "High"
            check_payloads([])

            assert widgets["enabled"].isEnabled()
            QTest.mouseClick(widgets["enabled"], Qt.LeftButton)
            check_payloads([b"READ\r\n"])
            editable = widgets["editable"]
            assert editable.text() == "READY"
            assert not editable.isReadOnly()
            editable.setFocus()
            editable.selectAll()
            QTest.keyClicks(editable, "GET")
            QTest.keyClick(editable, Qt.Key_Return)
            assert editable.text() == "GET"
            check_payloads([b"READ\r\n", b"GET\r\n"])
            selection.setCurrentIndex(0)
            check_payloads([b"READ\r\n", b"GET\r\n", b"LOW\r\n"])
        """)

    def test_default_selection_handles_empty_trimmed_and_out_of_range_items(self):
        widgets = []
        for row, (name, items, index) in enumerate((
            ("trimmed", "  Low \n\n High  \n", 1),
            ("negative", "Low\nHigh", -1),
            ("overflow", "Low\nHigh", 99),
            ("empty", "\n  \n", 0),
        )):
            widgets.append(control(name, "ComboBox", {
                "items": items, "currentIndex": index, "sendOnSelect": True,
            }, row))
        self.run_both(widgets, r"""
            for name, expected_index, expected_text in (
                ("trimmed", 1, "High"), ("negative", 0, "Low"),
                ("overflow", 0, "Low"), ("empty", -1, ""),
            ):
                selection = widgets[name]
                assert selection.currentIndex() == expected_index, name
                assert selection.currentText() == expected_text, name
            check_payloads([])
        """)

    def test_modbus_switch_always_writes_coils_in_preview_and_export(self):
        self.run_both([
            control("normal", "ToggleSwitch", {
                "commandMode": "Modbus", "mbSlave": 2, "mbAddress": 7,
            }),
            control("legacy", "ToggleSwitch", {
                "commandMode": "Modbus", "mbSlave": 2, "mbAddress": 7,
                "mbFunc": "06 写单寄存器",
            }, 1),
        ], r"""
            expected = []
            for name in ("normal", "legacy"):
                assert not widgets[name]._switch.isChecked()
                click_switch(name)
                assert widgets[name]._switch.isChecked()
                expected.append(bytes.fromhex("02050007ff003dc8"))
                check_payloads(expected)
                click_switch(name)
                assert not widgets[name]._switch.isChecked()
                expected.append(bytes.fromhex("0205000700007c38"))
                check_payloads(expected)
        """)
