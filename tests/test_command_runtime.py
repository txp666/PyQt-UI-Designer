"""Exercise command failures through real preview and standalone Qt callbacks."""
import unittest

from types import SimpleNamespace

import test_preview_export_parity as parity
from app.core import command_runtime
from app.core.command_runtime import (
    command_modbus_frame, command_modbus_tcp_frame, send_modbus_command,
)
from app.core.protocol_parser import modbus_crc


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

    def test_controls_write_typed_values_over_fc16(self):
        fc16 = {"commandMode": "Modbus", "mbSlave": 1, "mbFunc": "16 写多个寄存器", "mbAddress": 100}
        self.run_both([
            parity.control("spin", "SpinBox", {**fc16, "mbDataType": "float32", "maximum": 999}),
            parity.control("text", "LineEdit", {**fc16, "mbDataType": "int32",
                                                "mbRegOrder": "小端(CD AB)"}, 1),
            parity.control("button", "PushButton", {**fc16, "mbValue": 7}, 2),
            parity.control("short", "SpinBox", {**fc16, "mbFunc": "06 写单寄存器",
                                                "mbDataType": "int16", "minimum": -99}, 3),
        ], r"""
            from serial_handler import modbus_crc
            def rtu(pdu):
                pdu = bytes.fromhex(pdu)
                return pdu + modbus_crc(pdu)
            frames = []
            widgets["spin"].setValue(25)
            frames.append(rtu("0110006400020441c80000"))
            check_payloads(frames)
            widgets["text"].setText("-2")
            QTest.keyClick(widgets["text"], Qt.Key_Return)
            frames.append(rtu("01100064000204fffeffff"))
            check_payloads(frames)
            QTest.mouseClick(widgets["button"], Qt.LeftButton)
            frames.append(rtu("01100064000102 0007"))
            check_payloads(frames)
            widgets["short"].setValue(-5)
            frames.append(rtu("01060064fffb"))
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

    def test_typed_register_writes_use_fc06_or_fc16_and_reject_values_that_do_not_fit(self):
        for request, pdu in (
                ((1, 16, 100, 25.3, "float32"), "0110006400020441ca6666"),
                ((1, 16, 100, "25.3", "float32", "小端(CD AB)"), "011000640002046666 41ca"),
                ((1, 16, 0, -2, "int32"), "01100000000204ffff fffe"),
                ((1, 16, 0, 70000, "uint32"), "011000000002040001 1170"),
                ((1, 16, 5, 42), "0110000500010200 2a"),
                ((1, 6, 7, -1, "int16"), "01060007ffff")):
            with self.subTest(request=request):
                pdu = bytes.fromhex(pdu.replace(" ", ""))
                self.assertEqual(command_modbus_frame(*request), pdu + modbus_crc(pdu))
        self.assertEqual(
            command_modbus_tcp_frame(1, 16, 100, 25.3, 0x1234, "float32").hex(),
            "12340000000b" + "0110006400020441ca6666")
        for request in ((1, 6, 7, 1, "float32"), (1, 16, 65535, 1, "uint32"),
                        (1, 16, 0, 1e39, "float32"), (1, 16, 0, "nan", "float32"),
                        (1, 16, 0, 40000, "int16"), (1, 16, 0, "1.5", "int32"),
                        (1, 16, 0, 1, "double")):
            with self.subTest(request=request), self.assertRaises(ValueError):
                command_modbus_frame(*request)

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
        ascii_link = Link("modbus_ascii")
        hub = SimpleNamespace(connected_links=[serial, tcp, failing, ascii_link], is_connected=True)
        command_runtime._transaction[0] = 41
        sent = send_modbus_command(hub, 2, 6, 7, 42)
        rtu = bytes.fromhex("02060007002ab9e7")
        self.assertEqual(serial.sent, [rtu])
        self.assertEqual(tcp.sent, [bytes.fromhex("002a000000060206000700" + "2a")])
        self.assertEqual(failing.sent, [rtu])
        # Modbus ASCII: uppercase hex pairs of the RTU bytes without CRC, then the LRC, CR LF.
        self.assertEqual(ascii_link.sent, [b":02060007002AC7\r\n"])
        self.assertEqual(sent, [rtu, tcp.sent[0], ascii_link.sent[0]], "only accepted frames are reported")
        send_modbus_command(ascii_link, 1, 16, 100, 25.3, "float32")
        self.assertEqual(ascii_link.sent[-1], b":0110006400020441CA6666AE\r\n")
        self.assertEqual(idle.sent, [])
        with self.assertRaises(ValueError):
            send_modbus_command(hub, 2, 6, 7, "not a number")
        self.assertEqual(len(serial.sent), 1)
        # A bare link works like a one-link hub; nothing is sent while it is down.
        self.assertEqual(send_modbus_command(tcp, 1, 3, 0, 2), tcp.sent[-1:])
        self.assertEqual(tcp.sent[-1][6:], bytes.fromhex("010300000002"))
        self.assertEqual(send_modbus_command(idle, 1, 3, 0, 2), [])
        self.assertEqual(idle.sent, [])
