"""Exercise packet boundaries and the host/export communication contract."""
import unittest
import sys
import time
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
            protocol.HexFrameParser(footer=b"")  # nothing would end a frame

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

    def test_modbus_rtu_names_registers_by_address_when_the_read_is_known(self):
        requests = protocol.ModbusRequests()
        parser = protocol.create_parser("modbus", {}, requests)
        requests.note(1, 3, 100, 2)
        requests.note(1, 1, 7, 3)
        requests.note(2, 4, 30, 1)
        self.assertEqual(parser.feed(frame(bytes.fromhex("01030441ca6666"))),
                         [{"slave": 1, "fc": 3, "reg0": 0x41CA, "reg1": 0x6666,
                           "start": 100, "hr100": 0x41CA, "hr101": 0x6666}])
        # Only the coils that were read get addresses; the rest of the last byte is padding.
        self.assertEqual(parser.feed(frame(bytes.fromhex("01010105"))),
                         [{"slave": 1, "fc": 1, **{f"coil{i}": (5 >> i) & 1 for i in range(8)},
                           "start": 7, "co7": 1, "co8": 0, "co9": 1}])
        # An exception answers the same read; a reply whose count differs gets no addresses.
        self.assertEqual(parser.feed(frame(bytes.fromhex("028402"))),
                         [{"slave": 2, "fc": 0x84, "error": 2, "start": 30}])
        self.assertEqual(parser.feed(frame(bytes.fromhex("02040400010002"))),
                         [{"slave": 2, "fc": 4, "reg0": 1, "reg1": 2}])
        # An RTU master waits for each reply, so the latest read of that slave and function is
        # answered, and only once: a second reply has no request left to name it.
        requests.note(1, 3, 100, 2)
        requests.note(1, 3, 200, 2)
        reply = frame(bytes.fromhex("010304000a000b"))
        self.assertEqual(parser.feed(reply)[0]["hr201"], 11)
        self.assertEqual(parser.feed(reply), [{"slave": 1, "fc": 3, "reg0": 10, "reg1": 11}])
        self.assertEqual(parser.feed(frame(bytes.fromhex("0503020001"))),
                         [{"slave": 5, "fc": 3, "reg0": 1}], "no request, no addresses")
        # Each stream answers a read once, so a server's clients all name their replies.
        requests.note(1, 3, 300, 1)
        second = protocol.create_parser("modbus", {}, requests)
        reply = frame(bytes.fromhex("0103020005"))
        self.assertEqual(parser.feed(reply)[0]["hr300"], 5)
        self.assertEqual(second.feed(reply)[0]["hr300"], 5)
        self.assertNotIn("start", second.feed(reply)[0])

    def test_modbus_requests_are_read_from_outgoing_frames(self):
        requests = protocol.ModbusRequests()
        rtu = protocol.build_modbus_frame(1, 3, 100, count=6)
        for sent, parser_type in ((rtu, "line"), (rtu[:-1] + b"\0", "modbus"),
                                  (protocol.build_modbus_frame(1, 6, 100, 5), "modbus")):
            requests.note_frame(sent, parser_type)  # another parser, a bad CRC, a write
        self.assertIsNone(requests.take(1, 3))
        self.assertIsNone(requests.take(1, 6))
        requests.note_frame(rtu, "modbus")
        self.assertEqual(requests.take(1, 3), (100, 6))
        requests.note_frame(bytearray(protocol.build_modbus_tcp_frame(2, 4, 30, count=2, transaction=9)), "modbus_tcp")
        requests.note_frame(protocol.build_modbus_tcp_frame(2, 4, 40, count=2, transaction=10), "modbus")
        self.assertEqual((requests.take(2, 4, 9), requests.take(2, 4, 10)), ((30, 2), None))

    def test_modbus_tcp_names_each_reply_by_its_transaction(self):
        def reply(transaction, unit, pdu):
            pdu = bytes.fromhex(pdu)
            return (transaction.to_bytes(2, "big") + b"\0\0" + (len(pdu) + 1).to_bytes(2, "big")
                    + bytes([unit]) + pdu)
        requests = protocol.ModbusRequests()
        parser = protocol.create_parser("modbus_tcp", {}, requests)
        requests.note(1, 3, 100, 1, transaction=7)
        requests.note(1, 3, 200, 1, transaction=8)
        # Replies may come back in any order; each finds its own request.
        late, early = parser.feed(reply(8, 1, "0302000b") + reply(7, 1, "0302000a"))
        self.assertEqual((late["start"], late["hr200"], early["start"], early["hr100"]), (200, 11, 100, 10))
        for wrong in (reply(7, 2, "0302000a"), reply(7, 1, "0402000a"), reply(9, 1, "0302000a")):
            with self.subTest(wrong=wrong.hex()):
                self.assertNotIn("start", parser.feed(wrong)[0])
        for transaction in range(300):  # old transactions are forgotten, recent ones kept
            requests.note(1, 3, transaction, 1, transaction=1000 + transaction)
        self.assertEqual(parser.feed(reply(1299, 1, "03020001"))[0]["hr299"], 1)
        self.assertNotIn("start", parser.feed(reply(1000, 1, "03020001"))[0])

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

    def test_modbus_bad_crc_and_noise_do_not_hide_next_valid_response(self):
        valid = frame(bytes.fromhex("0103020007"))
        parser = protocol.ModbusRTUParser()
        self.assertEqual(parser.feed(bytes.fromhex("0183020000")), [])
        self.assertEqual(parser.feed(b"\xff" * 10000 + b"\x01\x03\xf0" + valid),
                         [{"slave": 1, "fc": 3, "reg0": 7}])
        self.assertLessEqual(len(parser._buf), 255)


def hexes(text):
    return bytes.fromhex(text.replace(" ", ""))


# The vectors of the frame-parsing spec FluentHMI Studio shares; both must cut and read them alike.
# A: AA 55 | LEN | CMD | DATA... | SUM, the length counting the data only.
CONFIG_A = {"header": "AA55", "footer": "", "lengthOffset": 2, "lengthSize": 1,
            "lengthCovers": "数据", "checksum": "和校验", "checksumStart": 0,
            "fields": [["cmd", 1, 1, "uint8"], ["temp", 2, 2, "int16", "小端(LE)"], ["hum", 4, 1, "uint8"]]}
