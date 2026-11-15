"""Key S7 codec, session and preview/export regressions."""
import json
import threading
import time
import unittest
import copy
from types import SimpleNamespace

from app.core.s7_values import encode_s7, decode_s7, parse_s7_address, s7_config, s7_point
from app.core.s7_worker import S7Worker
from tests import test_preview_export_parity as parity


class S7CodecTests(unittest.TestCase):
    def test_slow_reads_do_not_starve_other_due_points(self):
        observed = set()
        all_read = threading.Event()

        class Client:
            def connect(self, _config):
                pass

            def close(self):
                pass

            def read(self, point):
                time.sleep(0.005)  # one operation takes longer than the requested 1ms interval
                observed.add(point["address"])
                if len(observed) == 3:
                    all_read.set()
                return 1

        worker = S7Worker("fair", 1, s7_config({"period": 1}), lambda *_: None, Client)
        worker.set_needs([s7_point({"address": f"DB1.DBW{offset}", "dataType": "INT"}) for offset in (0, 2, 4)])
        worker.start()
        try:
            self.assertTrue(all_read.wait(2), observed)
        finally:
            worker.request_stop()
            worker.join(2)
            self.assertFalse(worker.is_alive())

    def test_duplicate_point_uses_fastest_effective_connection_or_point_period(self):
        from app.core.s7_runtime import S7Poller
        collected = []
        link = SimpleNamespace(poll_period=100, set_needs=collected.append)
        points = [s7_point({"period": 0}), s7_point({"period": 500})]
        poller = S7Poller(SimpleNamespace(s7_links={"plc": link}),
                          lambda: [("plc", point) for point in points])
        poller.refresh()
        self.assertEqual(collected[-1][0]["period"], 0)
        points.append(s7_point({"period": 50}))
        poller.refresh()
        self.assertEqual(collected[-1][0]["period"], 50)

    def test_project_versions_references_and_paste_connection_mapping(self):
        from tools.check_uidp import _register_widgets
        from app.core.project import ProjectData
        from app.designer.clipboard import assign_ids
        _register_widgets()
        project = ProjectData()
        project.widgets = [{"id": "button", "type": "PushButton", "properties": {
            "commandMode": "文本", "s7Command": {"address": "DB1.DBX0.0", "dataType": "BOOL"}}}]
        self.assertEqual(project.to_dict()["version"], "1.0")
        project.widgets = [{"id": "plc", "type": "S7ConfigCard", "properties": {}},
                           {"id": "value", "type": "SpinBox", "properties": {
                               "commandMode": "S7", "commandTargetId": "plc",
                               "s7Command": {"address": "DB1.DBW2", "dataType": "INT"}},
                            "binding": {"parseMode": "S7", "sourceCardId": "plc",
                                        "s7": {"address": "DB1.DBW2", "dataType": "INT"}}},
                           {"id": "chart", "type": "RealtimeChart", "properties": {
                               "_curve_0_parseMode": "S7", "_curve_0_sourceCardId": "plc",
                               "_curve_0_s7": {"address": "DB1.DBD16", "dataType": "REAL"}}}]
        self.assertEqual(ProjectData.from_dict(project.to_dict()).to_dict()["version"], "1.1")
        copied = copy.deepcopy(project.widgets)
        assign_ids(copied, {"plc", "value", "chart"})
        connection_id = copied[0]["id"]
        self.assertNotEqual(connection_id, "plc")
        self.assertEqual(copied[1]["binding"]["sourceCardId"], connection_id)
        self.assertEqual(copied[1]["properties"]["commandTargetId"], connection_id)
        self.assertEqual(copied[2]["properties"]["_curve_0_sourceCardId"], connection_id)
        isolated = copy.deepcopy(project.widgets[1:2])
        assign_ids(isolated, {"value"})
        self.assertEqual(isolated[0]["binding"]["sourceCardId"], "plc")
        project.widgets[1]["binding"]["sourceCardId"] = "missing"
        with self.assertRaises(ValueError):
            ProjectData.from_dict(project.to_dict())

    def test_wire_values_addresses_and_rejected_writes(self):
        for kind, value, wire in (("BOOL", True, "01"), ("BYTE", 255, "ff"),
                                  ("SINT", -12, "f4"), ("WORD", 50000, "c350"),
                                  ("INT", -1234, "fb2e"), ("DWORD", 4000000000, "ee6b2800"),
                                  ("DINT", -123456789, "f8a432eb"), ("REAL", -12.75, "c14c0000")):
            with self.subTest(kind=kind):
                self.assertEqual(encode_s7(value, kind).hex(), wire)
                self.assertEqual(decode_s7(bytes.fromhex(wire), kind), value)
        self.assertEqual(parse_s7_address("db0001.dbx000.7", "BOOL").canonical, "DB1.DBX0.7")
        self.assertEqual(parse_s7_address("mx00.0", "BOOL").canonical, "M0.0")
        for value, kind in (("1.0", "INT"), ("1e2", "INT"), (True, "INT"),
                            (256, "BYTE"), (-32769, "INT"), (float("inf"), "REAL"),
                            (2, "BOOL"), ("0x10", "WORD")):
            with self.subTest(value=value, kind=kind), self.assertRaises(ValueError):
                encode_s7(value, kind)
        for address, kind in (("DB0.DBW0", "INT"), ("DB1.DBX0.8", "BOOL"),
                              ("DB1.DBB0", "REAL"), ("MD2097150", "DWORD")):
            with self.subTest(address=address), self.assertRaises(ValueError):
                parse_s7_address(address, kind)

    def test_failed_write_is_not_replayed_after_reconnect(self):
        failed = threading.Event()
        clients, events = [], []

        class Client:
            def __init__(self):
                self.writes = []
                clients.append(self)

            def connect(self, _config):
                pass

            def close(self):
                pass

            def write(self, point, value):
                self.writes.append((point, value))
                failed.set()
                raise RuntimeError("write transport timeout")

        worker = S7Worker("plc", 1, s7_config({"reconnectInterval": 5}),
                          lambda kind, value: events.append((kind, value)), Client)
        worker.start()
        try:
            deadline = time.monotonic() + 2
            while not worker.connected and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(worker.write("request", s7_point({"address": "DB1.DBW2", "dataType": "INT"}), 7))
            self.assertTrue(failed.wait(2))
            deadline = time.monotonic() + 2
            while len(clients) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertGreaterEqual(len(clients), 2)
            self.assertEqual(sum(len(client.writes) for client in clients), 1)
            self.assertTrue(any(kind == "write" and value["status"] == "unknown" for kind, value in events))
        finally:
            worker.request_stop()
            worker.join(2)
            self.assertFalse(worker.is_alive())


