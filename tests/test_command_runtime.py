"""Exercise command failures through real preview and standalone Qt callbacks."""
import unittest

from types import SimpleNamespace

import test_preview_export_parity as parity
from app.core import command_runtime
from app.core.command_runtime import (
    command_modbus_frame, command_modbus_tcp_frame, send_modbus_command,
)


class CommandRuntimeTests(unittest.TestCase):
    run_both = parity.PreviewExportParityTests.run_both

    def test_hex_delimiters_are_normalized_and_invalid_fields_are_not_dropped(self):
        self.run_both([
            parity.control("hex", "PushButton", {
                "commandMode": "HEX", "command": "1", "frameHeader": "A",
                "frameTail": " B ", "commandTemplate": "10 {value}",
            }),
            parity.control("bad_header", "PushButton", {
                "commandMode": "HEX", "command": "01", "frameHeader": "GG",
            }, 1),
            parity.control("bad_tail", "PushButton", {
                "commandMode": "HEX", "command": "01", "frameTail": "ZZ",
            }, 2),
        ], r"""
            for name in ("bad_header", "bad_tail"):
                QTest.mouseClick(widgets[name], Qt.LeftButton)
                app.processEvents()
                check_payloads([])
            QTest.mouseClick(widgets["hex"], Qt.LeftButton)
            check_payloads([bytes.fromhex("0a01010b")])
        """)

    def test_packed_float_failures_do_not_escape_and_valid_input_recovers(self):
        self.run_both([
            parity.control("packed", "LineEdit", {
                "commandMode": "HEX", "sendOnEnter": True, "dataType": "float32",
                "frameHeader": "A", "frameTail": "B", "commandTemplate": "10 {value}",
            }),
        ], r"""
            control = widgets["packed"]
            for value in ("1e100", "-1e100", "nan", "inf", "-inf", "bad"):
                control.setText(value)
                QTest.keyClick(control, Qt.Key_Return)
                app.processEvents()
                check_payloads([])
            control.setText("1.5")
            QTest.keyClick(control, Qt.Key_Return)
            check_payloads([bytes.fromhex("0a103fc000000b")])
        """)

    def test_modbus_input_rejects_bad_values_without_default_writes_or_exceptions(self):
        self.run_both([
            parity.control("value", "LineEdit", {
                "commandMode": "Modbus", "mbSlave": 2, "mbAddress": 7,
                "commandTemplate": "SET {value}",
            }),
        ], r"""
            control = widgets["value"]
            for value in ("abc", "", " ", "-1", "65536", "1.5", "9" * 100):
                control.setText(value)
                QTest.keyClick(control, Qt.Key_Return)
                app.processEvents()
                check_payloads([])
            for value, expected in (
                    ("42", "02060007002ab9e7"), ("65535", "02060007ffff3988")):
                control.setText(value)
                QTest.keyClick(control, Qt.Key_Return)
                if value == "42":
                    frames = [bytes.fromhex(expected)]
                else:
                    frames.append(bytes.fromhex(expected))
                check_payloads(frames)
        """)

    def test_modbus_buttons_ignore_hidden_text_and_template_after_mode_change(self):
        self.run_both([
            parity.control("write", "PushButton", {
                "commandMode": "Modbus", "mbSlave": 2, "mbAddress": 7,
                "mbFunc": "06 写单寄存器", "mbValue": 5,
                "command": "77", "commandTemplate": "OLD {value}",
            }),
            parity.control("read", "PushButton", {
                "commandMode": "Modbus", "mbSlave": 2, "mbAddress": 7, "mbValue": 2,
                "command": "77", "commandTemplate": "OLD {value}",
            }, 1),
        ], r"""
            QTest.mouseClick(widgets["write"], Qt.LeftButton)
            QTest.mouseClick(widgets["read"], Qt.LeftButton)
            check_payloads([bytes.fromhex("020600070005f83b"),
                            bytes.fromhex("02030007000275f9")])
        """)

    def test_modbus_numeric_controls_reject_negative_and_preserve_valid_commands(self):
        self.run_both([
            parity.control(kind, kind, {
                "commandMode": "Modbus", "mbSlave": 2, "mbAddress": 7,
                "minimum": -10, "maximum": 99999, "value": 0,
                "commandTemplate": "OLD {value}",
            }, row)
            for row, kind in enumerate(("Slider", "SpinBox"))
        ], r"""
            frames = []
            for kind in ("Slider", "SpinBox"):
                control = widgets[kind]
                for value in (-1, 65536):
                    control.setValue(value)
                    app.processEvents()
                    check_payloads(frames)
                control.setValue(42)
                frames.append(bytes.fromhex("02060007002ab9e7"))
                check_payloads(frames)
        """)

    def test_empty_text_input_does_not_send_a_partial_template(self):
        self.run_both([
            parity.control("text", "LineEdit", {
                "sendOnEnter": True, "commandTemplate": "SET {value}",
                "commandNewline": "\\n",
            }),
        ], r"""
            control = widgets["text"]
            for value in ("", "   "):
                control.setText(value)
                QTest.keyClick(control, Qt.Key_Return)
                check_payloads([])
            control.setText("42")
            QTest.keyClick(control, Qt.Key_Return)
            check_payloads([b"SET 42\n"])
        """)

    def test_command_lists_are_independent_and_negative_selection_sends_nothing(self):
        self.run_both([
            parity.control("first-list 'quoted'", "ComboBox", {
                "items": "First\nSecond", "commands": "12\n34", "commandMode": "Modbus",
                "mbSlave": 2, "mbAddress": 7,
            }),
            parity.control("second.list", "ComboBox", {
                "items": "First\nSecond", "commands": "ZERO\nONE", "sendOnSelect": True,
            }, 1),
        ], r"""
            first = widgets["first-list 'quoted'"]
            second = widgets["second.list"]
            first.currentIndexChanged.emit(-1)
            second.currentIndexChanged.emit(-1)
            check_payloads([])
            first.setCurrentIndex(1)
            second.setCurrentIndex(1)
            first.setCurrentIndex(0)
            check_payloads([bytes.fromhex("020600070022b821"), b"ONE\r\n",
                            bytes.fromhex("02060007000c383d")])
        """)

    def test_modbus_function_ranges_reject_invalid_protocol_requests(self):
        for slave, function, address, value in (
                (0, 6, 0, 1), (248, 6, 0, 1), (1, 6, -1, 1),
                (1, 6, 65536, 1), (1, 1, 0, 0), (1, 2, 0, 2001),
                (1, 3, 0, 126), (1, 4, 0, 0), (1, 5, 0, 1),
                (1, 6, 0, -1), (1, 6, 0, 65536), (1, 7, 0, 1)):
            with self.subTest(slave=slave, function=function, address=address, value=value):
                with self.assertRaises(ValueError):
                    command_modbus_frame(slave, function, address, value)
                with self.assertRaises(ValueError):
                    command_modbus_tcp_frame(slave, function, address, value)
        self.assertEqual(command_modbus_frame(2, 3, 7, 125).hex(), "02030007007d3419")

    def test_modbus_tcp_requests_carry_mbap_headers_and_rolling_transactions(self):
        for slave, function, address, value, expected in (
                (2, 3, 7, 125, "02030007007d"), (1, 1, 0, 8, "010100000008"),
                (1, 5, 0, 0xFF00, "01050000ff00"), (1, 6, 10, 500, "0106000a01f4")):
            with self.subTest(function=function):
                frame = command_modbus_tcp_frame(slave, function, address, value, transaction=0x1234)
                self.assertEqual(frame.hex(), "123400000006" + expected)
        command_runtime._transaction[0] = 0xFFFE
        identifiers = [command_modbus_tcp_frame(1, 3, 0, 1)[:2].hex() for _ in range(3)]
        self.assertEqual(identifiers, ["ffff", "0000", "0001"])

    def test_requests_are_framed_per_link_and_validated_before_any_send(self):
        class Link:
            def __init__(self, parser_type, connected=True, accept=True):
                self.parser_type, self.is_connected, self.accept = parser_type, connected, accept
                self.sent = []

            def send(self, data):
                self.sent.append(data)
                return self.accept

        serial, tcp, idle, failing = Link("line"), Link("modbus_tcp"), Link("modbus_tcp", False), Link("modbus", accept=False)
        hub = SimpleNamespace(connected_links=[serial, tcp, failing], is_connected=True)
        command_runtime._transaction[0] = 41
        sent = send_modbus_command(hub, 2, 6, 7, 42)
        rtu = bytes.fromhex("02060007002ab9e7")
        self.assertEqual(serial.sent, [rtu])
        self.assertEqual(tcp.sent, [bytes.fromhex("002a000000060206000700" + "2a")])
        self.assertEqual(failing.sent, [rtu])
        self.assertEqual(sent, [rtu, tcp.sent[0]], "only accepted frames are reported")
        self.assertEqual(idle.sent, [])
        with self.assertRaises(ValueError):
            send_modbus_command(hub, 2, 6, 7, "not a number")
        self.assertEqual(len(serial.sent), 1)
        # A bare link works like a one-link hub; nothing is sent while it is down.
        self.assertEqual(send_modbus_command(tcp, 1, 3, 0, 2), tcp.sent[-1:])
        self.assertEqual(tcp.sent[-1][6:], bytes.fromhex("010300000002"))
        self.assertEqual(send_modbus_command(idle, 1, 3, 0, 2), [])
        self.assertEqual(idle.sent, [])