FRAME_A1 = hexes("AA 55 04 01 F6 FF 3C 35")  # sum AA+55+04+01+F6+FF+3C = 0x335
MESSAGE_A1 = {"cmd": 1, "temp": -10, "hum": 60}
FRAME_A2 = hexes("AA 55 04 02 10 00 28 3D")
MESSAGE_A2 = {"cmd": 2, "temp": 16, "hum": 40}
# B: fixed length, no header or footer, XOR of the first three bytes.
CONFIG_B = {"header": "", "footer": "", "fixedLength": 4, "checksum": "异或",
            "fields": [["v", 0, 2, "uint16"], ["f", 2, 1, "uint8"]]}
# C: a header, then whatever arrives before the line goes quiet.
CONFIG_C = {"header": "7E", "footer": "", "idleTimeout": 20, "fields": [["a", 0, 1, "uint8"]]}
# D: header, footer and a little-endian CRC16-Modbus that leaves out the header.
CONFIG_D = {"header": "AA55", "footer": "0D0A", "checksum": "CRC16-Modbus",
            "checksumEndian": "小端(LE)", "checksumStart": 2, "fields": [["t", 0, 4, "float32"]]}
FRAME_D = hexes("AA 55 41 CA 66 66 9F AC 0D 0A")  # CRC16-Modbus(41 CA 66 66) = 0xAC9F
# E: a project from before, with only a header, a footer and fields.
CONFIG_E = {"header": "AA55", "footer": "55AA", "fields": [["temp", 0, 2, "int16"]]}


def units(parser, stream, chunk=None):
    """The raw units ``frames`` cuts from ``stream`` fed in pieces of ``chunk`` bytes (all at once by default)."""
    chunk = chunk or len(stream) or 1
    return [unit for at in range(0, len(stream), chunk) for unit in parser.frames(stream[at:at + chunk])]


