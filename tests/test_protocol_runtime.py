"""Parser behaviour is pinned by golden vectors; the hand-written tests cover what a vector cannot
show: bounded buffers, requests shared between parsers, the serial reader, bindings and exports."""
import json
from pathlib import Path
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt5.QtCore import QObject, Qt

from app.core import protocol_parser as protocol
from app.core import serial_runtime
from app.core.code_generator import _gen_serial_handler, _gen_data_binding, _extract_bindings
from app.core.data_binding import BindingEntry

# Byte streams and what each parser cuts and reads from them, shared verbatim with FluentHMI Studio,
# whose parser reproduces every result.
VECTORS = Path(__file__).resolve().parent / "data" / "parser_vectors.json"

# Frames counted by a length field after an AA 55 header and checked by a byte sum.
COUNTED = {"header": "AA55", "footer": "", "lengthOffset": 2, "checksum": "和校验",
           "fields": [["cmd", 1, 1, "uint8"], ["temp", 2, 2, "int16", "小端(LE)"]]}
FRAMES = [bytes.fromhex("aa550401f6ff3c35"), bytes.fromhex("aa5504021000283d")]
MESSAGES = [{"cmd": 1, "temp": -10}, {"cmd": 2, "temp": 16}]


def frame(payload):
    return payload + protocol.modbus_crc(payload)


def exported_serial_runtime(config=None):
    namespace = {}
    exec(_gen_serial_handler(config or {}), namespace)
    return namespace


class ParserTests(unittest.TestCase):
    def test_every_vector_reads_as_recorded_in_the_designer_and_the_export(self):
        cases = json.loads(VECTORS.read_text(encoding="utf-8"))
        for runtime, namespace in (("host", vars(protocol)), ("export", exported_serial_runtime())):
            for case in cases:
                with self.subTest(runtime=runtime, name=case["name"]):
                    self.check_vector(namespace, case)

    def check_vector(self, namespace, case):
        requests = namespace["ModbusRequests"]()
        if "error" in case:
            with self.assertRaises(ValueError) as caught:
                namespace["create_parser"](case["type"], case["config"], requests)
            self.assertEqual(str(caught.exception), case["error"])
            return
        parser = namespace["create_parser"](case["type"], case["config"], requests)
        results = []
        for step in case["steps"]:
            if "note" in step:  # a request the link sent
                requests.note_frame(bytes.fromhex(step["note"]), case["type"])
                units = []
            elif "flush" in step:
                units = parser.flush()
            else:
                units = parser.frames(bytes.fromhex(step["feed"]))
            results.append([{"frame": unit.hex(), "messages": parser.parse(unit)} for unit in units])
        self.assertEqual(results, case["expect"])

    def test_noise_never_grows_a_buffer_past_the_longest_frame(self):
        for parser_type, config, longest, valid, message in (
            ("line", {}, 65536, b"\na=1\n", {"a": 1}),
            ("hex", {"header": "AA55", "footer": "55AA", "fields": [["v", 0, 2, "uint16"]]}, 65536,
             bytes.fromhex("aa55000755aa"), {"v": 7}),
            ("modbus", {}, 256, frame(bytes.fromhex("0103020007")), {"slave": 1, "fc": 3, "reg0": 7}),
            ("modbus_tcp", {}, 260, bytes.fromhex("000100000005010302002a"), {"slave": 1, "fc": 3, "reg0": 42}),
            ("modbus_ascii", {}, 511, b":010302000AF0\r\n", {"slave": 1, "fc": 3, "reg0": 10}),
        ):
            with self.subTest(parser=parser_type):
                parser = protocol.create_parser(parser_type, config)
                self.assertEqual(parser.feed(b"\xff" * (longest + 1000)), [])
                self.assertLessEqual(len(parser._buf), longest)
                self.assertEqual(parser.feed(valid), [message])


class ModbusRequestTests(unittest.TestCase):
    def test_each_parser_names_its_reply_to_a_read_once(self):
        # A server's clients share the link's requests: each names its reply, and only once.
        requests = protocol.ModbusRequests()
        parsers = [protocol.create_parser("modbus", {}, requests) for _ in range(2)]
        requests.note_frame(protocol.build_modbus_frame(1, 3, 300, count=1), "modbus")
        reply = frame(bytes.fromhex("0103020005"))
        for parser in parsers:
            self.assertEqual(parser.feed(reply), [{"slave": 1, "fc": 3, "reg0": 5, "start": 300, "hr300": 5}])
            self.assertEqual(parser.feed(reply), [{"slave": 1, "fc": 3, "reg0": 5}], "no read left to name it")


