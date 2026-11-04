"""The Modbus slave (RTU and TCP) of a link card in the slave role, shared by the designer preview and exports.

Pure Python, no Qt: the data table (SlaveStore), how a request is answered (ModbusSlave.request), how requests
are cut out of a byte stream (RtuRequestFramer, TcpRequestFramer) and the log lines. slave_runtime.py puts it on
a link. tests/data/modbus_slave_vectors.json holds the cases both repositories check.

A data table has four areas, coils (co), discrete inputs (di), holding registers (hr) and input registers (ir),
each a start address and a count. Registers hold 0–65535, coils and discrete inputs 0 or 1. Whatever writes to
the table (an external master, a control, a command, the register table) gets back a slave message: the
written addresses and their neighbours in the area, keyed like a Modbus reply's addresses (hr100), with
``slave`` and the area's read function code as ``fc``, so the bindings read it as if the link had received it.
"""
import re

from .protocol_parser import BaseParser, modbus_crc
from .i18n import tr, N_

# The link parsers a slave answers with: RTU frames (modbus) or MBAP frames (modbus_tcp).
SLAVE_PARSERS = ("modbus", "modbus_tcp")
# A link card's modbusRole: it polls slaves as a master, or answers a master as a slave.
MASTER_ROLE = "主站"  # i18n: value
SLAVE_ROLE = "从站"  # i18n: value
TABLES = ("co", "di", "hr", "ir")
READ_FUNCTIONS = {"co": 1, "di": 2, "hr": 3, "ir": 4}
# The tables by the area names bindings use, as binding_values.MODBUS_AREAS.
AREA_TABLES = {"保持寄存器": "hr", "输入寄存器": "ir", "线圈": "co", "离散输入": "di"}  # i18n: value
DEFAULT_AREA = (0, 100)  # start, count
MAX_COUNT = 10000

# Translated where a log line shows them.
EXCEPTION_NAMES = {1: N_("非法功能码"), 2: N_("非法数据地址"), 3: N_("非法数据值")}
FUNCTION_NAMES = {1: N_("读线圈"), 2: N_("读离散输入"), 3: N_("读保持寄存器"), 4: N_("读输入寄存器"),
                  5: N_("写单线圈"), 6: N_("写单寄存器"), 15: N_("写多个线圈"), 16: N_("写多个寄存器")}

_INIT_LINE = re.compile(r"\s*(co|di|hr|ir)([0-9]+)\s*=\s*(-?[0-9]+)\s*", re.I | re.A)


def hex_text(data):
    """Bytes as the log shows them: upper-case pairs, one space apart."""
    return " ".join(f"{byte:02X}" for byte in data)


def slave_area(start, count):
    """An area's (start, count) within the address space: the start 0–65535, the count 0–10000 and no
    further than address 65535."""
    start = min(max(int(start), 0), 65535)
    return start, min(max(int(count), 0), MAX_COUNT, 65536 - start)


def _u16(data, index):
    return (data[index] << 8) | data[index + 1]


class SlaveStore:
    """The data table of one slave: ``areas`` maps each table to (start, count); every value starts at 0, then
    the ``init`` lines (``hr100=1234``, ``co3=1``, one per line) set theirs."""

    def __init__(self, areas=None, init=""):
        areas = areas or {}
        self.areas = {}
        self._values = {}
        for table in TABLES:
            start, count = slave_area(*areas.get(table, DEFAULT_AREA))
            self.areas[table] = (start, count)
            self._values[table] = [0] * count
        self._apply_init(init)

    def _apply_init(self, text):
        """Blank lines, comments (#), malformed lines, values out of range and addresses outside the area are
        skipped; a later line wins. A register takes −32768–65535, a negative value as its two's complement."""
        for line in str(text).split("\n"):
            match = _INIT_LINE.fullmatch(line)
            if not match:
                continue
            table, address, value = match.group(1).lower(), int(match.group(2)), int(match.group(3))
            if not self.has(table, address, 1):
                continue
            if table in ("co", "di"):
                if value not in (0, 1):
                    continue
            elif not -32768 <= value <= 65535:
                continue
            self.set(table, address, [value & 0xFFFF])

    def has(self, table, address, count):
        """Whether ``count`` (one or more) addresses from ``address`` on are all in the table's area."""
        start, size = self.areas[table]
        return count >= 1 and start <= address and address + count <= start + size

    def addresses(self, table):
        start, count = self.areas[table]
        return range(start, start + count)

    def get(self, table, address):
        return self._values[table][address - self.areas[table][0]]

    def set(self, table, address, values):
        """Write values from ``address`` on, which has() must have allowed."""
        offset = address - self.areas[table][0]
        self._values[table][offset:offset + len(values)] = list(values)

    def message(self, slave, table, addresses):
        """The slave message after a write of ``addresses``: those and their neighbours in the area."""
        start, count = self.areas[table]
        keys = sorted({near for address in addresses for near in (address - 1, address, address + 1)
                       if start <= near < start + count})
        message = {"slave": slave, "fc": READ_FUNCTIONS[table]}
        for address in keys:
            message[f"{table}{address}"] = self.get(table, address)
        return message

    def start_messages(self, slave):
        """One message per area that has addresses, with all of them: what the program sends at its start."""
        messages = []
        for table in TABLES:
            if self.areas[table][1]:
                message = {"slave": slave, "fc": READ_FUNCTIONS[table]}
                for address in self.addresses(table):
                    message[f"{table}{address}"] = self.get(table, address)
                messages.append(message)
        return messages