class HexFrameTests(unittest.TestCase):
    def parser(self, config):
        return protocol.create_parser("hex", config)

    def test_length_field_frames_whole_and_reads_fields_after_the_header(self):
        parser = self.parser(CONFIG_A)
        self.assertEqual(parser.frames(FRAME_A1), [FRAME_A1])
        self.assertEqual(parser.parse(FRAME_A1), [MESSAGE_A1])
        stream = FRAME_A1 + FRAME_A2
        for chunk in (1, 3, len(stream)):  # byte by byte, in pieces, both frames in one read
            with self.subTest(chunk=chunk):
                self.assertEqual(units(self.parser(CONFIG_A), stream, chunk), [FRAME_A1, FRAME_A2])
        self.assertEqual(units(self.parser(CONFIG_A), hexes("12 34") + FRAME_A1, 1), [FRAME_A1],
                         "noise before the header is skipped")
        # The data may hold the header: the length field, not a search, ends the frame.
        inner = hexes("AA 55 04 AA 55 00 07")
        inner += bytes([sum(inner) & 0xFF])
        self.assertEqual(units(self.parser(CONFIG_A), inner + FRAME_A1, 1), [inner, FRAME_A1])
        self.assertEqual(self.parser(CONFIG_A).feed(inner), [{"cmd": 0xAA, "temp": 0x55, "hum": 7}])

    def test_a_bad_checksum_drops_the_frame_and_the_next_one_parses(self):
        bad = FRAME_A1[:-1] + b"\x30"
        for chunk in (1, len(bad) * 2):
            with self.subTest(chunk=chunk):
                parser = self.parser(CONFIG_A)
                self.assertEqual(units(parser, bad + FRAME_A2, chunk), [FRAME_A2])
                self.assertEqual(parser.parse(FRAME_A2), [MESSAGE_A2])

    def test_three_meanings_of_the_length_field_read_the_same_message(self):
        for covers, length in (("数据", 4), ("长度字段之后", 5), ("整帧", 8)):
            with self.subTest(covers=covers):
                body = hexes("AA 55") + bytes([length]) + hexes("01 F6 FF 3C")
                frame = body + bytes([sum(body) & 0xFF])
                parser = self.parser({**CONFIG_A, "lengthCovers": covers})
                self.assertEqual(units(parser, frame + FRAME_A1[:3], 1), [frame])
                self.assertEqual(parser.parse(frame), [MESSAGE_A1])

    def test_an_impossible_length_resyncs_to_the_next_header(self):
        whole = {**CONFIG_A, "lengthCovers": "整帧"}
        good = hexes("AA 55 08 01 F6 FF 3C 39")
        # 2 is shorter than the header, length field and checksum together.
        self.assertEqual(units(self.parser(whole), hexes("AA 55 02") + good, 1), [good])
        wide = {"header": "AA55", "footer": "", "lengthOffset": 2, "lengthSize": 2,
                "fields": [["v", 2, 1, "uint8"]]}
        parser = self.parser(wide)
        # FFFF bytes of data would make a frame longer than 65536 bytes.
        self.assertEqual(units(parser, hexes("AA 55 FF FF AA 55 00 01 07")), [hexes("AA 55 00 01 07")])
        self.assertEqual(parser.feed(hexes("AA 55 00 01 07")), [{"v": 7}])
        little = self.parser({**wide, "lengthEndian": "小端(LE)"})
        self.assertEqual(little.feed(hexes("AA 55 01 00 09")), [{"v": 9}])

    def test_a_counted_or_fixed_frame_must_end_in_the_footer(self):
        counted = {"header": "AA55", "footer": "0D0A", "lengthOffset": 2, "fields": [["v", 1, 1, "uint8"]]}
        good = hexes("AA 55 01 07 0D 0A")
        for config in (counted, {**counted, "lengthOffset": -1, "fixedLength": 6}):
            with self.subTest(config=config):
                parser = self.parser(config)
                self.assertEqual(units(parser, hexes("AA 55 01 05 0D 0B") + good, 1), [good])
                self.assertEqual(parser.parse(good), [{"v": 7}])

    def test_fixed_length_without_header_or_footer(self):
        parser = self.parser(CONFIG_B)
        stream = hexes("00 10 01 11 00 20 02 22")
        self.assertEqual(units(parser, stream, 1), [stream[:4], stream[4:]])
        self.assertEqual(self.parser(CONFIG_B).feed(stream), [{"v": 16, "f": 1}, {"v": 32, "f": 2}])
        # A wrong checksum costs one byte at a time until frames line up again.
        self.assertEqual(self.parser(CONFIG_B).feed(hexes("FF") + stream), [{"v": 16, "f": 1}, {"v": 32, "f": 2}])

    def test_header_and_idle_flush(self):
        parser = self.parser(CONFIG_C)
        self.assertEqual(parser.idle_timeout, 20)
        self.assertEqual(parser.frames(hexes("7E 01 02")), [])
        self.assertEqual(parser.flush(), [hexes("7E 01 02")])
        self.assertEqual(parser.parse(hexes("7E 01 02")), [{"a": 1}])
        self.assertEqual(parser.flush(), [])
        # Noise before the header goes; less than a header is no frame.
        self.assertEqual(parser.frames(hexes("33 7E 05")), [])
        self.assertEqual(parser.flush(), [hexes("7E 05")])
        two = self.parser({**CONFIG_C, "header": "7E7F"})
        self.assertEqual(two.frames(hexes("01 7E")), [])
        self.assertEqual((two.flush(), two._buf), ([], b""))
        summed = self.parser({**CONFIG_C, "checksum": "和校验"})
        summed.frames(hexes("7E"))
        self.assertEqual(summed.flush(), [], "no room for the checksum after the header")
        summed.frames(hexes("7E 7E"))
        self.assertEqual(summed.flush(), [hexes("7E 7E")])
        bare = self.parser({"header": "", "footer": "", "idleTimeout": 5, "checksum": "异或",
                            "fields": [["a", 0, 1, "uint8"]]})
        self.assertEqual(bare.frames(hexes("01 02 03")), [])
        self.assertEqual(bare.flush(), [hexes("01 02 03")])
        bare.frames(hexes("01 02 04"))
        self.assertEqual(bare.flush(), [], "a flushed frame still has to pass its checksum")

    def test_idle_flush_drops_a_frame_a_rule_should_have_ended(self):
        parser = self.parser({**CONFIG_E, "idleTimeout": 50})
        self.assertEqual(parser.frames(hexes("AA 55 00")), [])
        self.assertEqual((parser.flush(), parser._buf), ([], b""))
        self.assertEqual(parser.frames(hexes("01 55 AA")), [], "the rest of a dropped frame is noise")
        self.assertEqual(parser.feed(hexes("AA 55 00 05 55 AA")), [{"temp": 5}])

    def test_crc16_modbus_little_endian_without_the_header(self):
        self.assertEqual(protocol.modbus_crc(hexes("41 CA 66 66")), hexes("9F AC"))
        parser = self.parser(CONFIG_D)
        self.assertEqual(units(parser, hexes("00") + FRAME_D + FRAME_D, 1), [FRAME_D, FRAME_D])
        self.assertEqual(parser.parse(FRAME_D), [{"t": 25.299999237060547}])
        self.assertEqual(self.parser(CONFIG_D).feed(FRAME_D[:6] + hexes("AC 9F") + FRAME_D[8:]), [])
        self.assertEqual(self.parser({**CONFIG_D, "checksumEndian": "大端(BE)"}).feed(FRAME_D), [])

    def test_checksums_of_123456789(self):
        data = b"123456789"
        for algorithm, value in (("和校验", 0xDD), ("异或", 0x31), ("CRC8", 0xF4),
                                 ("CRC16-Modbus", 0x4B37), ("CRC16-CCITT", 0x29B1)):
            with self.subTest(algorithm=algorithm):
                self.assertEqual(protocol.hex_checksum(algorithm, data), value)
                # On the wire, after the checked bytes; 16-bit values big-endian by default.
                size = protocol.HEX_CHECKSUMS[algorithm]
                frame = data + value.to_bytes(size, "big")
                config = {"header": "", "footer": "", "fixedLength": len(frame), "checksum": algorithm,
                          "fields": [["s", 0, 9, "ASCII"]]}
                self.assertEqual(self.parser(config).feed(frame), [{"s": "123456789"}])
                self.assertEqual(self.parser(config).feed(frame[:-1] + bytes([frame[-1] ^ 1])), [])
        late = {"header": "", "footer": "", "fixedLength": 4, "checksum": "和校验", "checksumStart": 4}
        parser = self.parser(late)
        self.assertEqual(parser.frames(hexes("00 00 00 00 00 00 00 00")), [],
                         "a checksum that starts past its own byte never matches")
        self.assertLess(len(parser._buf), 4)
        # Starting at the checksum byte checks nothing: the sum of no bytes is 0.
        self.assertEqual(self.parser({**late, "checksumStart": 3}).frames(hexes("05 06 07 00")),
                         [hexes("05 06 07 00")])
        short = self.parser({"header": "AA55", "footer": "0D", "fixedLength": 3, "checksum": "异或"})
        self.assertEqual(short.frames(hexes("AA 55 0D AA 55 0D")), [],
                         "a frame must hold its header, checksum and footer")

    def test_every_field_type_in_both_byte_orders(self):
        payload = hexes("FE 0102 FFFE 00000100 FFFFFFFE 41CA6666 6666CA41"
                        "40394CCCCCCCCCCD CDCCCCCCCC4C3940 4F4B0058 DEAD FF")
        fields = [["u8", 0, 1, "uint8"], ["i8", 0, 1, "int8", "小端(LE)"],
                  ["u16", 1, 2, "uint16"], ["u16le", 1, 2, "uint16", "小端(LE)"],
                  ["i16", 3, 2, "int16", "大端(BE)"], ["i16le", 3, 2, "int16", "小端(LE)"],
                  ["u32", 5, 4, "uint32"], ["u32le", 5, 4, "uint32", "小端(LE)"],
                  ["i32", 9, 4, "int32"], ["i32le", 9, 4, "int32", "小端(LE)"],
                  ["f32", 13, 4, "float32"], ["f32le", 17, 4, "float32", "小端(LE)"],
                  ["f64", 21, 8, "float64"], ["f64le", 29, 8, "float64", "小端(LE)"],
                  ["text", 37, 4, "ASCII"], ["raw", 41, 2, "HEX"], ["odd", 43, 1, "ASCII"],
                  ["late", 43, 2, "HEX"]]
        parser = self.parser({"header": "", "footer": "", "fixedLength": len(payload), "fields": fields})
        self.assertEqual(parser.feed(payload), [{
            "u8": 254, "i8": -2, "u16": 258, "u16le": 513, "i16": -2, "i16le": -257,
            "u32": 256, "u32le": 65536, "i32": -2, "i32le": -16777217,
            "f32": 25.299999237060547, "f32le": 25.299999237060547, "f64": 25.3, "f64le": 25.3,
            "text": "OK", "raw": "dead", "odd": "�"}])  # late runs past the frame
        # Fields end before the checksum and footer.
        framed = self.parser({"header": "AA", "footer": "55", "checksum": "异或",
                              "fields": [["a", 0, 1, "uint8"], ["b", 1, 1, "uint8"]]})
        self.assertEqual(framed.feed(hexes("AA 07 AD 55")), [{"a": 7}])

    def test_an_overfull_buffer_is_cut_where_dropping_byte_by_byte_would_stop(self):
        noise = b"\x01" * 100000
        footer_only = self.parser({"header": "", "footer": "55AA", "fields": [["v", 0, 1, "uint8"]]})
        self.assertEqual(footer_only.frames(noise), [])
        self.assertEqual(footer_only._buf, noise[-65536:])
        self.assertEqual(footer_only.frames(hexes("55 AA")), [], "65538 bytes is too long for a frame")
        self.assertEqual((footer_only._buf, footer_only.frames(hexes("07 55 AA"))), (b"", [hexes("07 55 AA")]))
        parser = self.parser(CONFIG_E)
        self.assertEqual(parser.frames(hexes("AA 55") + noise + hexes("AA 55 00 07")), [])
        self.assertEqual(parser._buf, hexes("AA 55 00 07"), "the first header in the last 64 KiB")
        self.assertEqual(parser.frames(hexes("55 AA")), [hexes("AA 55 00 07 55 AA")])
        parser.frames(hexes("AA 55") + noise)
        self.assertEqual(parser._buf, b"\x01")
        # A footer that does arrive ends an overlong frame, which is dropped whole, as before.
        self.assertEqual(parser.frames(hexes("AA 55") + noise + hexes("55 AA AA 55 00 08 55 AA")),
                         [hexes("AA 55 00 08 55 AA")])

    def test_old_projects_parse_as_before(self):
        parser = self.parser(CONFIG_E)
        wire = hexes("AA 55 FF F6 55 AA AA 55 00 2A 55 AA")
        self.assertEqual(parser.frames(wire), [wire[:6], wire[6:]])
        self.assertEqual(self.parser(CONFIG_E).feed(wire), [{"temp": -10}, {"temp": 42}])
        self.assertEqual(protocol.create_parser("hex", {}).feed(hexes("AA 55 01 02 55 AA")), [],
                         "no fields, no message")
        self.assertEqual(protocol.create_parser("hex", {"header": "aa 55", "fields": [["x", 0, 3, "HEX"]]})
                         .feed(hexes("AA 55 01 02 03 55 AA")), [{"x": "010203"}])
        self.assertEqual(self.parser(CONFIG_E).idle_timeout, 0)
        self.assertEqual(self.parser(CONFIG_E).flush(), [])

    def test_feed_is_frames_then_parse(self):
        stream = hexes("12") + FRAME_A1 + FRAME_A1[:-1] + hexes("00") + FRAME_A2 + FRAME_A1[:4]
        for split in range(len(stream) + 1):
            with self.subTest(split=split):
                fed, framed = self.parser(CONFIG_A), self.parser(CONFIG_A)
                messages = fed.feed(stream[:split]) + fed.feed(stream[split:])
                parsed = [m for piece in (stream[:split], stream[split:])
                          for unit in framed.frames(piece) for m in framed.parse(unit)]
                self.assertEqual(messages, parsed)
                self.assertEqual(messages, [MESSAGE_A1, MESSAGE_A2])
        for parser in (protocol.create_parser("line"), protocol.create_parser("modbus")):
            self.assertEqual(parser.frames(b"a=1\n"), [b"a=1\n"], "other modes keep the read as one unit")
            self.assertEqual(parser.flush(), [])
            self.assertEqual(parser.idle_timeout, 0)

    def test_settings_are_checked_with_the_shared_messages(self):
        cases = [
            ({"footer": ""}, "HEX 帧需要帧尾、长度字段、固定帧长或空闲超时之一来分帧"),
            ({"header": "", "footer": " "}, "HEX 帧需要帧尾、长度字段、固定帧长或空闲超时之一来分帧"),
            ({"footer": "", "lengthSize": 3}, "HEX 帧需要帧尾、长度字段、固定帧长或空闲超时之一来分帧"),
            ({"header": "AA5"}, "HEX 帧头或帧尾不是十六进制"),
            ({"footer": "0G"}, "HEX 帧头或帧尾不是十六进制"),
            ({"header": 170}, "HEX 帧头或帧尾不是十六进制"),
            ({"fixedLength": 4, "lengthOffset": 2}, "固定帧长和长度字段只能选一个"),
            ({"lengthOffset": -2}, "HEX 长度字段设置无效"),
            ({"lengthOffset": "2"}, "HEX 长度字段设置无效"),
            ({"lengthSize": 4}, "HEX 长度字段设置无效"),
            ({"lengthEndian": "LE"}, "HEX 长度字段设置无效"),
            ({"lengthCovers": "全部"}, "HEX 长度字段设置无效"),
            ({"fixedLength": -1}, "HEX 固定帧长无效"),
            ({"fixedLength": 65537}, "HEX 固定帧长无效"),
            ({"checksum": "CRC32"}, "HEX 校验设置无效"),
            ({"checksumStart": -1}, "HEX 校验设置无效"),
            ({"checksumEndian": "BE"}, "HEX 校验设置无效"),
            ({"idleTimeout": -1}, "HEX 空闲超时无效"),
            ({"idleTimeout": 60001}, "HEX 空闲超时无效"),
            ({"fields": [["a", 0, 1]]}, "无效 HEX 字段: a"),
            ({"fields": [["b", -1, 1, "uint8"]]}, "无效 HEX 字段: b"),
            ({"fields": [["c", 0, 0, "HEX"]]}, "无效 HEX 字段: c"),
            ({"fields": [["d", 0, 2, "uint8"]]}, "无效 HEX 字段: d"),
            ({"fields": [["e", 0, 8, "uint64"]]}, "无效 HEX 字段: e"),
            ({"fields": [["f", 0, 2, "uint16", "LE"]]}, "无效 HEX 字段: f"),
            ({"fields": [["g", 0, 1, "uint8", "大端(BE)", 1]]}, "无效 HEX 字段: g"),
            ({"fields": [["h", 0, 3, "float32"]]}, "无效 HEX 字段: h"),
        ]
        for config, message in cases:
            with self.subTest(config=config):
                with self.assertRaises(ValueError) as caught:
                    protocol.create_parser("hex", config)
                self.assertEqual(str(caught.exception), message)
        self.assertEqual(protocol.hex_bytes("A A5\t5"), hexes("AA 55"), "whitespace anywhere is ignored")
        for config, message in (({"fields": "a,0,1,uint8"}, "无效 HEX 字段: "),
                                ({"fields": [7]}, "无效 HEX 字段: "),
                                ({"fields": [[1, 0, 1, "uint8", "x"]]}, "无效 HEX 字段: ")):
            with self.subTest(config=config):
                with self.assertRaises(ValueError) as caught:
                    protocol.create_parser("hex", config)
                self.assertEqual(str(caught.exception), message)
        for config in ({"header": ""}, {"header": "", "footer": "", "idleTimeout": 1},
                       {"header": "\t", "footer": "", "lengthOffset": 0}, {"lengthOffset": 2.0},
                       {"footer": "", "lengthOffset": 0}, {"footer": "", "fixedLength": 65536},
                       {"lengthOffset": 65535, "lengthSize": 2, "idleTimeout": 60000},
                       {"fields": [["s", 0, 1, "ASCII", "小端(LE)"], ["x", 3, 7, "HEX"]]}):
            with self.subTest(valid=config):
                protocol.create_parser("hex", config)