class BindingTests(unittest.TestCase):
    def test_host_and_export_modbus_bindings_read_register_tables_alike(self):
        cases = [  # binding, expected value
            ({"mbRegIndex": 1}, 0x6666),
            ({"mbArea": "保持寄存器", "mbRegIndex": 100, "mbDataType": "float32"}, 25.299999237060547),
            ({"mbArea": "保持寄存器", "mbRegIndex": 101}, 0x6666),
            ({"mbArea": "保持寄存器", "mbRegIndex": 101, "mbDataType": "float32"}, None),
            ({"mbArea": "保持寄存器", "mbRegIndex": 1}, None),
            ({"mbArea": "输入寄存器", "mbRegIndex": 100}, None),
            ({"mbArea": "线圈", "mbRegIndex": 9}, 1),
            ({"mbArea": "保持寄存器", "mbRegIndex": 100, "mbSlaveFilter": 2}, None),
        ]
        registers = {"slave": 1, "fc": 3, "reg0": 0x41CA, "reg1": 0x6666,
                     "start": 100, "hr100": 0x41CA, "hr101": 0x6666}
        coils = {"slave": 1, "fc": 1, "coil0": 1, "start": 9, "co9": 1}
        widgets = [{"id": f"w{i}", "type": "Label", "binding": {"parseMode": "Modbus", **b}}
                   for i, (b, _) in enumerate(cases)]
        namespace = {}
        exec(_gen_data_binding(_extract_bindings(widgets)), namespace)
        handler = serial_runtime.SerialHandler()
        ui = QObject()
        ui.widgets = {w["id"]: Mock() for w in widgets}
        binding = namespace["DataBinding"](ui, handler)
        for data in (registers, coils):
            handler.dataReceived.emit(data)
        for index, (config, expected) in enumerate(cases):
            with self.subTest(binding=config):
                host = BindingEntry(f"w{index}", "text", parse_mode="Modbus",
                                    mb_reg_index=config["mbRegIndex"],
                                    mb_data_type=config.get("mbDataType", "uint16"),
                                    mb_slave_filter=config.get("mbSlaveFilter", -1),
                                    mb_area=config.get("mbArea", "响应内序号"))
                values = [v for v in map(host.extract_from_parsed, (registers, coils)) if v is not None]
                self.assertEqual(values, [] if expected is None else [expected])
                shown = [call.args[0] for call in ui.widgets[f"w{index}"].setText.call_args_list]
                self.assertEqual(shown, [] if expected is None else [str(expected)])

    def test_json_arrays_bind_by_index(self):
        message = protocol.create_parser("line").feed(b'[{"temp": 25.3}, 60]\n')[0]
        by_path = BindingEntry("w", "text", parse_mode="JSON路径", json_path="0.temp")
        by_key = BindingEntry("w", "text", parse_mode="键值匹配", key="1")
        self.assertEqual((by_path.extract_from_parsed(message), by_key.extract_from_parsed(message)), (25.3, 60))


class FakePort:
    """Hands out its chunks one read at a time, then stays quiet until ``done()`` stops the reader."""

    def __init__(self, chunks, done):
        self.chunks, self.done, self.reader = list(chunks), done, None
        self.deadline = time.monotonic() + 5  # never hang the suite

    @property
    def in_waiting(self):
        if self.done() or time.monotonic() > self.deadline:
            self.reader._running = False
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, size):
        return self.chunks.pop(0)


