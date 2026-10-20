"""The committed demo must be reproducible and work outside the designer repo."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.code_generator import _gen_command_connection, _gen_ui, generate_project
from app.core.project import ProjectData
from app.widgets.basic import register_basic_widgets
from app.widgets.chart import register_chart_widgets
from app.widgets.comm import register_comm_widgets
from app.widgets.composite import register_composite_widgets
from app.widgets.display import register_display_widgets
from app.widgets.layout import register_layout_widgets


DEMO = Path(__file__).resolve().parents[1] / "demo"

_RUN_DEMO = r"""
import runpy
import sys
import time
import traceback
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

demo_path = Path(sys.argv[1]).resolve()
assert Path.cwd() != demo_path
original_exec = QApplication.exec

def exercise_application():
    app = QApplication.instance()
    window = next(w for w in app.topLevelWidgets() if hasattr(w, "widgets"))
    widgets = window.widgets
    serial = window._serial_handler
    card = widgets["serial"]
    chart = widgets["chart"]
    receive = widgets["receive"]
    samples, received, sent, errors, failures = [], [], [], [], []
    serial.dataReceived.connect(samples.append)
    serial.rawReceived.connect(received.append)
    serial.dataSent.connect(sent.append)
    serial.error.connect(errors.append)
    state = {"phase": "connect", "deadline": time.monotonic() + 10,
             "shutdown": False}
    timer = QTimer(app)
    timer.setInterval(20)

    for name in ("ui", "serial_handler", "data_binding", "theme_support"):
        assert Path(sys.modules[name].__file__).resolve().parent == demo_path
    assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
    assert not serial.is_connected
    assert card.port == "DEMO"

    def assert_latest_sample():
        sample = samples[-1]
        assert set(sample) >= {"temperature", "pressure", "running", "setpoint"}
        assert abs(float(widgets["temperature"]._value.text()) -
                   sample["temperature"]) < 0.011
        assert abs(float(widgets["pressure"]._value.text()) -
                   sample["pressure"]) < 0.011
        assert widgets["running"]._on == bool(sample["running"])
        assert widgets["run_switch"]._switch.isChecked() == bool(sample["running"])
        assert widgets["setpoint_slider"].value() == sample["setpoint"]
        slider = widgets["setpoint_slider"]
        expected_x = int((sample["setpoint"] - slider.minimum()) /
                         (slider.maximum() - slider.minimum()) * slider.grooveLength)
        assert slider.handle.x() == expected_x
        assert widgets["setpoint_spin"].value() == sample["setpoint"]
        assert widgets["pressure_ring"]._ring.value() == int(sample["pressure"])
        assert len(chart._data) == 2
        assert chart._data[0][-1] == sample["temperature"]
        assert chart._data[1][-1] == sample["pressure"]
        assert receive._count > 0
        assert "temperature" in receive._text.toPlainText()

    def step():
        try:
            assert time.monotonic() < state["deadline"], state["phase"]
            assert not errors, errors
            phase = state["phase"]
            if phase == "connect":
                card._sl_conn.click()
                assert serial.is_connected and serial._thread.isRunning()
                assert type(serial._thread).__name__ == "SerialReaderThread"
                assert type(serial._parser).__name__ == "LineParser"
                assert not card._sl_conn.isEnabled()
                assert card._sl_disconn.isEnabled()
                state["phase"] = "receiving"
            elif phase == "receiving" and len(samples) >= 3:
                assert_latest_sample()
                assert not sent, "Device updates must not echo commands"
                assert len(received) >= 3
                assert samples[-1]["running"] == 1
                assert samples[0]["temperature"] != samples[-1]["temperature"]
                widgets["stop"].click()
                assert sent[-1] == b"STOP\r\n", sent[-1]
                state["phase"] = "stopping"
            elif phase == "stopping" and samples[-1]["running"] == 0:
                assert_latest_sample()
                state.update(
                    phase="stopped",
                    stopped_values=(samples[-1]["temperature"], samples[-1]["pressure"]),
                    stopped_count=len(samples),
                )
            elif phase == "stopped" and len(samples) >= state["stopped_count"] + 3:
                assert_latest_sample()
                for sample in samples[state["stopped_count"]:]:
                    assert sample["running"] == 0
                    assert (sample["temperature"], sample["pressure"]) == state["stopped_values"]
                widgets["start"].click()
                assert sent[-1] == b"START\r\n", sent[-1]
                state["phase"] = "restarting"
            elif phase == "restarting" and samples[-1]["running"] == 1:
                assert_latest_sample()
                if (samples[-1]["temperature"], samples[-1]["pressure"]) == state["stopped_values"]:
                    return
                assert sent == [b"STOP\r\n", b"START\r\n"], sent
                widgets["setpoint_slider"].setValue(60)
                assert sent[-1] == b"60\r\n", sent
                state["phase"] = "slider"
            elif phase == "slider" and samples[-1]["setpoint"] == 60:
                assert_latest_sample()
                assert len(sent) == 3, sent
                widgets["setpoint_spin"].setValue(40)
                assert sent[-1] == b"40\r\n", sent
                state["phase"] = "spin"
            elif phase == "spin" and samples[-1]["setpoint"] == 40:
                assert_latest_sample()
                assert len(sent) == 4, sent
                widgets["run_switch"]._switch.setChecked(False)
                assert sent[-1] == b"STOP\r\n", sent
                state["phase"] = "switch_off"
            elif phase == "switch_off" and samples[-1]["running"] == 0:
                assert_latest_sample()
                assert len(sent) == 5, sent
                widgets["run_switch"]._switch.setChecked(True)
                assert sent[-1] == b"START\r\n", sent
                state["phase"] = "switch_on"
            elif phase == "switch_on" and samples[-1]["running"] == 1:
                assert_latest_sample()
                assert len(sent) == 6, sent
                state["read_count"] = len(samples)
                widgets["command"].setText("READ")
                QTest.keyClick(widgets["command"], Qt.Key_Return)
                assert sent[-1] == b"READ\r\n", sent[-1]
                state["phase"] = "reading"
            elif phase == "reading" and len(samples) > state["read_count"]:
                assert_latest_sample()
                assert len(sent) == 7, sent
                assert "READ" in receive._text.toPlainText()
                old_thread = serial._thread
                state["old_port"] = serial._port
                card._sl_disconn.click()
                assert not serial.is_connected
                assert serial._thread is None
                assert not old_thread.isRunning()
                assert not state["old_port"].is_open
                assert card._sl_conn.isEnabled()
                assert not card._sl_disconn.isEnabled()
                state.update(phase="settle", disconnected_at=time.monotonic())
            elif phase == "settle" and time.monotonic() - state["disconnected_at"] > 0.1:
                state.update(phase="disconnected", disconnected_count=len(samples))
            elif phase == "disconnected" and time.monotonic() - state["disconnected_at"] > 0.4:
                assert len(samples) == state["disconnected_count"]
                card._sl_conn.click()
                assert serial.is_connected and serial._thread.isRunning()
                assert serial._port is not state["old_port"]
                state["phase"] = "reconnected"
            elif phase == "reconnected" and len(samples) >= state["disconnected_count"] + 2:
                assert_latest_sample()
                assert samples[-1]["running"] == 1
                state.update(phase="complete", exit_port=serial._port)
                timer.stop()
                # Leave the reader connected: generated main.py must shut it
                # down through aboutToQuit, before deleting its QObjects.
                window.close()
        except BaseException:
            failures.append(traceback.format_exc())
            timer.stop()
            serial.disconnect()
            app.exit(1)

    def check_shutdown():
        try:
            assert not serial.is_connected
            assert serial._thread is None
            if state["phase"] == "complete":
                assert not state["exit_port"].is_open
                state["shutdown"] = True
        except BaseException:
            failures.append(traceback.format_exc())

    app.aboutToQuit.connect(check_shutdown)
    timer.timeout.connect(step)
    timer.start()
    result = original_exec()
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    if state["phase"] != "complete" or not state["shutdown"]:
        print("Incomplete simulation:", state["phase"], file=sys.stderr)
        return 1
    print("STANDALONE_DEMO_OK: serial, parser, bindings, commands, reconnect, shutdown")
    return result