# Phase two of the shared frame-parsing spec: text records, JSON values, encodings and NMEA.
GPGGA = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
GPGGA_MESSAGE = {"ch0": "GPGGA", "ch1": 123519, "ch2": 4807.038, "ch3": "N", "ch4": 1131.0, "ch5": "E",
                 "ch6": 1, "ch7": 8, "ch8": 0.9, "ch9": 545.4, "ch10": "M", "ch11": 46.9, "ch12": "M",
                 "ch13": "", "ch14": ""}
AIVDM = b"!AIVDM,1,1,,B,177KQJ5000G?tO`K>RA1wUbN0TKH,0*5C"
AIVDM_MESSAGE = {"ch0": "AIVDM", "ch1": 1, "ch2": 1, "ch3": "", "ch4": "B",
                 "ch5": "177KQJ5000G?tO`K>RA1wUbN0TKH", "ch6": 0}


class LineFormatTests(unittest.TestCase):
    def parser(self, **config):
        return protocol.create_parser("line", config)

    def assert_reads(self, config, stream, expected):
        """``stream`` gives ``expected`` however it is split: in two anywhere, or a byte at a time."""
        for split in range(len(stream) + 1):
            with self.subTest(split=split):
                parser = self.parser(**config)
                self.assertEqual(parser.feed(stream[:split]) + parser.feed(stream[split:]), expected)
        parser = self.parser(**config)
        self.assertEqual([m for byte in stream for m in parser.feed(bytes([byte]))], expected)

    def test_any_terminator_ends_a_record_and_whitespace_around_it_is_stripped(self):
        self.assert_reads({"terminator": ";"}, b"a=1;b=2;\r\n c=3;", [{"a": 1}, {"b": 2}, {"c": 3}])
        # With CR as the terminator, the LF of a CR LF line is the next record's leading whitespace.
        self.assert_reads({"terminator": "\r"}, b"a=1\r\na=2\r\n", [{"a": 1}, {"a": 2}])
        self.assert_reads({}, b"a=1\r\n\r\n\n  a=2\n", [{"a": 1}, {"a": 2}])
        self.assert_reads({"terminator": "END"}, b"t=1ENDt=2ENENDx", [{"t": 1}, {"t": "2EN"}])
        parser = self.parser(terminator="\r\n")
        self.assertEqual(parser.feed(b"1,2\r"), [], "half a terminator is not one")
        self.assertEqual(parser.feed(b"\n"), [{"ch0": 1, "ch1": 2}])

    def test_the_key_value_separator_is_the_only_one_recognised(self):
        self.assert_reads({"kvSeparator": ":"}, b"temp:25.3,hum:60\ntemp=25\ntime:12:30\n",
                          [{"temp": 25.3, "hum": 60}, {"ch0": "temp=25"}, {"time": "12:30"}])
        self.assertEqual(self.parser().feed(b"temp:25\ntemp=25\n"), [{"ch0": "temp:25"}, {"temp": 25}])

    def test_records_decode_in_the_link_encoding_and_bad_bytes_become_replacement_characters(self):
        gbk = b"\xce\xc2\xb6\xc8=25\n"  # 温度=25 in GBK
        self.assertEqual(self.parser(encoding="gbk").feed(gbk), [{"温度": 25}])
        self.assertEqual(self.parser(encoding="GBK").feed(gbk), [{"温度": 25}], "the name ignores case")
        self.assertEqual(self.parser().feed(gbk), [{"�¶�": 25}], "not UTF-8: CE C2 B6 C8")
        self.assertEqual(self.parser(encoding="ascii").feed(gbk), [{"�" * 4: 25}],
                         "ASCII replaces every byte above 7F")
        self.assertEqual(self.parser(encoding="ascii").feed("é=1\n".encode()), [{"��": 1}])
        # A terminator is spelt in the encoding too: 。 is A1 A3 in GBK.
        self.assert_reads({"encoding": "gbk", "terminator": "。"}, "温度=25。湿度=60。".encode("gbk"),
                          [{"温度": 25}, {"湿度": 60}])
        self.assert_reads({}, "温度=25\n".encode(), [{"温度": 25}])

    def test_nmea_sentences_are_kept_only_when_their_checksum_matches(self):
        self.assert_reads({}, GPGGA + b"\r\n" + GPGGA[:-1] + b"8\r\n" + AIVDM + b"\r\n",
                          [GPGGA_MESSAGE, AIVDM_MESSAGE])
        self.assertEqual(self.parser().feed(AIVDM[:-2] + b"5c\n"), [AIVDM_MESSAGE], "either case")
        self.assertEqual(self.parser().feed(b"$GPTXT,hello\n"), [{"ch0": "$GPTXT", "ch1": "hello"}],
                         "no *HH, no checksum: the $ stays")
        self.assertEqual(self.parser().feed(b"$GPTXT,a*4\n"), [{"ch0": "$GPTXT", "ch1": "a*4"}])
        self.assertEqual(self.parser(terminator=";").feed(b" $A,1*5C ;"), [{"ch0": "A", "ch1": 1}])
        self.assertEqual(self.parser().feed(b"$*00\n"), [{"ch0": ""}], "an empty sentence is still a record")
        self.assertEqual(self.parser(kvSeparator=":").feed(b"$PX,t:5*00\n"), [], "the XOR is 5F")
        self.assertEqual(self.parser(kvSeparator=":").feed(b"$PX,t:5*5F\n"), [{"t": 5}],
                         "a checked sentence is an ordinary record: key-value when a field has the separator")

    def test_json_values_end_where_their_brackets_close(self):
        pretty = b'{\n  "data": {"sensors": [{"temp": 25.3}, {"temp": 22.1}]},\n  "note": "a}\\"b"\n}\n'
        stream = (pretty + b'{"a":1}{"a":2}\n[1, 2, 3]\n[{"temp": 7}, [8]]{"a":1}xyz\n'
                  b'{"bad":}\nok=1\n{}\n[]\n{"a": NaN}\n  {"last": true}')
        self.assert_reads({}, stream, [
            {"data": {"sensors": [{"temp": 25.3}, {"temp": 22.1}]}, "note": 'a}"b'},
            {"a": 1}, {"a": 2}, {"0": 1, "1": 2, "2": 3}, {"0": {"temp": 7}, "1": [8]},
            {"a": 1}, {"ch0": "xyz"}, {"ok": 1}, {"last": True}])
        # The terminator right after a value is part of it; the next record starts after it.
        self.assert_reads({"terminator": ";"}, b'{"a":1};b=2;[3];', [{"a": 1}, {"b": 2}, {"0": 3}])
        self.assertEqual(self.parser().feed(b'{"a": [1, {"b": "]"'), [], "waits for the brackets")
        # Any closing bracket closes any opening one; a mismatched value then fails to parse.
        self.assert_reads({}, b'{"a":1]\nok=1\n', [{"ok": 1}])
        self.assert_reads({"encoding": "gbk"}, '{"名称":"温度"}\n'.encode("gbk"), [{"名称": "温度"}])

    def test_json_arrays_bind_by_index(self):
        message = self.parser().feed(b'[{"temp": 25.3}, 60]\n')[0]
        by_path = BindingEntry("w", "text", parse_mode="JSON路径", json_path="0.temp")
        by_key = BindingEntry("w", "text", parse_mode="键值匹配", key="1")
        self.assertEqual((by_path.extract_from_parsed(message), by_key.extract_from_parsed(message)), (25.3, 60))

    def test_more_than_the_buffer_waiting_is_dropped_up_to_the_next_terminator(self):
        # Overflow is checked once nothing more completes: a whole record in the buffer is still
        # read, while more than max_buffer bytes still waiting for their end are dropped.
        def parser():
            return protocol.LineParser(max_buffer=16)
        long_record = b"a=" + b"1" * 15 + b"\nb=2\n"
        self.assertEqual(parser().feed(long_record), [{"a": int("1" * 15)}, {"b": 2}])
        bytewise = parser()
        self.assertEqual([m for byte in long_record for m in bytewise.feed(bytes([byte]))], [{"b": 2}])
        split = parser()
        self.assertEqual(split.feed(long_record[:17]) + split.feed(long_record[17:]), [{"b": 2}],
                         "17 bytes waiting for their terminator")
        self.assertEqual(split.feed(b"a=" + b"1" * 14) + split.feed(b"\n"), [{"a": int("1" * 14)}], "16 fit")
        # An unclosed value is dropped up to the first terminator, which may be inside it already.
        unclosed = b"{" + b"x" * 20 + b"\nc=3\n"
        self.assertEqual(parser().feed(unclosed), [{"c": 3}])
        bytewise = parser()
        self.assertEqual([m for byte in unclosed for m in bytewise.feed(bytes([byte]))], [{"c": 3}])
        inner = b'{"k": [1,\n' + b"2" * 20 + b"\nc=3\n"
        self.assertEqual(parser().feed(inner), [{"ch0": int("2" * 20)}, {"c": 3}],
                         "dropped up to the newline inside the value, the record after it is whole")
        bytewise = parser()
        self.assertEqual([m for byte in inner for m in bytewise.feed(bytes([byte]))], [{"c": 3}])
        # While dropping, the last bytes are kept, so a terminator split across reads still ends it.
        crlf = protocol.LineParser(max_buffer=16, terminator="\r\n")
        self.assertEqual(crlf.feed(b"x" * 20 + b"\r") + crlf.feed(b"\nd=4\r\n"), [{"d": 4}])
        bounded = parser()
        bounded.feed(b"{" + b"x" * 10000)
        self.assertLessEqual(len(bounded._buf), 16)
        self.assertEqual(bounded.feed(b'\n{"a":1}\n'), [{"a": 1}])

    def test_line_settings_are_checked_with_the_shared_messages(self):
        for config, message in (
            ({"terminator": ""}, "行结束符不能为空"),
            ({"terminator": None}, "行结束符不能为空"),
            ({"terminator": 10}, "行结束符不能为空"),
            ({"kvSeparator": ""}, "键值分隔符只能是 = 或 :"),
            ({"kvSeparator": "=="}, "键值分隔符只能是 = 或 :"),
            ({"kvSeparator": ";"}, "键值分隔符只能是 = 或 :"),
            ({"kvSeparator": ["="]}, "键值分隔符只能是 = 或 :"),
            ({"encoding": "utf8"}, "编码只能是 utf-8、gbk 或 ascii"),
            ({"encoding": "latin-1"}, "编码只能是 utf-8、gbk 或 ascii"),
            ({"encoding": 8}, "编码只能是 utf-8、gbk 或 ascii"),
            ({"separator": ""}, "行分隔符不能为空"),
            ({"separator": 1}, "行分隔符不能为空"),
            # The checks run in FluentHMI Studio's order: separator, terminator, kvSeparator, encoding.
            ({"terminator": "", "kvSeparator": "-", "encoding": "x", "separator": ""}, "行分隔符不能为空"),
            ({"terminator": "", "kvSeparator": "-", "encoding": "x"}, "行结束符不能为空"),
            ({"kvSeparator": "-", "encoding": "x"}, "键值分隔符只能是 = 或 :"),
        ):
            with self.subTest(config=config):
                with self.assertRaises(ValueError) as caught:
                    protocol.create_parser("line", config)
                self.assertEqual(str(caught.exception), message)
        for config in ({}, {"terminator": "\r\n", "kvSeparator": ":", "encoding": "UTF-8", "separator": ";"},
                       {"terminator": " ", "encoding": "ascii"}, {"encoding": "Gbk"}):
            with self.subTest(valid=config):
                protocol.create_parser("line", config)


