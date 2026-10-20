"""Exercise command failures through real preview and standalone Qt callbacks."""
import unittest

import test_preview_export_parity as parity
from app.core.command_runtime import command_modbus_frame


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
        self.assertEqual(command_modbus_frame(2, 3, 7, 125).hex(), "02030007007d3419")