class S7PreviewExportTests(unittest.TestCase):
    run_both = parity.PreviewExportParityTests.run_both

    def test_targeted_commands_and_typed_feedback_never_broadcast_or_echo(self):
        widgets = [parity.control("plc", "S7ConfigCard", {"autoConnect": False})]
        for index, kind in enumerate(("PushButton", "ToggleSwitch", "LineEdit", "ComboBox", "Slider", "SpinBox"), 1):
            properties = {"commandMode": "S7", "commandTargetId": "plc", "minimum": -100,
                          "maximum": 100, "items": "10\n20", "commands": "10\n20",
                          "s7Command": {"address": "DB1.DBW2", "dataType": "INT",
                                        "value": "17", "onValue": "9", "offValue": "4"}}
            widget = parity.control(kind, kind, properties, index)
            if kind != "PushButton":
                widget["binding"] = {"parseMode": "S7", "sourceCardId": "plc",
                                     "s7": {"address": "DB1.DBW2", "dataType": "INT"}}
            widgets.append(widget)
        self.run_both(widgets, r'''
            calls = []
            hub.write_s7 = lambda source, point, value: calls.append((source, point, value))
            if os.environ["APPLICATION_MODE"] == "preview":
                from app.core.data_binding import bindingEngine
                bindingEngine.load_bindings_from_project(json.loads(os.environ["PROJECT_WIDGETS"]))
                bindingEngine.start()
            sample = {"sourceCardId":"other", "address":"DB1.DBW2", "dataType":"INT", "value":1,
                      "quality":"good", "timestamp":0, "sessionGeneration":1}
            initial = widgets["SpinBox"].value()
            hub.s7SampleReceived.emit(sample)
            assert widgets["SpinBox"].value() == initial
            sample["sourceCardId"] = "plc"
            sample["quality"] = "bad"
            hub.s7SampleReceived.emit(sample)
            assert widgets["SpinBox"].value() == initial
            sample["quality"] = "good"
            hub.s7SampleReceived.emit(sample)
            assert widgets["SpinBox"].value() == widgets["Slider"].value() == 1
            assert widgets["ComboBox"].currentIndex() == 1
            assert widgets["ToggleSwitch"]._switch.isChecked()
            assert widgets["LineEdit"].text() == "1"
            assert calls == [], calls
            widgets["PushButton"].click()
            widgets["ToggleSwitch"]._switch.setChecked(False)
            widgets["LineEdit"].setText("-23")
            widgets["LineEdit"].returnPressed.emit()
            widgets["ComboBox"].setCurrentIndex(0)
            widgets["SpinBox"].setValue(-11)
            widgets["Slider"].setValue(12)
            widgets["Slider"].sliderReleased.emit()
            assert [item[2] for item in calls] == ["17", "4", "-23", "10", -11, 12], calls
            assert all(source == "plc" and point["address"] == "DB1.DBW2" for source, point, value in calls)
            check_payloads([])
            from PyQt5 import sip
            sip.delete(widgets["plc"])
            app.processEvents()
            assert "plc" not in hub.s7_links
            check_payloads([])
        ''')