def ascii_frame(body_hex, lrc=None):
    """A Modbus ASCII frame of these bytes: ':', uppercase hex pairs, the LRC, CR LF."""
    body = hexes(body_hex)
    lrc = protocol.modbus_lrc(body) if lrc is None else lrc
    return b":" + (body + bytes([lrc])).hex().upper().encode() + b"\r\n"


def tcp_adu(transaction, body_hex):
    body = hexes(body_hex)
    return transaction.to_bytes(2, "big") + b"\0\0" + len(body).to_bytes(2, "big") + body


# Responses the parsers read alike over RTU, TCP and ASCII: slave and PDU, and the message.
NEW_RESPONSES = [
    ("01 07 6D", {"slave": 1, "fc": 7, "status": 0x6D}),
    ("01 08 0000 A537", {"slave": 1, "fc": 8, "subfunction": 0, "data": 0xA537}),
    ("11 11 05 0A FF 01 02 03", {"slave": 17, "fc": 0x11, "id": 10, "run": 1, "extra": "010203"}),
    ("11 11 02 0B 00", {"slave": 17, "fc": 0x11, "id": 11, "run": 0, "extra": ""}),
    ("11 11 02 0B 01", {"slave": 17, "fc": 0x11, "id": 11, "run": 0, "extra": ""}),
    ("11 11 01 0C", {"slave": 17, "fc": 0x11, "id": 12, "run": 0, "extra": ""}),
    ("01 16 0004 00F2 0025", {"slave": 1, "fc": 0x16, "address": 4, "andMask": 0xF2, "orMask": 0x25}),
    ("01 17 04 0001 000A", {"slave": 1, "fc": 0x17, "reg0": 1, "reg1": 10}),
    ("01 87 01", {"slave": 1, "fc": 0x87, "error": 1}),
    ("01 88 03", {"slave": 1, "fc": 0x88, "error": 3}),
    ("11 91 01", {"slave": 17, "fc": 0x91, "error": 1}),
    ("01 96 02", {"slave": 1, "fc": 0x96, "error": 2}),
    ("01 97 02", {"slave": 1, "fc": 0x97, "error": 2}),
]
WIRES = {"modbus": lambda body: frame(hexes(body)), "modbus_tcp": lambda body: tcp_adu(9, body),
         "modbus_ascii": ascii_frame}