# The card properties that set each area's start and count: slaveCoStart, slaveCoCount, …
AREA_PROPERTIES = {"co": "slaveCo", "di": "slaveDi", "hr": "slaveHr", "ir": "slaveIr"}


def store_from_properties(properties):
    """The data table a serial, TCP or UDP card's properties describe, as the card builds it at the start."""
    def whole(name, default):
        try:
            return int(properties.get(name, default))
        except (TypeError, ValueError, OverflowError):
            return default
    areas = {table: (whole(f"{prefix}Start", DEFAULT_AREA[0]), whole(f"{prefix}Count", DEFAULT_AREA[1]))
             for table, prefix in AREA_PROPERTIES.items()}
    return SlaveStore(areas, properties.get("slaveInit", ""))


def describe(pdu):
    """What a request asks for, as its log line says."""
    fc = pdu[0]
    if fc not in FUNCTION_NAMES:
        return tr("功能码 %1", f"{fc:02X}")
    text = tr(FUNCTION_NAMES[fc])
    if len(pdu) >= 5:
        address, value = _u16(pdu, 1), _u16(pdu, 3)
        if fc == 5:
            text += " " + tr("地址 %1 值 %2", address, f"{value:04X}")
        elif fc == 6:
            text += " " + tr("地址 %1 值 %2", address, value)
        else:
            text += " " + tr("地址 %1 数量 %2", address, value)
    return text


