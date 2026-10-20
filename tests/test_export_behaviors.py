"""Exercise exported controls through real Qt signals and serial payloads."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import sip
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.core.code_generator import generate_project
from app.core.data_binding import bindingEngine
from app.core.project import ProjectData
from app.widgets.basic import create_widget


_RUN_EXPORT = r"""
import runpy
import sys
import traceback
from contextlib import ExitStack
from unittest.mock import patch
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import InfoBar

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

def exercise_application():
    app = QApplication.instance()
    app.processEvents()
    window = next(w for w in app.topLevelWidgets() if hasattr(w, "widgets"))
    widgets = window.widgets
    serial = window._serial_handler
    port = MemoryPort()
    serial._port = port
    sent = []
    serial.dataSent.connect(sent.append)
    def click_switch(name):
        switch = widgets[name]._switch
        QTest.mouseClick(switch.indicator, Qt.LeftButton)
        app.processEvents()
        assert not errors, errors
    def check_payloads(expected):
        assert not errors, errors
        assert port.writes == expected, (port.writes, expected)
        assert sent == expected, (sent, expected)
__CHECKS__
    assert not errors, errors
    assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
    serial.disconnect()
    print("EXPORTED_CONTROLS_OK")
    return 0

with ExitStack() as stack:
    # Only bypass Cocoa's title-bar bridge: all Qt controls and signals are real.
    if sys.platform == "darwin":
        from qframelesswindow.mac import MacFramelessWindow
        for name in ("updateFrameless", "_hideSystemTitleBar",
                     "setSystemTitleBarButtonVisible"):
            stack.enter_context(patch.object(
                MacFramelessWindow, name, lambda *args, **kwargs: None))
    stack.enter_context(patch.object(QApplication, "exec", staticmethod(exercise_application)))
    runpy.run_path("main.py", run_name="__main__")
