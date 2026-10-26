"""Exercise packet boundaries and the host/export communication contract."""
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt5.QtCore import QObject, Qt

from app.core import protocol_parser as protocol
from app.core import serial_runtime
from app.core.code_generator import _gen_serial_handler, _gen_data_binding, _extract_bindings
from app.core.data_binding import BindingEntry


def frame(payload):
    return payload + protocol.modbus_crc(payload)


class ProtocolTests(unittest.TestCase):
    def test_line_split_at_every_byte_and_batch_preserves_all_samples(self):
        message = b'temp=25.3,humidity=60\r\n{"temp":26,"msg":"a\\nb"}\n1,2\n'
        expected = [{"temp": 25.3, "humidity": 60},
                    {"temp": 26, "msg": "a\nb"}, {"ch0": 1, "ch1": 2}]
        for split in range(len(message) + 1):
            with self.subTest(split=split):
                parser = protocol.LineParser()
                self.assertEqual(parser.feed(message[:split]) + parser.feed(message[split:]),
                                 expected)

    def test_partial_records_wait_for_real_newline(self):
        parser = protocol.LineParser()
        self.assertEqual(parser.feed(b"temp=2"), [])
        self.assertEqual(parser.feed(b"5.3"), [])
        self.assertEqual(parser.feed(b"\n"), [{"temp": 25.3}])
        self.assertEqual(parser.feed(b'{"temp":'), [])
        self.assertEqual(parser.feed(b"26}\n"), [{"temp": 26}])
        self.assertEqual(parser.feed(b'{"invalid":}\n'), [])

    def test_oversized_line_is_discarded_until_boundary_then_recovers(self):
        parser = protocol.LineParser(max_buffer=32)
        self.assertEqual(parser.feed(b"x" * 10000), [])
        self.assertLessEqual(len(parser._buf), 32)
        self.assertEqual(parser.feed(b"temp=1\ntemp=2\n"), [{"temp": 2}])

    def test_hex_split_and_coalesced_frames(self):
        wire = bytes.fromhex("aa55000155aaaa55000255aa")
        for split in range(len(wire) + 1):
            parser = protocol.HexFrameParser(fields=[("v", 0, 2, "uint16")])
            self.assertEqual(parser.feed(wire[:split]) + parser.feed(wire[split:]),
                             [{"v": 1}, {"v": 2}])

    def test_hex_noise_and_incomplete_frames_are_bounded(self):
        parser = protocol.HexFrameParser(fields=[("v", 0, 1, "uint8")], max_buffer=32)
        parser.feed(b"x" * 10000 + b"\xaa")
        self.assertLessEqual(len(parser._buf), 1)
        self.assertEqual(parser.feed(bytes.fromhex("550155aa")), [{"v": 1}])
        parser.feed(b"\xaa\x55" + b"x" * 10000)
        self.assertLessEqual(len(parser._buf), 32)
        self.assertEqual(parser.feed(bytes.fromhex("aa550255aa")), [{"v": 2}])
        with self.assertRaises(ValueError):
            protocol.HexFrameParser(header=b"")

    def test_modbus_split_all_response_types_and_multiple_frames(self):
        messages = [
            (bytes.fromhex("0103021234"), {"slave": 1, "fc": 3, "reg0": 0x1234}),
            (bytes.fromhex("020602000005"), {"slave": 2, "fc": 6, "address": 512, "value": 5}),
            (bytes.fromhex("018302"), {"slave": 1, "fc": 131, "error": 2}),
        ]
        wire = b"".join(frame(p) for p, _ in messages)
        for split in range(len(wire) + 1):
            parser = protocol.ModbusRTUParser()
            self.assertEqual(parser.feed(wire[:split]) + parser.feed(wire[split:]),
                             [result for _, result in messages])

    def test_modbus_tcp_split_all_response_types_and_multiple_frames(self):
        messages = [
            (bytes.fromhex("0001 0000 0009 01 03 06 03e8 09c4 0064".replace(" ", "")),
             {"slave": 1, "fc": 3, "reg0": 1000, "reg1": 2500, "reg2": 100}),
            (bytes.fromhex("0002 0000 0004 11 01 01 05".replace(" ", "")),
             {"slave": 17, "fc": 1, "coil0": 1, "coil1": 0, "coil2": 1, "coil3": 0,
              "coil4": 0, "coil5": 0, "coil6": 0, "coil7": 0}),
            (bytes.fromhex("0003 0000 0006 02 06 0200 0005".replace(" ", "")),
             {"slave": 2, "fc": 6, "address": 512, "value": 5}),
            (bytes.fromhex("0004 0000 0003 01 83 02".replace(" ", "")),
             {"slave": 1, "fc": 131, "error": 2}),
        ]
        wire = b"".join(adu for adu, _ in messages)
        for split in range(len(wire) + 1):
            parser = protocol.ModbusTCPParser()
            self.assertEqual(parser.feed(wire[:split]) + parser.feed(wire[split:]),
                             [result for _, result in messages])
        named = protocol.create_parser("modbus_tcp", {"fields": ["temperature"]})
        self.assertEqual(named.feed(messages[0][0]),
                         [{"slave": 1, "fc": 3, "temperature": 1000, "reg1": 2500, "reg2": 100}])

    def test_modbus_tcp_rejects_bad_headers_and_inconsistent_lengths(self):
        valid = bytes.fromhex("000100000005010302002a")
        parser = protocol.ModbusTCPParser()
        for noise in (
            bytes.fromhex("00010001000501030200ff"),      # protocol id must be 0
            bytes.fromhex("000100000006010302002aff"),    # length does not match the byte count
            bytes.fromhex("0001000000050103030000"),      # odd register byte count
            bytes.fromhex("000100000005010603000000"),    # write echo must have length 6
            bytes.fromhex("0001000000030199"),            # unknown function code
        ):
            with self.subTest(noise=noise.hex()):
                self.assertEqual(parser.feed(noise), [])
        self.assertEqual(parser.feed(b"\xff" * 10000 + valid),
                         [{"slave": 1, "fc": 3, "reg0": 42}])
        self.assertLessEqual(len(parser._buf), 9)
        request = protocol.build_modbus_tcp_frame(1, 3, 0, count=2, transaction=7)
        self.assertEqual(request.hex(), "000700000006010300000002")
        self.assertEqual(parser.feed(request), [], "requests are not responses")

    def test_modbus_bad_crc_and_noise_do_not_hide_next_valid_response(self):
        valid = frame(bytes.fromhex("0103020007"))
        parser = protocol.ModbusRTUParser()
        self.assertEqual(parser.feed(bytes.fromhex("0183020000")), [])
        self.assertEqual(parser.feed(b"\xff" * 10000 + b"\x01\x03\xf0" + valid),
                         [{"slave": 1, "fc": 3, "reg0": 7}])
        self.assertLessEqual(len(parser._buf), 255)