class ModbusFrameTests(unittest.TestCase):
    def test_new_function_codes_read_alike_over_rtu_tcp_and_ascii(self):
        for parser_type, wire in WIRES.items():
            stream = b"".join(wire(body) for body, _ in NEW_RESPONSES)
            expected = [message for _, message in NEW_RESPONSES]
            with self.subTest(parser=parser_type):
                parser = protocol.create_parser(parser_type)
                self.assertEqual(parser.feed(stream), expected)
                bytewise = protocol.create_parser(parser_type)
                self.assertEqual([m for byte in stream for m in bytewise.feed(bytes([byte]))], expected)
            for body, message in NEW_RESPONSES:
                with self.subTest(parser=parser_type, body=body):
                    self.assertEqual(protocol.create_parser(parser_type).feed(wire(body)), [message])

    def test_new_function_codes_check_their_lengths(self):
        for body in ("01 17 03 000100", "11 11 00", "01 17 00", "01 99 02", "00 07 6D", "F8 07 6D"):
            for parser_type, wire in WIRES.items():
                if parser_type == "modbus_tcp" and body[:2] in ("00", "F8"):
                    continue  # a Modbus TCP unit id may be any byte
                with self.subTest(parser=parser_type, body=body):
                    self.assertEqual(protocol.create_parser(parser_type).feed(wire(body)), [])
        for adu in ("0001 0000 0004 01 07 6D 00", "0001 0000 0005 01 08 0000 00",
                    "0001 0000 0007 01 16 0004 00F2 00", "0001 0000 0007 11 11 05 0A FF 01"):
            with self.subTest(adu=adu):
                self.assertEqual(protocol.ModbusTCPParser().feed(hexes(adu)), [],
                                 "the MBAP length must match the function code")

    def test_read_write_multiple_registers_names_the_registers_it_read(self):
        # FC 0x17: read 2 from 10, write 2 (1, 2) from 20; the reply holds the registers read.
        request = "01 17 000A 0002 0014 0002 04 0001 0002"
        reply = "01 17 04 0007 0008"
        named = {"slave": 1, "fc": 0x17, "reg0": 7, "reg1": 8, "start": 10, "hr10": 7, "hr11": 8}
        for parser_type, wire in WIRES.items():
            with self.subTest(parser=parser_type):
                requests = protocol.ModbusRequests()
                parser = protocol.create_parser(parser_type, {}, requests)
                sent = wire(request)
                if parser_type == "modbus":
                    self.assertEqual(len(sent), 13 + 2 * 2)
                requests.note_frame(sent, parser_type)
                self.assertEqual(parser.feed(wire(reply)), [named])
                if parser_type != "modbus_tcp":
                    self.assertNotIn("start", parser.feed(wire(reply))[0], "one reply per request")
                requests.note_frame(sent, parser_type)
                self.assertEqual(parser.feed(wire("01 97 04")), [{"slave": 1, "fc": 0x97, "error": 4, "start": 10}])
        # The length the write count gives is the check, not the byte count after it.
        requests = protocol.ModbusRequests()
        requests.note_frame(frame(hexes("01 17 000A 0002 0014 0002 05 0001 0002")), "modbus")
        self.assertEqual(requests.take(1, 0x17), (10, 2))
        requests = protocol.ModbusRequests()
        for sent, parser_type in ((frame(hexes(request))[:-1] + b"\0", "modbus"),  # a bad CRC
                                  (frame(hexes("01 17 000A 0002 0014 0002 03 0001 00")), "modbus"),
                                  (ascii_frame(request), "modbus"), (frame(hexes(request)), "modbus_ascii"),
                                  (tcp_adu(3, "01 17 000A 0002 0014 0002 04 0001"), "modbus_tcp")):
            requests.note_frame(sent, parser_type)
        self.assertIsNone(requests.take(1, 0x17))

    def test_ascii_frames_are_cut_by_colon_and_crlf_and_checked_by_lrc(self):
        first, second = "01 03 02 000A", "02 03 04 0001 0002"
        self.assertEqual(ascii_frame(first), b":010302000AF0\r\n")
        stream = (b"\x00noise" + ascii_frame(first) + ascii_frame(second).lower()
                  + ascii_frame(first, lrc=0xF1)  # a wrong LRC: dropped
                  + b":0103" + ascii_frame(second)  # a frame cut short, then a whole one
                  + b":01030\r\n" + b":0103ZZ\r\n" + ascii_frame("01 03 03 000102")  # odd, not hex, odd count
                  + ascii_frame(first))
        messages = [{"slave": 1, "fc": 3, "reg0": 10}, {"slave": 2, "fc": 3, "reg0": 1, "reg1": 2}]
        expected = [messages[0], messages[1], messages[1], messages[0]]
        for split in range(len(stream) + 1):
            with self.subTest(split=split):
                parser = protocol.ModbusASCIIParser()
                self.assertEqual(parser.feed(stream[:split]) + parser.feed(stream[split:]), expected)
        parser = protocol.create_parser("modbus_ascii", {"fields": ["temperature"]})
        self.assertEqual([m for byte in stream for m in parser.feed(bytes([byte]))],
                         [{"slave": 1, "fc": 3, "temperature": 10}, {"slave": 2, "fc": 3, "temperature": 1, "reg1": 2},
                          {"slave": 2, "fc": 3, "temperature": 1, "reg1": 2}, {"slave": 1, "fc": 3, "temperature": 10}])
        self.assertEqual(parser.feed(frame(hexes(first))), [], "RTU bytes are not ASCII frames")
        self.assertEqual(parser.feed(protocol.build_modbus_ascii_frame(1, 3, 0, count=1)), [],
                         "requests are not responses")
        parser.feed(b":" + b"0" * 10000)
        self.assertLessEqual(len(parser._buf), protocol.ModbusASCIIParser.MAX_FRAME)
        self.assertEqual(parser.feed(b"\r\n" + ascii_frame(first)), [{"slave": 1, "fc": 3, "temperature": 10}])

    def test_ascii_requests_are_uppercase_hex_with_an_lrc_and_are_noted(self):
        self.assertEqual(protocol.build_modbus_ascii_frame(1, 3, 0, count=1), b":010300000001FB\r\n")
        self.assertEqual(protocol.build_modbus_ascii_frame(0x11, 6, 0x1A, 0xBEEF), b":1106001ABEEF22\r\n")
        self.assertEqual(protocol.build_modbus_ascii_frame(1, 16, 100, registers=(0x41C8, 0)),
                         b":0110006400020441C800007C\r\n")
        requests = protocol.ModbusRequests()
        parser = protocol.create_parser("modbus_ascii", {}, requests)
        read = protocol.build_modbus_ascii_frame(1, 3, 100, count=2)
        for sent, parser_type in ((read, "modbus"), (read, "line"), (read[:-4] + b"00\r\n", "modbus_ascii"),
                                  (read.lower(), "modbus_tcp")):
            requests.note_frame(sent, parser_type)  # another parser or a wrong LRC: not a request
        self.assertIsNone(requests.take(1, 3))
        requests.note_frame(bytearray(read.lower()), "modbus_ascii")
        reply = ascii_frame("01 03 04 0019 0001")
        self.assertEqual(parser.feed(reply), [{"slave": 1, "fc": 3, "reg0": 25, "reg1": 1,
                                               "start": 100, "hr100": 25, "hr101": 1}])
        self.assertNotIn("start", parser.feed(reply)[0], "an ASCII master waits for each reply, as RTU")
        requests.note_frame(read, "modbus_ascii")
        second = protocol.create_parser("modbus_ascii", {}, requests)
        self.assertEqual((parser.feed(reply)[0]["hr101"], second.feed(reply)[0]["hr101"]), (1, 1),
                         "each parser answers a read once")


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

    def test_reader_publishes_each_hex_frame_and_flushes_when_idle(self):
        class Port:
            """Hands out its chunks one read at a time, then stays quiet."""
            def __init__(self, chunks):
                self.chunks = list(chunks)
            @property
            def in_waiting(self):
                if time.monotonic() > deadline:
                    reader._running = False  # never hang the suite
                return len(self.chunks[0]) if self.chunks else 0
            def read(self, size):
                return self.chunks.pop(0)

        for namespace in self.runtimes():
            for config, chunks, frames, messages in (
                (CONFIG_A, [hexes("12") + FRAME_A1[:3], FRAME_A1[3:] + FRAME_A2],
                 [FRAME_A1, FRAME_A2], [MESSAGE_A1, MESSAGE_A2]),
                (CONFIG_C, [hexes("7E 01"), hexes("02")], [hexes("7E 01 02")], [{"a": 1}]),
                ({**CONFIG_A, "idleTimeout": 10}, [FRAME_A1 + FRAME_A2[:4]], [FRAME_A1], [MESSAGE_A1]),
            ):
                with self.subTest(config=config):
                    reader = namespace["SerialReaderThread"](
                        Port(chunks), namespace["create_parser"]("hex", config))
                    raw, parsed, events = [], [], []
                    def on_raw(unit):
                        raw.append(unit)
                        events.append("raw")
                    def on_parsed(message):
                        parsed.append(message)
                        events.append("data")
                    reader.rawReceived.connect(on_raw, Qt.DirectConnection)
                    reader.parsedReceived.connect(on_parsed, Qt.DirectConnection)
                    started = time.monotonic()
                    deadline = started + (0.2 if config.get("idleTimeout") else 0.05)
                    reader.run()
                    self.assertEqual(raw, frames)
                    self.assertEqual(parsed, messages)
                    self.assertEqual(events[:2], ["raw", "data"], "each frame before its messages")
                    if config is CONFIG_C:
                        self.assertGreaterEqual(time.monotonic() - started, 0.02, "flushed after the quiet")

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

    def test_exports_read_text_and_modbus_ascii_alike(self):
        line = {"terminator": "。", "kvSeparator": ":", "encoding": "gbk"}
        stream = "温度:25。".encode("gbk") + GPGGA + "\r\n。[1,2]".encode("gbk")
        for runtime, namespace in zip(("host", "export"), self.runtimes()):
            with self.subTest(runtime=runtime):
                parser = namespace["create_parser"]("line", line)
                self.assertEqual(parser.feed(stream), [{"温度": 25}, GPGGA_MESSAGE, {"0": 1, "1": 2}])
                for body, message in NEW_RESPONSES:
                    self.assertEqual(namespace["create_parser"]("modbus_ascii").feed(ascii_frame(body)), [message])

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
        stream = hexes("12 34") + FRAME_A1 + FRAME_A2
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
        parser = protocol.create_parser("hex", CONFIG_A)
        frames = units(parser, stream, 3)
        for unit in frames:
            handler.rawReceived.emit(unit)
        for name, offset, dtype, order, values in bindings:
            with self.subTest(binding=name):
                host = BindingEntry(name, "text", parse_mode="HEX字节提取", byte_offset=offset,
                                    data_type=dtype, byte_order=order)
                self.assertEqual([v for unit in frames for v in host.extract_all_from_raw(unit)], values)
                self.assertEqual([call.args[0] for call in ui.widgets[name].setText.call_args_list],
                                 [str(v) for v in values])
        # A header and footer on the binding still find the payload inside each frame.
        framed = BindingEntry("cmd", "text", parse_mode="HEX字节提取", byte_offset=1,
                              data_type="uint8", frame_header="AA 55")
        self.assertEqual([v for unit in frames for v in framed.extract_all_from_raw(unit)], [1, 2])

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