def handle(store, pdu):
    """Carry out a request PDU on ``store``: (the reply PDU, or the exception code; the written
    (table, addresses), or None).

    Checked in this order: an unsupported function code is exception 01; a PDU of the wrong length, a quantity
    out of range, a byte count that does not match the quantity or an 05 value other than 0000 / FF00 is 03; an
    address range not wholly in the area is 02."""
    fc = pdu[0]
    if fc not in FUNCTION_NAMES:
        return 1, None
    if fc <= 6:
        if len(pdu) != 5:
            return 3, None
    elif len(pdu) < 6 or len(pdu) != 6 + pdu[5]:
        return 3, None
    address, quantity = _u16(pdu, 1), _u16(pdu, 3)
    if fc in (1, 2):
        table = "co" if fc == 1 else "di"
        if not 1 <= quantity <= 2000:
            return 3, None
        if not store.has(table, address, quantity):
            return 2, None
        packed = bytearray((quantity + 7) // 8)  # least significant bit first, the last byte padded with 0
        for index in range(quantity):
            if store.get(table, address + index):
                packed[index // 8] |= 1 << (index % 8)
        return bytes([fc, len(packed)]) + bytes(packed), None
    if fc in (3, 4):
        table = "hr" if fc == 3 else "ir"
        if not 1 <= quantity <= 125:
            return 3, None
        if not store.has(table, address, quantity):
            return 2, None
        data = b"".join(store.get(table, address + index).to_bytes(2, "big") for index in range(quantity))
        return bytes([fc, len(data)]) + data, None
    if fc == 5:
        if quantity not in (0x0000, 0xFF00):
            return 3, None
        if not store.has("co", address, 1):
            return 2, None
        store.set("co", address, [1 if quantity == 0xFF00 else 0])
        return bytes(pdu), ("co", [address])
    if fc == 6:
        if not store.has("hr", address, 1):
            return 2, None
        store.set("hr", address, [quantity])
        return bytes(pdu), ("hr", [address])
    count = pdu[5]
    if fc == 15:
        if not 1 <= quantity <= 1968 or count != (quantity + 7) // 8:
            return 3, None
        if not store.has("co", address, quantity):
            return 2, None
        data = pdu[6:]  # the bits past the quantity are ignored
        store.set("co", address, [(data[index // 8] >> (index % 8)) & 1 for index in range(quantity)])
        return bytes(pdu[:5]), ("co", list(range(address, address + quantity)))
    if not 1 <= quantity <= 123 or count != 2 * quantity:
        return 3, None
    if not store.has("hr", address, quantity):
        return 2, None
    store.set("hr", address, [_u16(pdu, 6 + 2 * index) for index in range(quantity)])
    return bytes(pdu[:5]), ("hr", list(range(address, address + quantity)))


class ModbusSlave:
    """Answers the requests to slave ``slave`` with ``store``: ``framing`` "rtu" (RTU frames, the modbus parser)
    or "tcp" (MBAP frames, modbus_tcp). With ``exceptions`` off a request that fails gets no reply."""

    def __init__(self, framing, slave, exceptions, store):
        self.framing, self.slave, self.exceptions, self.store = framing, slave, exceptions, store

    def request(self, frame):
        """A complete request: an RTU frame with a good CRC, or a Modbus TCP ADU. Returns (the reply, or
        None; the log lines as [text, level]; the slave messages its write gives).

        RTU answers its own address; 0 is a broadcast, whose writes are carried out unanswered and whose reads
        are not carried out. TCP answers its own unit identifier, 0 and 255, with the request's transaction id
        and unit. A request to another slave is ignored and logs nothing."""
        frame = bytes(frame)
        if self.framing == "rtu":
            unit, pdu = frame[0], frame[1:-2]
            if unit not in (0, self.slave):
                return None, [], []
            broadcast = unit == 0
        else:
            unit, pdu = frame[6], frame[7:]
            if unit not in (0, 255, self.slave):
                return None, [], []
            broadcast = False
        fc = pdu[0]
        line = f"{tr('收')} {hex_text(frame)} · {describe(pdu)}"
        unanswered = f" · {tr('广播')} · {tr('不应答')}"
        if broadcast and fc in (1, 2, 3, 4):
            return None, [[line + unanswered, "info"]], []
        result, written = handle(self.store, pdu)
        emits = [self.store.message(self.slave, *written)] if written else []
        if isinstance(result, int):
            problem = tr("异常 %1 %2", f"{result:02X}", tr(EXCEPTION_NAMES[result]))
            if broadcast:
                return None, [[f"{line} · {problem}{unanswered}", "warn"]], emits
            if not self.exceptions:
                return None, [[f"{line} · {problem} · {tr('不应答')}", "warn"]], emits
            reply_pdu, ok = bytes([fc | 0x80, result]), False
        else:
            if broadcast:
                return None, [[line + unanswered, "info"]], emits
            reply_pdu, ok = result, True
        if self.framing == "rtu":
            body = bytes([unit]) + reply_pdu
            reply = body + modbus_crc(body)
        else:
            reply = frame[:4] + (len(reply_pdu) + 1).to_bytes(2, "big") + bytes([unit]) + reply_pdu
        tail = tr("正常") if ok else problem
        return reply, [[line, "info"], [f"{tr('发')} {hex_text(reply)} · {tail}", "ok" if ok else "warn"]], emits


class RtuRequestFramer(BaseParser):
    """Cuts RTU requests out of a byte stream. Function codes 01–06 make 8-byte frames, 0F and 10 nine plus
    their byte count; a frame whose CRC fails loses its first byte and the search goes on. Before a request
    of another function code, whose length only the silence after it tells, a complete known request with a
    good CRC further on is looked for; at the silence (50 ms), what is left is a frame when it has 4 bytes or
    more and its CRC is good, else dropped. ``parse`` gives no messages: the link's slave answers the frames."""

    idle_timeout = 50

    def __init__(self):
        self._buf = b""

    @staticmethod
    def _known_length(buf):
        """The length of the request at buf[0] when its function code fixes it, 0 for another function code,
        None while too few bytes are in to tell."""
        if len(buf) < 2:
            return None
        fc = buf[1]
        if 1 <= fc <= 6:
            return 8
        if fc in (15, 16):
            return 9 + buf[6] if len(buf) >= 7 else None
        return 0

    def _valid_at(self, index):
        size = self._known_length(self._buf[index:])
        return (bool(size) and len(self._buf) - index >= size
                and modbus_crc(self._buf[index:index + size - 2]) == self._buf[index + size - 2:index + size])

    def frames(self, data):
        self._buf += data
        frames = []
        while len(self._buf) >= 2:
            need = self._known_length(self._buf)
            if need is None:
                break
            if need == 0:  # another function code: its length is known only at the silence after it
                later = next((index for index in range(1, len(self._buf) - 1) if self._valid_at(index)), None)
                if later is None:
                    break
                self._buf = self._buf[later:]  # noise, or a request that cannot be framed, before a whole one
                continue
            if len(self._buf) < need:
                break
            if modbus_crc(self._buf[:need - 2]) == self._buf[need - 2:need]:
                frames.append(self._buf[:need])
                self._buf = self._buf[need:]
            else:
                self._buf = self._buf[1:]
        return frames

    def flush(self):
        buf, self._buf = self._buf, b""
        if len(buf) >= 4 and modbus_crc(buf[:-2]) == buf[-2:]:
            return [buf]
        return []

    def parse(self, unit):
        return []


class TcpRequestFramer(BaseParser):
    """Cuts Modbus TCP requests out of a byte stream: the 6-byte MBAP header, then its length. A header whose
    protocol id is not 0 or whose length is not 2–254 clears what has arrived."""

    def __init__(self):
        self._buf = b""

    def frames(self, data):
        self._buf += data
        frames = []
        while len(self._buf) >= 6:
            protocol, length = _u16(self._buf, 2), _u16(self._buf, 4)
            if protocol != 0 or not 2 <= length <= 254:
                self._buf = b""
                break
            if len(self._buf) < 6 + length:
                break
            frames.append(self._buf[:6 + length])
            self._buf = self._buf[6 + length:]
        return frames

    def parse(self, unit):
        return []


def request_framer(parser_type):
    """The framer of one stream for a link that parses ``parser_type`` (one of SLAVE_PARSERS)."""
    return TcpRequestFramer() if parser_type == "modbus_tcp" else RtuRequestFramer()
