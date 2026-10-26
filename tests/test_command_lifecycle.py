"""Preview lifetime and serial failures must behave like standalone applications."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

from tests import test_preview_export_parity as parity


ROOT = Path(__file__).resolve().parent.parent


def control(name, kind, properties=None):
    item = parity.control(name, kind, properties or {})
    item["geometry"].update(w=600, h=260)
    return item


_PREVIEW = r"""
import sys
import traceback
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication
from app.core.project import ProjectData
from app.core.serial_manager import serialManager
from app.view.preview_interface import PreviewInterface

errors = []
def capture(kind, value, tb):
    errors.append(repr(value))
    traceback.print_exception(kind, value, tb)
sys.excepthook = capture
app = QApplication([])
project = ProjectData()
project.canvas_width = 650
project.canvas_height = 1050
project.widgets = [
    {"id": kind, "type": kind, "properties": {},
     "geometry": {"x": 10, "y": 10 + row * 260, "w": 600, "h": 250}}
    for row, kind in enumerate(("ModbusConfigCard", "DataRecvCard", "LogBox", "DataSendCard"))
]
window = PreviewInterface()
window.set_project_data(project)
window.resize(750, 950)
window.show()
app.processEvents()
__CHECKS__
assert not errors, errors
window.deleteLater()
app.sendPostedEvents(None, QEvent.DeferredDelete)
serialManager.disconnect()
assert not errors, errors
print("PREVIEW_LIFECYCLE_OK")
"""


class CommandLifecycleTests(unittest.TestCase):
    run_both = parity.PreviewExportParityTests.run_both

    def run_preview(self, checks):
        script = _PREVIEW.replace("__CHECKS__", textwrap.dedent(checks))
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PREVIEW_LIFECYCLE_OK", result.stdout)

    def test_real_preview_start_stop_restart_disconnects_deleted_card_slots(self):
        self.run_preview(r"""
            for cycle in range(3):
                QTest.mouseClick(window._run_btn, Qt.LeftButton)
                app.processEvents()
                assert window._running
                assert not errors, errors
                serialManager.connected.emit("TEST")
                serialManager.rawReceived.emit(b"temperature=42\n")
                serialManager.dataReceived.emit({"temperature": 42})
                serialManager.error.emit("test error")
                receive, log = window._preview_canvas._widgets[1:3]
                assert receive._output.toPlainText().count("已连接: TEST") == 1
                assert log._output.toPlainText().count("已连接: TEST") == 1
                QTest.mouseClick(window._stop_btn, Qt.LeftButton)
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                assert not window._running
                serialManager.disconnect()
                serialManager.error.emit("after stop")
                assert not errors, errors
        """)

    def test_send_tip_timer_dies_with_preview_and_repeated_errors_restore_button(self):
        self.run_preview(r"""
            QTest.mouseClick(window._run_btn, Qt.LeftButton)
            send = window._preview_canvas._widgets[-1]
            send._send_btn.click()
            assert not send._send_btn.isEnabled()
            assert send._tip_timer.isActive()
            QTest.mouseClick(window._stop_btn, Qt.LeftButton)
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            QTest.qWait(1350)
            assert not errors, errors

            QTest.mouseClick(window._run_btn, Qt.LeftButton)
            send = window._preview_canvas._widgets[-1]
            QTest.keyClick(send._input, Qt.Key_Return)
            QTest.keyClick(send._input, Qt.Key_Return)
            restored = QSignalSpy(send._tip_timer.timeout)
            assert restored.wait(3000), "Send warning timer did not finish"
            assert send._send_btn.text() == "发送"
            assert send._send_btn.isEnabled()
            QTest.mouseClick(window._stop_btn, Qt.LeftButton)
            app.sendPostedEvents(None, QEvent.DeferredDelete)
        """)

    def test_deleted_cards_no_longer_receive_serial_events_in_either_application(self):
        self.run_both([
            control("bus", "ModbusConfigCard"),
            control("recv", "DataRecvCard"),
            control("log", "LogBox"),
        ], r"""
            for widget in widgets.values():
                widget.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            serial.connected.emit("RECONNECTED")
            serial.disconnected.emit()
            serial.error.emit("after deletion")
            serial.rawReceived.emit(b"temperature=42\n")
            serial.dataReceived.emit({"temperature": 42})
            app.processEvents()
            assert not errors, errors
        """)

    def test_serial_card_preserves_initial_and_connected_button_states(self):
        self.run_both([control("serial", "SerialConfigCard", {
            "displayMode": "单行",
        })], r"""
            card = widgets["serial"]
            assert card._display_mode == "单行"
            for connect, disconnect in ((card._connect_btn, card._disconnect_btn),
                                        (card._sl_conn, card._sl_disconn)):
                assert connect.isEnabled()
                assert not disconnect.isEnabled()
            window.setEnabled(False)
            card.set_display_mode("完整")
            card.set_display_mode("单行")
            window.setEnabled(True)
            assert card._sl_conn.isEnabled()
            assert not card._sl_disconn.isEnabled()
            serial.connected.emit("TEST")
            window.setEnabled(False)
            card.set_display_mode("完整")
            card.set_display_mode("单行")
            window.setEnabled(True)
            for connect, disconnect in ((card._connect_btn, card._disconnect_btn),
                                        (card._sl_conn, card._sl_disconn)):
                assert not connect.isEnabled()
                assert disconnect.isEnabled()
            assert not card._baud_combo.isEnabled()
            serial.disconnect()
            assert card._connect_btn.isEnabled()
            assert not card._disconnect_btn.isEnabled()
            assert card._baud_combo.isEnabled()
        """)

    def test_single_line_serial_card_connects_after_each_real_preview_restart(self):
        self.run_preview(r"""
            from unittest.mock import patch
            import serial as pyserial
            class Port:
                is_open = True
                in_waiting = 0
                def close(self):
                    self.is_open = False
            project.widgets = [{
                "id": "serial", "type": "SerialConfigCard",
                "properties": {"displayMode": "单行"},
                "geometry": {"x": 10, "y": 10, "w": 600, "h": 80},
            }]
            window.set_project_data(project)
            for cycle in range(3):
                QTest.mouseClick(window._run_btn, Qt.LeftButton)
                app.processEvents()
                card = window._preview_canvas._widgets[0]
                assert card._sl_conn.isEnabled(), cycle
                assert not card._sl_disconn.isEnabled(), cycle
                card._sl_port.clear()
                card._sl_port.addItem("TEST test port")
                port = Port()
                with patch.object(pyserial, "Serial", return_value=port):
                    QTest.mouseClick(card._sl_conn, Qt.LeftButton)
                assert serialManager.is_connected, cycle
                assert not card._sl_conn.isEnabled()
                assert card._sl_disconn.isEnabled()
                QTest.mouseClick(window._stop_btn, Qt.LeftButton)
                assert not serialManager.is_connected
                assert not port.is_open
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                assert not errors, errors
        """)

    def test_parser_override_discards_other_mode_config_and_same_mode_keeps_it(self):
        self.run_both([control("serial", "SerialConfigCard", {
            "defaultParser": "modbus",
        })], r"""
            from collections import deque
            from unittest.mock import patch
            from PyQt5.QtTest import QSignalSpy
            import serial as pyserial
            class ReadPort(MemoryPort):
                def __init__(self, packet):
                    super().__init__()
                    self.packets = deque([packet])
                @property
                def in_waiting(self):
                    return len(self.packets[0]) if self.packets else 0
                def read(self, count):
                    return self.packets.popleft()

            serial.disconnect()
            config = {"parser": "hex", "parserConfig": {
                "header": "AA55", "footer": "55AA",
                "fields": [["temperature", 0, 2, "uint16"]],
            }}
            serial.configure(config)
            failures, samples = [], []
            serial.error.connect(failures.append)
            serial.dataReceived.connect(samples.append)
            card = widgets["serial"]
            card._port_combo.clear()
            card._port_combo.addItem("TEST test port")
            for selection, packet, expected in (
                    ("modbus", bytes.fromhex("010302002a399b"),
                     {"slave": 1, "fc": 3, "reg0": 42}),
                    ("项目设置", bytes.fromhex("aa55002a55aa"), {"temperature": 42}),
                    ("hex", bytes.fromhex("aa55002b55aa"), {"temperature": 43})):
                card._parser_combo.setCurrentText(selection)
                received = QSignalSpy(serial.dataReceived)
                with patch.object(pyserial, "Serial", return_value=ReadPort(packet)):
                    QTest.mouseClick(card._connect_btn, Qt.LeftButton)
                    assert received or received.wait(3000), (selection, failures)
                assert serial.is_connected
                assert samples[-1] == expected, samples
                assert not failures, failures
                QTest.mouseClick(card._disconnect_btn, Qt.LeftButton)
                assert not serial.is_connected
            assert config["parserConfig"]["fields"] == [["temperature", 0, 2, "uint16"]]
        """)

    def test_modbus_reports_failed_or_short_writes_and_stops_polling(self):
        self.run_both([control("bus", "ModbusConfigCard", {
            "defaultPoll": 60000,
        })], r"""
            bus = widgets["bus"]
            failures = []
            serial.error.connect(failures.append)
            original_write = port.write
            attempts = []
            for outcome in ("exception", 0, 4):
                def failing_write(payload):
                    attempts.append(payload)
                    if outcome == "exception":
                        raise OSError("device unplugged during write")
                    return outcome
                port.write = failing_write
                QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
                assert bus._poll_timer.isActive()
                bus._poll_timer.timeout.emit()
                assert not bus._poll_timer.isActive()
                assert bus._send_btn.isEnabled()
                assert "发送失败" in bus._status.text(), bus._status.text()
                assert "已发送" not in bus._status.text()
                assert not sent
                assert not errors, errors
            assert len(attempts) == len(failures) == 3
            assert "0/8" in failures[1] and "4/8" in failures[2], failures
            port.write = original_write
            QTest.mouseClick(bus._send_btn, Qt.LeftButton)
            frame = bytes.fromhex("010300000001840a")
            check_payloads([frame])
            assert "已发送" in bus._status.text()
            assert serial.send_text("READ\n") is True
            check_payloads([frame, b"READ\n"])
            serial.disconnect()
            assert serial.send(frame) is False
            check_payloads([frame, b"READ\n"])
        """)

    def test_exported_cards_replacing_handler_disconnect_the_old_handler(self):
        self.run_both([
            control("bus", "ModbusConfigCard"),
            control("recv", "DataRecvCard"),
            control("log", "LogBox"),
        ], r"""
            if os.environ["APPLICATION_MODE"] == "export":
                from serial_handler import SerialHandler
                replacement = SerialHandler()
                for widget in widgets.values():
                    widget.set_serial_handler(replacement)
                    widget.set_serial_handler(replacement)
                serial.connected.emit("OLD")
                serial.error.emit("OLD")
                serial.rawReceived.emit(b"OLD\n")
                replacement.connected.emit("NEW")
                replacement.rawReceived.emit(b"NEW\n")
                assert widgets["recv"]._text.toPlainText().count("已连接: NEW") == 1
                assert widgets["log"]._text.toPlainText().count("已连接: NEW") == 1
                assert "OLD" not in widgets["recv"]._text.toPlainText()
                assert "OLD" not in widgets["log"]._text.toPlainText()
                for widget in widgets.values():
                    widget.set_serial_handler(None)
                replacement.disconnect()
        """)