class RuntimeParityTests(unittest.TestCase):
    def runtimes(self, config=None):
        exported = {}
        exec(_gen_serial_handler(config or {}), exported)
        return (vars(serial_runtime), exported)

    def test_reader_emits_all_frames_for_host_and_export(self):
        for namespace in self.runtimes():
            for parser_name, packet, expected in (
                ("LineParser", b"a=1\na=2\n", [{"a": 1}, {"a": 2}]),
                ("ModbusRTUParser", frame(bytes.fromhex("0103020001")) * 2,
                 [{"slave": 1, "fc": 3, "reg0": 1}] * 2),
                ("ModbusTCPParser", bytes.fromhex("000100000005010302000a") * 2,
                 [{"slave": 1, "fc": 3, "reg0": 10}] * 2),
            ):
                parser_class = namespace.get(parser_name, getattr(protocol, parser_name))
                chunks = [packet[:2], packet[2:]]
                port = Mock()
                port.in_waiting = 100
                reader = namespace["SerialReaderThread"](port, parser_class())
                def read(_):
                    chunk = chunks.pop(0)
                    if not chunks:
                        reader._running = False
                    return chunk
                port.read.side_effect = read
                parsed, raw = [], []
                reader.parsedReceived.connect(parsed.append, Qt.DirectConnection)
                reader.rawReceived.connect(raw.append, Qt.DirectConnection)
                reader.run()
                self.assertEqual(parsed, expected)
                self.assertEqual(b"".join(raw), packet)

    def test_all_serial_options_and_parser_config_survive_export(self):
        config = {"baudRate": 19200, "dataBits": 7, "parity": "Even",
                  "stopBits": 2, "flowControl": "rtscts", "parser": "modbus",
                  "parserConfig": {"fields": ["temperature"]}}
        for namespace in self.runtimes(config):
            with patch.object(namespace["serial"], "Serial") as factory, \
                 patch.dict(namespace, {"SerialReaderThread": Mock()}):
                handler = namespace["SerialHandler"](config=config)
                self.assertTrue(handler.connect("TEST"))
                factory.assert_called_once_with(
                    port="TEST", baudrate=19200, bytesize=7, parity="E", stopbits=2,
                    timeout=0.1, write_timeout=1, rtscts=True, xonxoff=False, dsrdtr=False)
                self.assertEqual(handler._parser.feed(frame(bytes.fromhex("0103020009"))),
                                 [{"slave": 1, "fc": 3, "temperature": 9}])
                handler.disconnect()

    def test_export_default_config_and_explicit_overrides(self):
        exported = self.runtimes({"baudRate": 9600, "parser": "modbus"})[1]
        with patch.object(exported["serial"], "Serial") as factory, \
             patch.dict(exported, {"SerialReaderThread": Mock()}):
            handler = exported["SerialHandler"]()
            self.assertTrue(handler.connect("TEST", databits=7, parity="O", stopbits=1.5,
                                            flowcontrol="xonxoff", parser_type="line",
                                            parser_config={"separator": ";"}))
            self.assertEqual(factory.call_args.kwargs["baudrate"], 9600)
            self.assertEqual(factory.call_args.kwargs["bytesize"], 7)
            self.assertEqual(factory.call_args.kwargs["parity"], "O")
            self.assertEqual(factory.call_args.kwargs["stopbits"], 1.5)
            self.assertTrue(factory.call_args.kwargs["xonxoff"])
            self.assertEqual(handler._parser.feed(b"a=1;b=2\n"), [{"a": 1, "b": 2}])
            handler.disconnect()

    def test_invalid_parser_does_not_open_port(self):
        for namespace in self.runtimes():
            with patch.object(namespace["serial"], "Serial") as factory:
                handler = namespace["SerialHandler"]()
                self.assertFalse(handler.connect("TEST", parser_type="hex",
                                                  parser_config={"header": ""}))
                factory.assert_not_called()