"""


def widget(widget_id, kind, properties=None, binding=None):
    data = {
        "id": widget_id, "type": kind, "properties": properties or {},
        "geometry": {"x": 10, "y": 10, "w": 250, "h": 150},
    }
    if binding:
        data["binding"] = binding
    return data


class ExportBehaviorTests(unittest.TestCase):
    def run_export(self, widgets, checks):
        project = ProjectData()
        project.widgets = widgets
        with tempfile.TemporaryDirectory() as folder:
            generate_project(project, folder, theme_mode="Light")
            for source in Path(folder).glob("*.py"):
                compile(source.read_text(encoding="utf-8"), str(source), "exec")
            script = _RUN_EXPORT.replace(
                "__CHECKS__", textwrap.indent(textwrap.dedent(checks).strip(), "    "))
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=folder,
                env={**os.environ, "PYTHONPATH": "", "QT_QPA_PLATFORM": "offscreen"},
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("EXPORTED_CONTROLS_OK", result.stdout)

    def test_switch_text_commands_notification_and_device_feedback(self):
        self.run_export([
            widget("switch", "ToggleSwitch", {
                "onCommand": "RUN", "offCommand": "STOP",
                "notify": True, "notifyTitle": "状态", "notifyContent": "已切换",
                "notifyDuration": -1,
            }, {"key": "running"}),
        ], r"""
            switch = widgets["switch"]._switch
            assert not switch.isChecked()
            click_switch("switch")
            assert switch.isChecked()
            click_switch("switch")
            assert not switch.isChecked()
            check_payloads([b"RUN\r\n", b"STOP\r\n"])
            notices = window.findChildren(InfoBar)
            assert len(notices) == 2
            assert all(n.title == "状态" and n.content == "已切换" for n in notices)
            serial.dataReceived.emit({"running": 1})
            assert switch.isChecked()
            serial.dataReceived.emit({"running": 0})
            assert not switch.isChecked()
            check_payloads([b"RUN\r\n", b"STOP\r\n"])
            assert len(window.findChildren(InfoBar)) == 2
            click_switch("switch")
            check_payloads([b"RUN\r\n", b"STOP\r\n", b"RUN\r\n"])
            assert len(window.findChildren(InfoBar)) == 3
        """)

    def test_switch_hex_and_modbus_clicks_send_correct_frames(self):
        self.run_export([
            widget("hex", "ToggleSwitch", {
                "commandMode": "HEX", "onCommand": "01", "offCommand": "00",
                "commandTemplate": "10 {value}", "frameHeader": "AA 55",
                "frameTail": "55 AA",
            }),
            widget("modbus", "ToggleSwitch", {
                "commandMode": "Modbus", "mbSlave": 2, "mbAddress": 7,
            }),
        ], r"""
            click_switch("hex")
            click_switch("hex")
            click_switch("modbus")
            click_switch("modbus")
            check_payloads([
                bytes.fromhex("aa55100155aa"), bytes.fromhex("aa55100055aa"),
                bytes.fromhex("02050007ff003dc8"), bytes.fromhex("0205000700007c38"),
            ])
        """)

    def test_switch_notification_without_command_and_empty_command_are_safe(self):
        self.run_export([
            widget("notify_only", "ToggleSwitch", {
                "notify": True, "notifyTitle": "通知", "notifyDuration": -1,
            }),
            widget("one_way", "ToggleSwitch", {"onCommand": "RUN"}),
        ], r"""
            click_switch("notify_only")
            check_payloads([])
            assert len(window.findChildren(InfoBar)) == 1
            click_switch("one_way")
            click_switch("one_way")
            check_payloads([b"RUN\r\n"])
        """)

    def test_numeric_controls_send_default_and_custom_templates(self):
        widgets = []
        for kind in ("Slider", "SpinBox"):
            for template in ("{value}", "SET {value};{value}"):
                name = kind + ("_default" if template == "{value}" else "_template")
                widgets.append(widget(name, kind, {
                    "minimum": -100, "maximum": 200, "value": 17,
                    "suffix": "kPa", "sendOnChange": True,
                    "commandTemplate": template, "commandNewline": "\\n",
                }, {"key": name}))
        self.run_export(widgets, r"""
            expected = []
            for kind in ("Slider", "SpinBox"):
                for suffix in ("_default", "_template"):
                    name = kind + suffix
                    control = widgets[name]
                    assert control.value() == 17
                    if kind == "SpinBox":
                        assert control.suffix() == " kPa"
                    # A keyboard gesture goes through the real Qt valueChanged signal.
                    QTest.keyClick(control, Qt.Key_Right if kind == "Slider" else Qt.Key_Up)
                    app.processEvents()
                    assert control.value() == 18
                    expected.append(b"18\n" if suffix == "_default" else b"SET 18;18\n")
                    check_payloads(expected)
                    serial.dataReceived.emit({name: -12})
                    assert control.value() == -12
                    check_payloads(expected)
                    QTest.keyClick(control, Qt.Key_Right if kind == "Slider" else Qt.Key_Up)
                    app.processEvents()
                    assert control.value() == -11
                    expected.append(b"-11\n" if suffix == "_default" else b"SET -11;-11\n")
                    check_payloads(expected)
        """)

    def test_numeric_controls_hex_string_and_packed_modes(self):
        widgets = []
        for kind in ("Slider", "SpinBox"):
            for data_type in ("HEX字符串", "uint16"):
                widgets.append(widget(kind + data_type, kind, {
                    "commandMode": "HEX", "sendOnChange": True, "value": 0,
                    "dataType": data_type, "byteOrder": "小端(LE)",
                    "frameHeader": "AA", "frameTail": "55",
                }))
        self.run_export(widgets, r"""
            expected = []
            for kind in ("Slider", "SpinBox"):
                for data_type in ("HEX字符串", "uint16"):
                    control = widgets[kind + data_type]
                    control.setValue(10)
                    expected.append(bytes.fromhex("aa1055" if data_type == "HEX字符串"
                                                   else "aa0a0055"))
                    check_payloads(expected)
        """)

    def test_slider_feedback_moves_handle_without_echo_in_both_orientations(self):
        self.run_export([
            widget("slider", "Slider", {
                "minimum": 20, "maximum": 80, "value": 50, "sendOnChange": True,
            }, {"key": "setpoint"}),
        ], r"""
            slider = widgets["slider"]
            for orientation in (Qt.Horizontal, Qt.Vertical):
                slider.setOrientation(orientation)
                slider.resize(320, 36) if orientation == Qt.Horizontal else slider.resize(36, 320)
                app.processEvents()
                slider.setValue(65)
                expected_position = slider.handle.pos()
                slider.setValue(30)
                assert slider.handle.pos() != expected_position
                port.writes.clear()
                sent.clear()
                serial.dataReceived.emit({"setpoint": 65})
                assert slider.value() == 65
                assert slider.handle.pos() == expected_position, (
                    orientation, slider.handle.pos(), expected_position)
                check_payloads([])
                slider.setValue(66)
                check_payloads([b"66\r\n"])
        """)

    def test_progress_ring_receives_key_json_hex_and_modbus_bindings(self):
        self.run_export([
            widget("key", "ProgressRingDisplay", {"maximum": 200, "value": 11},
                   {"key": "progress"}),
            widget("json", "ProgressRingDisplay",
                   binding={"parseMode": "JSON路径", "jsonPath": "state.progress"}),
            widget("hex", "ProgressRingDisplay", binding={
                "parseMode": "HEX字节提取", "frameHeader": "AA55",
                "frameTail": "55AA", "dataType": "uint16"}),
            widget("modbus", "ProgressRingDisplay", binding={
                "parseMode": "Modbus", "mbRegIndex": 2, "mbSlaveFilter": 1,
                "mbFcFilter": 3}),
            widget("bar", "ProgressBar", binding={"key": "progress"}),
        ], r"""
            assert widgets["key"]._ring.maximum() == 200
            assert widgets["key"]._ring.value() == 11
            assert widgets["key"]._ring.text() == "5%"
            serial.dataReceived.emit({"progress": 45, "state": {"progress": 46}})
            serial.rawReceived.emit(bytes.fromhex("aa5500"))
            serial.rawReceived.emit(bytes.fromhex("2f55aa"))
            serial.dataReceived.emit({"slave": 1, "fc": 3, "reg2": 48})
            for name, value, maximum, percentage in (
                    ("key", 45, 200, "22%"), ("json", 46, 100, "46%"),
                    ("hex", 47, 100, "47%"), ("modbus", 48, 100, "48%")):
                ring = widgets[name]
                assert ring._ring.value() == value, (name, ring._ring.value())
                assert ring._ring.maximum() == maximum
                assert ring._ring.isTextVisible()
                assert ring._ring.text() == percentage, (name, ring._ring.text())
            assert widgets["bar"].value() == 45
            serial.dataReceived.emit({"slave": 2, "fc": 3, "reg2": 99})
            assert widgets["modbus"]._ring.value() == 48
            check_payloads([])
        """)


class PreviewBindingBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_device_feedback_updates_interactive_controls_without_user_signals(self):
        engine = bindingEngine
        previous = (engine._bindings, engine._widget_map, engine._latest_data, engine._active)
        self.addCleanup(lambda: (
            setattr(engine, "_bindings", previous[0]), setattr(engine, "_widget_map", previous[1]),
            setattr(engine, "_latest_data", previous[2]), setattr(engine, "_active", previous[3])))
        engine._bindings, engine._widget_map, engine._latest_data = [], {}, {}
        data = [widget("switch", "ToggleSwitch", binding={"key": "running"}),
                widget("slider", "Slider", binding={"key": "setting"}),
                widget("spin", "SpinBox", binding={"key": "setting"})]
        signals = []
        for entry in data:
            control = create_widget(entry["type"], {})
            self.addCleanup(lambda w=control: sip.delete(w) if not sip.isdeleted(w) else None)
            engine.register_widget(entry["id"], control)
            if entry["type"] == "ToggleSwitch":
                control._switch.checkedChanged.connect(
                    lambda value: signals.append(("switch", value)))
            else:
                control.valueChanged.connect(
                    lambda value, name=entry["id"]: signals.append((name, value)))
        engine.load_bindings_from_project(data)
        engine.start()
        engine._on_data({"running": 1, "setting": 31})
        self.assertTrue(engine._widget_map["switch"]._switch.isChecked())
        self.assertEqual(engine._widget_map["slider"].value(), 31)
        self.assertEqual(engine._widget_map["spin"].value(), 31)
        self.assertEqual(signals, [])
        engine._on_data({"setting": "unavailable"})
        self.assertEqual(engine._widget_map["slider"].value(), 31)
        self.assertEqual(engine._widget_map["spin"].value(), 31)
        engine._widget_map["switch"]._switch.toggleChecked()
        for name in ("slider", "spin"):
            engine._widget_map[name].setValue(32)
        self.assertEqual(signals, [("switch", False), ("slider", 32), ("spin", 32)])

    def test_slider_feedback_moves_handle_in_both_orientations(self):
        from app.core.data_binding import BindingEntry
        slider = create_widget("Slider", {"minimum": 20, "maximum": 80, "value": 50})
        self.addCleanup(lambda: sip.delete(slider) if not sip.isdeleted(slider) else None)
        binding = BindingEntry("slider", "value", type_name="Slider")
        signals = []
        slider.valueChanged.connect(signals.append)
        slider.show()
        for orientation in (Qt.Horizontal, Qt.Vertical):
            with self.subTest(orientation=orientation):
                slider.setOrientation(orientation)
                slider.resize(320, 36) if orientation == Qt.Horizontal else slider.resize(36, 320)
                self.app.processEvents()
                slider.setValue(65)
                expected_position = slider.handle.pos()
                slider.setValue(30)
                self.assertNotEqual(slider.handle.pos(), expected_position)
                signals.clear()
                bindingEngine._apply_to_widget(slider, binding, 65)
                self.assertEqual(slider.value(), 65)
                self.assertEqual(slider.handle.pos(), expected_position)
                self.assertEqual(signals, [])
                slider.setValue(66)
                self.assertEqual(signals, [66])


if __name__ == "__main__":
    unittest.main()
