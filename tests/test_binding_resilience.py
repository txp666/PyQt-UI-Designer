"""Bad device fields must not interrupt host or standalone Qt bindings."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import sip
from PyQt5.QtWidgets import QApplication

from app.common.signal_bus import signalBus
from app.core.code_generator import generate_project
from app.core.data_binding import bindingEngine
from app.core.project import ProjectData
from app.widgets.basic import create_widget


def bound(kind, name, binding=None, properties=None):
    return {
        "id": name, "type": kind, "properties": properties or {},
        "geometry": {"x": 10, "y": 10, "w": 240, "h": 150},
        "binding": binding or {"key": name},
    }


_CHECK_HELPERS = """
changes = []
for name, control in widgets.items():
    if hasattr(control, "_switch"):
        control._switch.checkedChanged.connect(lambda v: changes.append(v))
    elif hasattr(control, "valueChanged") and not hasattr(control, "set_value"):
        control.valueChanged.connect(lambda v: changes.append(v))

def numeric(name):
    control = widgets[name]
    if hasattr(control, "_ring"): return control._ring.value()
    if hasattr(control, "value"): return control.value()
    return control._value

def text(name):
    control = widgets[name]
    if hasattr(control, "text"): return control.text()
    return (control._value_label if hasattr(control, "_value_label")
            else control._value).text()

def emit_data(data):
    serial.dataReceived.emit(data)
    assert not errors, errors

def emit_raw(data):
    serial.rawReceived.emit(data)
    assert not errors, errors
"""


_RUN_EXPORT = """
import runpy
import sys
import struct
from contextlib import ExitStack
from unittest.mock import patch
from PyQt5.QtWidgets import QApplication

errors = []
sys.excepthook = lambda kind, value, tb: errors.append(repr(value))

def exercise():
    app = QApplication.instance()
    app.processEvents()
    window = next(w for w in app.topLevelWidgets() if hasattr(w, "widgets"))
    widgets = window.widgets
    serial = window._serial_handler
__HELPERS__
__CHECKS__
    assert not errors, errors
    assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
    serial.disconnect()
    print("BINDING_RESILIENCE_OK")
    return 0

with ExitStack() as stack:
    if sys.platform == "darwin":
        from qframelesswindow.mac import MacFramelessWindow
        for name in ("updateFrameless", "_hideSystemTitleBar",
                     "setSystemTitleBarButtonVisible"):
            stack.enter_context(patch.object(
                MacFramelessWindow, name, lambda *args, **kwargs: None))
    stack.enter_context(patch.object(QApplication, "exec", staticmethod(exercise)))
    runpy.run_path("main.py", run_name="__main__")
