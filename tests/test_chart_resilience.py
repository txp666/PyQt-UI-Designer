"""Chart samples and history files survive bad input in live and exported apps."""
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
from app.core.project import ProjectData
from app.widgets.chart import RealtimeLineChart


_EXPORT_RUNNER = """
import json
from pathlib import Path
import runpy
import struct
import sys
from contextlib import ExitStack
from unittest.mock import patch
from PyQt5.QtWidgets import QApplication

errors = []
sys.excepthook = lambda kind, value, tb: errors.append(repr(value))

def exercise():
    app = QApplication.instance()
    app.processEvents()
    window = next(w for w in app.topLevelWidgets() if hasattr(w, "widgets"))
    chart = window.widgets["chart"]
    serial = window._comm_hub.serial
__CHECKS__
    assert not errors, errors
    assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
    print("STANDALONE_CHART_RESILIENCE_OK")
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


class ChartResilienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def run_both(self, checks):
        import json
        import struct
        checks = textwrap.dedent(checks)
        chart = RealtimeLineChart()
        chart.start_listening()
        errors = []
        with tempfile.TemporaryDirectory() as folder:
            namespace = {
                "chart": chart, "errors": errors, "json": json, "struct": struct,
                "Path": lambda name: Path(folder) / name,
                "serial": SimpleNamespace(
                    dataReceived=signalBus.serialDataReceived,
                    rawReceived=signalBus.serialRawReceived),
            }
            try:
                with patch.object(sys, "excepthook",
                                  lambda kind, value, tb: errors.append(repr(value))):
                    exec(checks, namespace)
                self.assertFalse(errors)
            finally:
                chart.stop_listening()
                sip.delete(chart)

        project = ProjectData()
        project.widgets = [{"id": "chart", "type": "RealtimeChart"}]
        with tempfile.TemporaryDirectory() as folder:
            generate_project(project, folder, theme_mode="Light")
            runner = _EXPORT_RUNNER.replace(
                "__CHECKS__", textwrap.indent(checks.strip(), "    "))
            result = subprocess.run(
                [sys.executable, "-c", runner], cwd=folder,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": ""},
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("STANDALONE_CHART_RESILIENCE_OK", result.stdout)

    def test_bad_samples_are_isolated_per_channel_and_per_raw_frame(self):
        self.run_both("""
            chart.configure([
                {"name": "key", "key": "bad"},
                {"name": "nested", "parseMode": "JSON路径", "jsonPath": "sensor.value"},
                {"name": "registers", "parseMode": "Modbus", "regIndex": 0,
                 "mbDataType": "uint32", "mbFcFilter": 3},
                {"name": "good", "key": "good"},
                {"name": "raw", "parseMode": "HEX字节提取", "dataType": "float32",
                 "frameHeader": "AA55", "frameTail": "55AA"},
            ])
            serial.dataReceived.emit({"bad": 1, "sensor": {"value": 2},
                                      "fc": 3, "hr0": 0, "hr1": 3, "good": 4})
            assert [h.count for h in chart._data] == [1, 1, 1, 1, 0]
            invalid = ("ERR", {}, [], None, float("nan"), float("inf"),
                       -float("inf"), 10 ** 400)
            for index, value in enumerate(invalid):
                serial.dataReceived.emit({"bad": value, "sensor": {"value": value},
                                          "fc": 3, "hr0": value, "hr1": 3,
                                          "good": index})
                assert not errors, errors
                assert [h.count for h in chart._data] == [1, 1, 1, index + 2, 0]
            # Validate both words of a dual-register value before combining them.
            for value in ("2", 1.5, -1, 65536, 10 ** 400):
                before = chart._data[3].count
                serial.dataReceived.emit({"fc": 3, "hr0": 0, "hr1": value, "good": 7})
                assert chart._data[2].count == 1
                assert chart._data[3].count == before + 1
            serial.dataReceived.emit({"bad": "5.5", "sensor": {"value": "6.5"},
                                      "fc": 3, "hr0": 1, "hr1": 2, "good": 8})
            assert [chart._data[i][-1] for i in range(4)] == [5.5, 6.5, 65538, 8]
            def frame(value):
                return b"\\xaa\\x55" + struct.pack(">f", value) + b"\\x55\\xaa"
            serial.rawReceived.emit(frame(float("nan")) + frame(9) +
                                    frame(float("inf")) + frame(10))
            assert list(chart._data[4].values()) == [9, 10]
            chart._refresh_all()
            assert list(chart._curves[4].yData) == [9, 10]
            assert not errors, errors
        """)

    def test_plot_keeps_its_width_while_readings_change_length(self):
        self.run_both("""
            chart.configure([{"name": "目标", "key": "tgt"}, {"name": "实际", "key": "pos"}])
            chart.resize(700, 300)
            chart.show()
            widths = []
            def settle():
                chart._refresh_all()
                chart.layout().activate()
                widths.append(chart._plot.width())
            for pos in (100, 99.82, 100, 137.5, 90, -5.25, 0.001234, 100):
                serial.dataReceived.emit({"tgt": 100, "pos": pos})
                settle()
            chart._update_table_at_cursor(123.0)  # the cursor reading replaces 实时
            chart.layout().activate()
            widths.append(chart._plot.width())
            chart._mode_label.setText("实时")
            settle()
            assert len(set(widths)) == 1, widths
        """)

    def test_loaded_recording_overlays_the_live_curves(self):
        self.run_both("""
            from PyQt5.QtCore import Qt
            chart.configure([{"name": "电压", "key": "v"}])
            for v in (4.1, 4.0, 3.9):
                serial.dataReceived.emit({"v": v})
            path = Path("上周.csv")
            path.write_text("电压\\n4.2\\n3.8\\n3.5\\n3.2\\n", encoding="utf-8")
            chart.load_reference(path)
            chart._refresh_all()
            assert [list(h.values()) for h in chart._data] == [[4.1, 4.0, 3.9]]  # the live curve stays
            assert list(chart._ref_curves[0].yData) == [4.2, 3.8, 3.5, 3.2]
            assert chart._ref_curves[0].opts["pen"].style() == Qt.DashLine
            assert not chart._clear_ref_btn.isHidden()
            def readings():
                return [lbl.text().split()[-1] for lbl in chart._val_labels + chart._ref_labels]
            assert readings() == ["3.9", "3.5"], readings()  # live now, and the recording at the same sample
            chart._update_table_at_cursor(1.0)
            assert readings() == ["4", "3.8"], readings()  # the cursor reads both
            serial.dataReceived.emit({"v": 3.8})
            chart.save_data(Path("本次.csv"))
            assert Path("本次.csv").read_text(encoding="utf-8").split() == ["电压", "4.1", "4.0", "3.9", "3.8"]
            chart.clear_reference()
            assert chart._ref_curves == [] and chart._ref_labels == [] and chart._clear_ref_btn.isHidden()
            assert [list(h.values()) for h in chart._data] == [[4.1, 4.0, 3.9, 3.8]]
            path.write_text("电压\\n1\\nnan\\n", encoding="utf-8")
            try:
                chart.load_reference(path)
            except (TypeError, ValueError, OverflowError):
                pass
            assert chart._ref_curves == [], "a bad file must not leave a half-loaded overlay"
        """)

    def test_duplicate_names_roundtrip_and_legacy_json_remain_lossless(self):
        self.run_both("""
            chart.configure([{"name": "温度", "key": "a"},
                             {"name": "温度", "key": "b"}])
            serial.dataReceived.emit({"a": 1, "b": 2})
            serial.dataReceived.emit({"a": 3})
            path = Path("duplicate.json")
            chart.save_data(path)
            assert json.loads(path.read_text(encoding="utf-8")) == [
                {"name": "温度", "values": [1, 3]},
                {"name": "温度", "values": [2]},
            ]
            chart.clear_data()
            chart.load_data(path)
            assert [list(h.values()) for h in chart._data] == [[1, 3], [2]]
            serial.dataReceived.emit({"a": 4, "b": 5})
            assert [list(h.values()) for h in chart._data] == [[1, 3, 4], [2, 5]]
            # Older exports wrote duplicate object keys; recover both in order.
            path.write_text('{"温度":[6,7],"温度":[8]}', encoding="utf-8")
            chart.load_data(path)
            assert [list(h.values()) for h in chart._data] == [[6, 7], [8]]
            chart.configure([{"name": "A", "key": "a"}, {"name": "B", "key": "b"}])
            path.write_text('{"B":[20],"A":[10,11]}', encoding="utf-8")
            chart.load_data(path)
            chart.save_data(path)
            assert json.loads(path.read_text(encoding="utf-8")) == {"A": [10, 11], "B": [20]}
        """)

    def test_invalid_history_is_rejected_without_changing_live_samples(self):
        self.run_both("""
            cfgs = [{"name": "value", "key": "value"}]
            chart.configure(cfgs)
            serial.dataReceived.emit({"value": 42})
            spool = chart._data[0]._file
            for suffix, content in (
                ("csv", "value\\n1\\nnan\\n"),
                ("csv", "value\\n1\\ninf\\n"),
                ("json", '{"value":[1,NaN]}'),
                ("json", '{"value":[1,1e400]}'),
                ("json", '{"value":"123"}'),
                ("json", '{"value":{"bad":1}}'),
                ("json", '[{"name":"value","values":[1,Infinity]}]'),
                ("json", '[{"name":"value"}]'),
                ("json", '[{"name":2,"values":[1]}]'),
            ):
                path = Path("bad." + suffix)
                path.write_text(content, encoding="utf-8")
                try:
                    chart.load_data(path)
                except (TypeError, ValueError, OverflowError):
                    pass
                else:
                    raise AssertionError("Accepted invalid history: " + content)
                assert chart._cfgs == cfgs
                assert list(chart._data[0].values()) == [42]
                assert chart._data[0]._file is spool and not spool.closed
            for value in (float("nan"), float("inf"), 10 ** 400):
                try:
                    chart.append_value(0, value)
                except (ValueError, OverflowError):
                    pass
                else:
                    raise AssertionError("Accepted non-finite direct sample")
                assert chart._data[0].count == 1
            serial.dataReceived.emit({"value": 43})
            assert list(chart._data[0].values()) == [42, 43]
            chart.save_data(Path("good.json"))
            assert json.loads(Path("good.json").read_text(encoding="utf-8")) == {"value":[42,43]}
        """)