class RuntimeParityTests(unittest.TestCase):
    def runtimes(self, config=None):
        return vars(serial_runtime), exported_serial_runtime(config)

    def test_reader_emits_all_frames_for_host_and_export(self):
        for namespace in self.runtimes():
            for parser_name, packet, expected in (
                ("LineParser", b"a=1\na=2\n", [{"a": 1}, {"a": 2}]),
                ("ModbusRTUParser", frame(bytes.fromhex("0103020001")) * 2,
                 [{"slave": 1, "fc": 3, "reg0": 1}] * 2),
                ("ModbusTCPParser", bytes.fromhex("000100000005010302000a") * 2,
                 [{"slave": 1, "fc": 3, "reg0": 10}] * 2),
                ("ModbusASCIIParser", b":010302000AF0\r\n" * 2, [{"slave": 1, "fc": 3, "reg0": 10}] * 2),
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

    def test_reader_publishes_each_hex_frame_and_flushes_once_the_port_is_quiet(self):
        idle = {"header": "7E", "footer": "", "idleTimeout": 200, "fields": [["a", 0, 1, "uint8"]]}
        quiet_frame = bytes.fromhex("7e0102")
        for namespace in self.runtimes():
            for config, chunks, frames, messages in (
                (COUNTED, [b"\x12" + FRAMES[0][:3], FRAMES[0][3:] + FRAMES[1]], FRAMES, MESSAGES),
                (idle, [quiet_frame], [quiet_frame], [{"a": 1}]),  # one write: nothing but the quiet ends it
            ):
                with self.subTest(config=config):
                    events = []
                    port = FakePort(chunks, lambda: len(events) == 2 * len(frames))
                    reader = port.reader = namespace["SerialReaderThread"](
                        port, namespace["create_parser"]("hex", config))
                    reader.rawReceived.connect(events.append, Qt.DirectConnection)
                    reader.parsedReceived.connect(events.append, Qt.DirectConnection)
                    started = time.monotonic()
                    reader.run()
                    self.assertEqual(events, [item for pair in zip(frames, messages) for item in pair],
                                     "each frame, then its message")
                    if "idleTimeout" in config:
                        self.assertGreaterEqual(time.monotonic() - started, 0.2, "flushed after the quiet")

    def test_links_note_the_reads_they_send_before_writing(self):
        for namespace in self.runtimes():
            handler = namespace["SerialHandler"]()
            replies = []
            parser = namespace["create_parser"]("modbus", {}, handler.modbus_requests)  # the link's own
            class Port:
                is_open = True
                def write(self, data):
                    # A device answering at once: the read must already be noted.
                    replies.extend(parser.feed(frame(bytes.fromhex("01030400070008"))))
                    return len(data)
            handler._port = Port()
            handler.configure({"parser": "modbus"})
            # Any request bytes count, such as a frame typed in HEX mode.
            self.assertTrue(handler.send(protocol.build_modbus_frame(1, 3, 100, count=2)))
            self.assertEqual((replies[0]["start"], replies[0]["hr101"]), (100, 8))
            handler.configure({"parser": "line"})
            self.assertTrue(handler.send(protocol.build_modbus_frame(1, 3, 100, count=2)))
            self.assertNotIn("start", replies[1], "a link that does not parse Modbus notes nothing")
            handler._port = None

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
                                                  parser_config={"header": "XYZ"}))
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

    def test_raw_bindings_on_a_hex_link_count_from_the_frame_start(self):
        # A hex link publishes whole frames, so a binding needs no header or footer of its own.
        bindings = [("cmd", 3, "uint8", "大端(BE)", [1, 2]), ("temp", 4, "int16", "小端(LE)", [-10, 16])]
        widgets = [{"id": name, "type": "Label", "binding": {
            "parseMode": "HEX字节提取", "byteOffset": offset, "dataType": dtype, "byteOrder": order}}
            for name, offset, dtype, order, _values in bindings]
        namespace = {}
        with patch.dict(sys.modules, {"serial_handler": SimpleNamespace(
                RawFrameBuffer=protocol.RawFrameBuffer)}):
            exec(_gen_data_binding(_extract_bindings(widgets)), namespace)
        handler = serial_runtime.SerialHandler()
        ui = QObject()
        ui.widgets = {name: Mock() for name, *_rest in bindings}
        binding = namespace["DataBinding"](ui, handler)
        for unit in FRAMES:
            handler.rawReceived.emit(unit)
        for name, offset, dtype, order, values in bindings:
            with self.subTest(binding=name):
                host = BindingEntry(name, "text", parse_mode="HEX字节提取", byte_offset=offset,
                                    data_type=dtype, byte_order=order)
                self.assertEqual([v for unit in FRAMES for v in host.extract_all_from_raw(unit)], values)
                self.assertEqual([call.args[0] for call in ui.widgets[name].setText.call_args_list],
                                 [str(v) for v in values])
        # A binding from before, with a header of its own, still finds the payload inside each frame.
        framed = BindingEntry("cmd", "text", parse_mode="HEX字节提取", byte_offset=1,
                              data_type="uint8", frame_header="AA 55")
        self.assertEqual([v for unit in FRAMES for v in framed.extract_all_from_raw(unit)], [1, 2])

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