"""


class BindingResilienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def run_both(self, specifications, checks):
        import struct
        widgets = {spec["id"]: create_widget(spec["type"], spec["properties"])
                   for spec in specifications}
        bindingEngine.clear()
        bindingEngine.load_bindings_from_project(specifications)
        for name, widget in widgets.items():
            bindingEngine.register_widget(name, widget)
        bindingEngine.start()
        errors = []
        namespace = {
            "widgets": widgets, "errors": errors, "struct": struct,
            "serial": SimpleNamespace(dataReceived=signalBus.serialDataReceived,
                                      rawReceived=signalBus.serialRawReceived),
        }
        try:
            with patch.object(sys, "excepthook",
                              lambda kind, value, tb: errors.append(repr(value))):
                exec(_CHECK_HELPERS + textwrap.dedent(checks), namespace)
                self.assertFalse(errors)
        finally:
            bindingEngine.stop()
            bindingEngine.clear()
            for widget in widgets.values():
                sip.delete(widget)

        project = ProjectData()
        project.widgets = specifications
        with tempfile.TemporaryDirectory() as folder:
            generate_project(project, folder, theme_mode="Light")
            for path in Path(folder).glob("*.py"):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            script = _RUN_EXPORT.replace(
                "__HELPERS__", textwrap.indent(_CHECK_HELPERS.strip(), "    ")
            ).replace("__CHECKS__", textwrap.indent(textwrap.dedent(checks).strip(), "    "))
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=folder,
                env={**os.environ, "PYTHONPATH": "", "QT_QPA_PLATFORM": "offscreen"},
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("BINDING_RESILIENCE_OK", result.stdout)

    def test_invalid_numeric_field_does_not_stop_siblings_or_later_frames(self):
        kinds = ("Slider", "SpinBox", "ProgressBar", "ProgressRingDisplay", "GaugeMeter")
        self.run_both(
            [bound(kind, kind) for kind in kinds] + [bound("Label", "good")],
            """
            kinds = ("Slider", "SpinBox", "ProgressBar", "ProgressRingDisplay", "GaugeMeter")
            emit_data({**{name: 17 for name in kinds}, "good": "initial"})
            for index, value in enumerate(("ERR", {}, [], None, float("nan"),
                                           float("inf"), -float("inf"), 10 ** 400)):
                emit_data({**{name: value for name in kinds}, "good": str(index)})
                assert [numeric(name) for name in kinds] == [17] * len(kinds)
                assert text("good") == str(index)
            # Finite floats retain the previous integer truncation rule.
            emit_data({name: 23.8 for name in kinds})
            assert [numeric(name) for name in kinds] == [23, 23, 23, 23, 23.8]
            integer_kinds = kinds[:-1]
            for value in (2 ** 31, -(2 ** 31) - 1, 10 ** 100):
                emit_data({**{name: value for name in integer_kinds}, "good": "overflow"})
                assert [numeric(name) for name in integer_kinds] == [23] * 4
                assert text("good") == "overflow"
            emit_data({name: "42" for name in kinds})
            assert [numeric(name) for name in kinds] == [42] * len(kinds)
            # ProgressBar exposes a display-only valueChanged signal; the two
            # command-capable controls must still suppress their feedback.
            """,
        )

    def test_boolean_strings_custom_led_states_and_unknown_values(self):
        self.run_both([
            bound("ToggleSwitch", "switch"), bound("LEDIndicator", "led"),
            bound("LEDIndicator", "custom", properties={"onValue": "RUN", "offValue": "STOP"}),
            bound("Label", "good"),
        ], """
            for value, expected in (("true", True), ("FALSE", False), ("1", True),
                                    ("0", False), (" on ", True), ("off", False),
                                    (True, True), (False, False)):
                emit_data({"switch": value, "led": value})
                assert widgets["switch"]._switch.isChecked() is expected
                assert widgets["led"]._on is expected
            emit_data({"switch": True, "led": True, "custom": "RUN"})
            for value in ("unknown", "NaN", float("inf"), [], {}):
                emit_data({"switch": value, "led": value, "custom": value, "good": "alive"})
                assert widgets["switch"]._switch.isChecked()
                assert widgets["led"]._on
                assert widgets["custom"]._on
                assert text("good") == "alive"
            emit_data({"switch": False, "led": False, "custom": "STOP"})
            assert not widgets["switch"]._switch.isChecked()
            assert not widgets["led"]._on and not widgets["custom"]._on
            assert changes == [], changes
        """)

    def test_explicit_expressions_run_before_conversion_and_keep_failure_fallback(self):
        self.run_both([
            bound("SpinBox", "scale", {"key": "raw", "expression": "value / 10"}),
            bound("SpinBox", "replace", {"key": "error", "expression": "7 if value == 'ERR' else value"}),
            bound("SpinBox", "fallback", {"key": "zero", "expression": "10 / value"}),
            bound("ToggleSwitch", "state", {"key": "state", "expression": "value == 'RUN'"}),
            bound("Label", "good"),
        ], """
            emit_data({"raw": 120, "error": "ERR", "zero": 0, "state": "RUN"})
            assert numeric("scale") == 12 and numeric("replace") == 7
            assert numeric("fallback") == 0 and widgets["state"]._switch.isChecked()
            emit_data({"raw": float("inf"), "error": 42, "state": "STOP", "good": "alive"})
            assert numeric("scale") == 12 and numeric("replace") == 42
            assert not widgets["state"]._switch.isChecked()
            assert text("good") == "alive"
            assert changes == [], changes
        """)

    def test_raw_and_modbus_invalid_samples_do_not_block_valid_bindings(self):
        raw = {"parseMode": "HEX字节提取", "frameHeader": "AA55",
               "frameTail": "55AA", "dataType": "float32"}
        self.run_both([
            bound("SpinBox", "raw", raw),
            bound("Label", "raw_good", {**raw, "dataType": "uint8", "byteOffset": 4}),
            bound("ProgressRingDisplay", "modbus", {
                "parseMode": "Modbus", "mbRegIndex": 0, "mbDataType": "float32",
            }),
            bound("Label", "good"),
        ], """
            def frame(value, counter):
                return b"\\xaa\\x55" + struct.pack(">fB", value, counter) + b"\\x55\\xaa"
            emit_raw(frame(17, 1))
            emit_data({"fc": 3, "reg0": 0x4188, "reg1": 0})
            for value in (float("nan"), float("inf"), -float("inf")):
                emit_raw(frame(value, 2))
                assert numeric("raw") == 17 and text("raw_good") == "2"
                hi, lo = struct.unpack(">HH", struct.pack(">f", value))
                emit_data({"fc": 3, "reg0": hi, "reg1": lo, "good": "alive"})
                assert numeric("modbus") == 17 and text("good") == "alive"
            for value in ("ERR", {}, [], -1, 65536):
                emit_data({"fc": 3, "reg0": value, "reg1": 0, "good": "bad register"})
                assert numeric("modbus") == 17 and text("good") == "bad register"
            emit_raw(frame(float("inf"), 3) + frame(42, 4))
            assert numeric("raw") == 42 and text("raw_good") == "4"
            emit_data({"fc": 3, "reg0": 0x4228, "reg1": 0})
            assert numeric("modbus") == 42
            assert changes == [], changes
        """)

    def test_odd_hex_delimiters_match_host_for_split_and_joined_frames(self):
        self.run_both([
            bound("NumericDisplay", "odd", {
                "parseMode": "HEX字节提取", "frameHeader": "A", "frameTail": "B",
                "dataType": "uint8",
            }),
            bound("NumericDisplay", "even", {
                "parseMode": "HEX字节提取", "frameHeader": "0A", "frameTail": "0 B",
                "dataType": "uint8",
            }),
        ], """
            emit_raw(bytes.fromhex("0a"))
            emit_raw(bytes.fromhex("2a0b"))
            assert text("odd") == text("even") == "42"
            emit_raw(bytes.fromhex("0a2b0b0a2c0b"))
            assert text("odd") == text("even") == "44"
        """)

    def test_nonfinite_display_formatting_does_not_stop_other_fields(self):
        self.run_both([
            bound("NumericDisplay", "display", properties={"displayFormat": "十六进制(HEX)"}),
            bound("Label", "good"),
        ], """
            for value in (float("nan"), float("inf"), -float("inf")):
                emit_data({"display": value, "good": "alive"})
                assert text("display") == str(value)
                assert text("good") == "alive"
            emit_data({"display": 42, "good": "recovered"})
            assert text("display") == "0x2A" and text("good") == "recovered"
        """)


if __name__ == "__main__":
    unittest.main()
