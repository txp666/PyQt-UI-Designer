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
from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QApplication
from PyQt5 import sip

from app.common import runtime_sources
from app.common.build_support import build_nuitka_command
from app.core.chart_runtime import RealtimeLineChart
from app.core.code_generator import _realtime_chart_class, generate_project
from app.core.project import ProjectData
from app.core.protocol_parser import RawFrameBuffer
from types import SimpleNamespace


def click_legend_sample(chart, index):
    """Click a curve's sample in the chart legend, as a user does to hide or show that curve."""
    sample = chart._legend.items[index][0]
    sample.mouseClickEvent(SimpleNamespace(button=lambda: Qt.LeftButton, accept=lambda: None))


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
            refreshes = QSignalSpy(chart._refresh_timer.timeout)
            with patch.object(curve, "setData", wraps=curve.setData) as render:
                for i in range(2000):
                    chart.append_value(0, i)
                render.assert_not_called()
                self.assertTrue(chart._refresh_timer.isActive())
                # Wait for the real Qt timeout; a busy CI event loop may deliver
                # the 33 ms timer after a fixed 90 ms wall-clock wait expires.
                self.assertTrue(refreshes.wait(3000), "Chart refresh timer did not fire")
                self.assertEqual(len(refreshes), 1)
                render.assert_called_once()
                self.assertEqual(list(render.call_args.args[0]), list(range(1800, 2000)))
                self.assertFalse(chart._refresh_timer.isActive())
                # Advance the event loop through several refresh intervals
                # without new samples, and verify no refresh gets scheduled.
                idle_timer = QTimer()
                idle_timer.setSingleShot(True)
                idle_elapsed = QSignalSpy(idle_timer.timeout)
                idle_timer.start(chart.REFRESH_MS * 3)
                self.assertTrue(idle_elapsed.wait(3000), "Idle observation timer did not fire")
                self.assertEqual(len(refreshes), 1)
                self.assertFalse(chart._refresh_timer.isActive())
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
                self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["temperature"], list(range(count)))
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

    def test_history_load_preserves_all_live_parsers_and_matches_reordered_names(self):
        cfgs = [
            {"name": "温度", "parseMode": "键值匹配", "key": "custom_temperature"},
            {"name": "压力", "parseMode": "JSON路径", "jsonPath": "sensors.1.value"},
            {"name": "计数", "parseMode": "Modbus", "regIndex": 2,
             "mbDataType": "uint32", "mbRegOrder": "小端(CD AB)",
             "mbFcFilter": 3, "mbSlaveFilter": 7},
            {"name": "电压", "parseMode": "HEX字节提取", "byteOffset": 1,
             "dataType": "uint16", "byteOrder": "小端(LE)",
             "frameHeader": "AA55", "frameTail": "55AA"},
        ]
        recorded = {"温度": [1, 2], "压力": [3, 4], "计数": [5, 6], "电压": [7, 8]}
        for cls in self.chart_classes:
            for extension in ("csv", "json"):
                with self.subTest(runtime=cls.__module__, format=extension):
                    chart = self.make_chart(cls)
                    chart.configure(cfgs)
                    click_legend_sample(chart, 1)
                    self.assertFalse(chart._curves[1].isVisible())
                    chart.append_value(0, 999)
                    chart.on_raw(bytes.fromhex("aa5501"))
                    with tempfile.TemporaryDirectory() as folder:
                        path = Path(folder) / f"history.{extension}"
                        reordered = dict(reversed(list(recorded.items())))
                        if extension == "json":
                            path.write_text(json.dumps(reordered), encoding="utf-8")
                        else:
                            with path.open("w", encoding="utf-8", newline="") as output:
                                writer = csv.writer(output)
                                writer.writerow(reordered)
                                writer.writerows(zip(*reordered.values()))
                        chart.load_data(path)
                    self.assertEqual(chart._cfgs, cfgs)
                    self.assertFalse(chart._curves[1].isVisible(), "loading keeps a hidden curve hidden")
                    self.assertEqual([list(h.values()) for h in chart._data],
                                     list(recorded.values()))
                    chart.on_parsed({"custom_temperature": 12,
                                     "sensors": [{}, {"value": 13}],
                                     "fc": 3, "slave": 7,
                                     "reg2": 0x5678, "reg3": 0x1234})
                    chart.on_raw(bytes.fromhex("020355aa"))
                    self.assertEqual([list(h.values()) for h in chart._data],
                                     [[1, 2, 12], [3, 4, 13],
                                      [5, 6, 0x12345678], [7, 8, 770]])
                    # Modbus filters must also survive history import.
                    chart.on_parsed({"fc": 4, "slave": 7, "reg2": 1, "reg3": 0})
                    self.assertEqual(chart._data[2].count, 3)

    def test_history_channel_mismatch_preserves_config_and_samples(self):
        for cls in self.chart_classes:
            chart = self.make_chart(cls)
            chart.configure([{"name": "温度", "key": "temp"},
                             {"name": "压力", "key": "pressure"}])
            chart.on_parsed({"temp": 42, "pressure": 7})
            for header in (["温度"], ["温度", "压力", "多余"],
                           ["改名", "压力"], ["温度", "温度"], list("123456789")):
                with self.subTest(runtime=cls.__module__, channels=header):
                    with tempfile.TemporaryDirectory() as folder:
                        path = Path(folder) / "mismatched.csv"
                        with path.open("w", encoding="utf-8", newline="") as output:
                            csv.writer(output).writerows([header, [1] * len(header)])
                        with self.assertRaises(ValueError):
                            chart.load_data(path)
                    self.assertEqual([list(h.values()) for h in chart._data], [[42], [7]])
                    self.assertEqual(chart._cfgs,
                                     [{"name": "温度", "key": "temp"},
                                      {"name": "压力", "key": "pressure"}])
            chart.on_parsed({"temp": 43, "pressure": 8})
            self.assertEqual([list(h.values()) for h in chart._data], [[42, 43], [7, 8]])

    def test_empty_default_chart_can_import_arbitrary_history_channels(self):
        for cls in self.chart_classes:
            chart = cls()
            self.addCleanup(lambda chart=chart: sip.delete(chart)
                            if not sip.isdeleted(chart) else None)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "history.json"
                path.write_text(json.dumps({"温度": [1, 2], "压力": [3]}), encoding="utf-8")
                chart.load_data(path)
            self.assertEqual([cfg["name"] for cfg in chart._cfgs], ["温度", "压力"])
            self.assertEqual([list(h.values()) for h in chart._data], [[1, 2], [3]])
            chart.on_parsed({"温度": 4, "压力": 5})
            self.assertEqual([list(h.values()) for h in chart._data], [[1, 2, 4], [3, 5]])

    def test_identical_duplicate_channel_names_keep_original_column_order(self):
        for cls in self.chart_classes:
            chart = self.make_chart(cls)
            chart.configure([{"name": "温度", "key": "first"},
                             {"name": "温度", "key": "second"}])
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "history.csv"
                path.write_text("温度,温度\n1,2\n", encoding="utf-8")
                chart.load_data(path)
            chart.on_parsed({"first": 3, "second": 4})
            self.assertEqual([list(h.values()) for h in chart._data], [[1, 3], [2, 4]])


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
                compile(source.read_text(encoding="utf-8"), str(source), "exec")
            code = """
from unittest.mock import patch, Mock
from PyQt5.QtWidgets import QApplication, QWidget
app = QApplication([])
import serial_handler as runtime
from ui import RealtimeLineChart, SerialConfigCard, NumericDisplay
from data_binding import DataBinding
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
ui = QWidget()
ui.widgets = {"chart": chart, "value": value, "serial": card}
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
                    compile(source.read_text(encoding="utf-8"), str(source), "exec")
                for name in runtime_sources.RUNTIME_FILES:
                    self.assertTrue(runtime_sources.runtime_source(name))