with ExitStack() as stack:
    # Offscreen winIds are not Cocoa pointers; keep all Qt widgets, data
    # handling, and the real event loop, disabling only the native title bar.
    if sys.platform == "darwin":
        from qframelesswindow.mac import MacFramelessWindow
        for method in ("updateFrameless", "_hideSystemTitleBar",
                       "setSystemTitleBarButtonVisible"):
            stack.enter_context(patch.object(
                MacFramelessWindow, method, lambda *args, **kwargs: None))
    stack.enter_context(patch.object(QApplication, "exec", staticmethod(exercise_application)))
    # Match Python's normal script startup: it puts the script's own directory,
    # not the caller's working directory or designer repo, on the import path.
    sys.path.insert(0, str(demo_path))
    sys.argv = [str(demo_path / "simulate.py")]
    runpy.run_path(sys.argv[0], run_name="__main__")
"""


class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for register in (
            register_basic_widgets, register_chart_widgets, register_comm_widgets,
            register_composite_widgets, register_display_widgets, register_layout_widgets,
        ):
            register()

    def test_exported_commands_send_real_newlines(self):
        # Execute the actual generated send method and command callbacks
        # without constructing a native window just to capture their output.
        source = _gen_ui([{
            "id": "send", "type": "PushButton",
            "properties": {"command": "READ"},
        }], 500, 300)
        ui_class = next(node for node in ast.parse(source).body
                        if isinstance(node, ast.ClassDef) and node.name == "MainUI")
        send_method = next(node for node in ui_class.body
                           if isinstance(node, ast.FunctionDef)
                           and node.name == "_send_text_command")
        namespace = {}
        exec(compile(ast.Module(body=[send_method], type_ignores=[]),
                     "<generated-send-method>", "exec"), namespace)
        for widget_type in ("PushButton", "LineEdit"):
            for selection, suffix in (
                ("无", ""), ("\\r\\n", "\r\n"), ("\\n", "\n"), ("\\r", "\r"),
                (None, "\r\n"),
            ):
                with self.subTest(widget=widget_type, newline=selection):
                    widget = SimpleNamespace(
                        clicked=Mock(), returnPressed=Mock(),
                        text=Mock(return_value="READ"),
                    )
                    handler = SimpleNamespace(is_connected=True, send_text=Mock())
                    ui = SimpleNamespace(widgets={"send": widget}, _serial_handler=handler)
                    ui._send_text_command = MethodType(namespace["_send_text_command"], ui)
                    properties = {"command": "READ", "sendOnEnter": True}
                    if selection is not None:
                        properties["commandNewline"] = selection
                    callbacks = _gen_command_connection("send", widget_type, properties)
                    exec(textwrap.dedent("\n".join(callbacks)), {"self": ui})
                    signal = widget.clicked if widget_type == "PushButton" else widget.returnPressed
                    callback = signal.connect.call_args.args[0]
                    callback()
                    handler.send_text.assert_called_once_with("READ" + suffix)

    def test_committed_export_matches_its_editable_project(self):
        source = DEMO / "project.uidp"
        project = ProjectData.from_dict(json.loads(source.read_text(encoding="utf-8")))
        project.file_path = str(source)
        with tempfile.TemporaryDirectory() as folder:
            generate_project(project, folder, theme_mode="Auto")
            generated = Path(folder)
            self.assertTrue((generated / "main.py").is_file())
            for expected in generated.iterdir():
                with self.subTest(file=expected.name):
                    committed = DEMO / expected.name
                    self.assertTrue(committed.is_file(), str(committed))
                    self.assertEqual(committed.read_bytes(), expected.read_bytes())
                    if expected.suffix == ".py":
                        compile(committed.read_text(encoding="utf-8"), str(committed), "exec")

    def test_simulation_runs_from_an_independent_copy_and_real_event_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            copied = root / "standalone-demo"
            shutil.copytree(DEMO, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            unrelated = root / "unrelated-working-directory"
            unrelated.mkdir()
            result = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(_RUN_DEMO), str(copied)],
                cwd=unrelated,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": ""},
                text=True, capture_output=True, timeout=25,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("STANDALONE_DEMO_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