class RawBindingTests(unittest.TestCase):
    def test_host_hex_binding_keeps_partial_and_multiple_frames(self):
        binding = BindingEntry("value", "text", parse_mode="HEX字节提取",
                               frame_header="AA55", frame_tail="55AA",
                               data_type="uint16")
        wire = bytes.fromhex("aa55000155aaaa55000255aa")
        for split in range(len(wire) + 1):
            binding._raw_frames.reset()
            self.assertEqual(list(binding.extract_all_from_raw(wire[:split])) +
                             list(binding.extract_all_from_raw(wire[split:])), [1, 2])

    def test_export_independent_bindings_and_disconnect_reset(self):
        bindings = _extract_bindings([
            {"id": "first", "type": "Label", "binding": {
                "parseMode": "HEX字节提取", "frameHeader": "AA55",
                "frameTail": "55AA", "dataType": "uint16"}},
            {"id": "second", "type": "Label", "binding": {
                "parseMode": "HEX字节提取", "frameHeader": "BB66",
                "frameTail": "66BB", "dataType": "uint16"}},
        ])
        namespace = {}
        with patch.dict(sys.modules, {"serial_handler": SimpleNamespace(
                RawFrameBuffer=protocol.RawFrameBuffer)}):
            exec(_gen_data_binding(bindings), namespace)
        first, second = Mock(), Mock()
        handler = serial_runtime.SerialHandler()
        ui = QObject()
        ui.widgets = {"first": first, "second": second}
        binding = namespace["DataBinding"](ui, handler)
        handler.rawReceived.emit(bytes.fromhex("bb66000766bb"))
        second.setText.assert_called_once_with("7")
        first.setText.assert_not_called()
        handler.rawReceived.emit(bytes.fromhex("aa5500"))
        handler.disconnected.emit()
        handler.rawReceived.emit(bytes.fromhex("0155aa"))
        first.setText.assert_not_called()
        handler.rawReceived.emit(bytes.fromhex("aa55000155aaaa55000255aa"))
        self.assertEqual([call.args[0] for call in first.setText.call_args_list], ["1", "2"])
