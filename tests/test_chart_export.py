"""Bounded rendering, lossless history, and standalone exported runtime checks."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from PyQt5 import sip

from app.common import runtime_sources
from app.common.build_support import build_nuitka_command
from app.core.chart_runtime import RealtimeLineChart
from app.core.code_generator import _realtime_chart_class, generate_project
from app.core.project import ProjectData
from app.core.protocol_parser import RawFrameBuffer
from types import SimpleNamespace


class ChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        namespace = {}
        with patch.dict(sys.modules, {"serial_handler": SimpleNamespace(RawFrameBuffer=RawFrameBuffer)}):
            exec(_realtime_chart_class(), namespace)
        cls.chart_classes = (RealtimeLineChart, namespace["RealtimeLineChart"])

    def make_chart(self, cls):
        chart = cls()
        chart.configure([{"name": "temperature", "key": "temp"}], 200)
        self.addCleanup(lambda: sip.delete(chart) if not sip.isdeleted(chart) else None)
        return chart

    def test_rendering_is_batched_and_idle_does_not_redraw(self):
        for cls in self.chart_classes:
            chart = self.make_chart(cls)
            curve = chart._curves[0]
            with patch.object(curve, "setData", wraps=curve.setData) as render:
                for i in range(2000):
                    chart.append_value(0, i)
                render.assert_not_called()
                QTest.qWait(90)
                render.assert_called_once()
                self.assertEqual(list(render.call_args.args[0]), list(range(1800, 2000)))
                QTest.qWait(90)
                render.assert_called_once()

    def test_cache_limit_does_not_truncate_csv_or_json_history(self):
        for cls in self.chart_classes:
            chart = self.make_chart(cls)
            count = chart.HISTORY_LIMIT + 17
            for i in range(count):
                chart.on_parsed({"temp": i})
            self.assertEqual(len(chart._data[0]), chart.HISTORY_LIMIT)
            self.assertEqual(chart._data[0][0], 17)
            self.assertEqual(chart._data[0].count, count)
            chart.set_display_points(999999)
            self.assertEqual(chart._display_points, chart.HISTORY_LIMIT)
            with tempfile.TemporaryDirectory() as folder:
                csv_path = Path(folder) / "capture.csv"
                json_path = Path(folder) / "capture.json"
                chart.save_data(csv_path)
                chart.save_data(json_path)
                with csv_path.open() as source:
                    rows = list(csv.reader(source))
                self.assertEqual(rows[0], ["temperature"])
                self.assertEqual([float(row[0]) for row in rows[1:]], list(range(count)))
                self.assertEqual(json.loads(json_path.read_text())["temperature"], list(range(count)))
                # Saving must restore the append position in the spool file.
                chart.append_value(0, count)
                self.assertEqual(list(chart._data[0].values())[-1], count)
                chart.load_data(csv_path)
                self.assertEqual(len(chart._data[0]), chart.HISTORY_LIMIT)
                self.assertEqual(chart._data[0].count, count)

    def test_clear_and_destroy_close_spool_and_cancel_pending_refresh(self):
        chart = self.make_chart(RealtimeLineChart)
        chart.append_value(0, 5)
        spool = chart._data[0]._file
        chart.clear_data()
        self.assertTrue(spool.closed)
        self.assertFalse(chart._refresh_timer.isActive())
        self.assertEqual(chart._data[0].count, 0)
        chart.append_value(0, 6)
        spool = chart._data[0]._file
        sip.delete(chart)
        self.assertTrue(spool.closed)

    def test_bad_history_load_preserves_current_samples(self):
        chart = self.make_chart(RealtimeLineChart)
        chart.append_value(0, 42)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.csv"
            path.write_text("value\n1\nnot-a-number\n")
            with self.assertRaises(ValueError):
                chart.load_data(path)
        self.assertEqual(list(chart._data[0].values()), [42])

    def test_hex_chart_keeps_all_frames_and_resets_partial_on_disconnect(self):
        for cls in self.chart_classes:
            chart = self.make_chart(cls)
            chart.configure([{"parseMode": "HEX字节提取", "dataType": "uint16",
                              "frameHeader": "AA55", "frameTail": "55AA"}])
            chart.on_raw(bytes.fromhex("aa5500"))
            self.assertEqual(chart._data[0].count, 0)
            chart.on_raw(bytes.fromhex("0155aaaa55000255aa"))
            self.assertEqual(list(chart._data[0].values()), [1, 2])
            chart.on_raw(bytes.fromhex("aa5500"))
            chart.reset_stream()
            chart.on_raw(bytes.fromhex("0355aa"))
            self.assertEqual(chart._data[0].count, 2)


class StandaloneExportTests(unittest.TestCase):
    def test_nested_chart_and_serial_card_work_without_designer_imports(self):
        project = ProjectData()
        project.serial.update({"parser": "modbus", "parity": "Even", "dataBits": 7})
        project.widgets = [
            {"id": "group", "type": "GroupBox", "children": [
                {"id": "chart", "type": "RealtimeChart",
                 "properties": {"_curve_0_parseMode": "Modbus", "_curve_0_regIndex": 0}},
                {"id": "value", "type": "NumericDisplay",
                 "binding": {"parseMode": "Modbus", "mbRegIndex": 0}},
            ]},
            {"id": "serial", "type": "SerialConfigCard",
             "properties": {"defaultDatabits": "7", "defaultParity": "Even",
                            "defaultStopbits": "2", "defaultFlow": "RTS/CTS",
                            "defaultParser": "modbus"}},
        ]
        with tempfile.TemporaryDirectory() as folder:
            generate_project(project, folder)
            for source in Path(folder).glob("*.py"):
                compile(source.read_text(), str(source), "exec")
            code = """
from unittest.mock import patch, Mock
from PyQt5.QtWidgets import QApplication
app = QApplication([])
import serial_handler as runtime
from ui import RealtimeLineChart, SerialConfigCard, NumericDisplay
from data_binding import DataBinding
from types import SimpleNamespace
handler = runtime.SerialHandler()
chart = RealtimeLineChart()
chart.configure([{"parseMode": "Modbus", "regIndex": 0}])
value = NumericDisplay()
card = SerialConfigCard()
card.set_default_databits("7")
card.set_default_parity("Even")
card.set_default_stopbits("2")
card.set_default_flow("RTS/CTS")
card.set_default_parser("modbus")
card._port_combo.clear()
card._port_combo.addItem("TEST fake device")
ui = SimpleNamespace(widgets={"chart": chart, "value": value, "serial": card})
binding = DataBinding(ui, handler)
with patch.object(runtime.serial, "Serial") as port, patch.object(runtime, "SerialReaderThread"):
    card._on_connect()
    assert port.call_args.kwargs["bytesize"] == 7
    assert port.call_args.kwargs["parity"] == "E"
    assert port.call_args.kwargs["stopbits"] == 2
    assert port.call_args.kwargs["rtscts"]
    payload = bytes.fromhex("0103020019")
    for parsed in handler._parser.feed(payload + runtime.modbus_crc(payload)):
        handler.dataReceived.emit(parsed)
    assert chart._data[0][-1] == 25
    assert value._value.text() == "25"
    handler.disconnect()
print("STANDALONE_MODBUS_CHART_OK")
"""
            result = subprocess.run([sys.executable, "-c", code], cwd=folder,
                                    env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                                         "PYTHONPATH": ""},
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("STANDALONE_MODBUS_CHART_OK", result.stdout)

    def test_packaged_source_bundle_supports_export_without_python_sources(self):
        root = Path(__file__).resolve().parents[1]
        args = build_nuitka_command(root, [sys.executable], "Designer")
        self.assertTrue(any(arg.endswith("=runtime_sources.json") for arg in args))
        bundle = root / "build" / "runtime_sources.json"
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            (target / "runtime_sources.json").write_bytes(bundle.read_bytes())
            with patch.object(runtime_sources, "ROOT", target), \
                 patch.dict(vars(runtime_sources), {"__compiled__": True}):
                output = target / "export"
                generate_project(ProjectData(), str(output))
                for source in output.glob("*.py"):
                    compile(source.read_text(), str(source), "exec")
                for name in runtime_sources.RUNTIME_FILES:
                    self.assertTrue(runtime_sources.runtime_source(name))
