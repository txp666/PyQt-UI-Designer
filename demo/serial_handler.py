# coding: utf-8
"""Data frame parsers shared by every communication link."""
import json
import re
import struct
from typing import Optional, Dict, Any, List


class BaseParser:
    """Reading a byte stream takes two steps: ``frames`` cuts the bytes a link read into raw
    units, and ``parse`` reads the messages in one unit. The link publishes each unit before
    its messages, so raw bindings see the same units the parser read.

    By default the unit is the read itself and ``parse`` keeps its own buffer. A parser that
    frames by silence sets ``idle_timeout`` (ms); its link calls ``flush`` once nothing has
    arrived for that long and publishes the units it returns like any others.
    """

    idle_timeout = 0

    def frames(self, data: bytes) -> List[bytes]:
        return [data]

    def parse(self, unit: bytes) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        """Every complete message in ``data``, in arrival order."""
        return [message for unit in self.frames(data) for message in self.parse(unit)]

    def flush(self) -> List[bytes]:
        return []

    def reset(self):
        self._buf = b""


class RawFrameBuffer:
    """Frame raw widget bindings when both delimiters are configured.

    Without both delimiters, the read chunk remains the legacy input unit:
    no total packet length can be inferred from a single widget's byte offset.
    """
    def __init__(self, header=b"", footer=b"", max_buffer=65536):
        self.header, self.footer = header, footer
        self.max_buffer = max_buffer
        self._buf = b""

    def reset(self):
        self._buf = b""

    def feed(self, data):
        if not self.header or not self.footer:
            return [data]
        self._buf += data
        frames = []
        while self._buf:
            start = self._buf.find(self.header)
            if start < 0:
                keep = len(self.header) - 1
                self._buf = self._buf[-keep:] if keep else b""
                break
            self._buf = self._buf[start:]
            end = self._buf.find(self.footer, len(self.header))
            if end < 0:
                if len(self._buf) > self.max_buffer:
                    self._buf = self._buf[1:]
                    continue
                break
            end += len(self.footer)
            if end <= self.max_buffer:
                frames.append(self._buf[:end])
            self._buf = self._buf[end:]
        return frames


# The text encodings and key-value separators a line link may use, as .uidp files name them.
LINE_ENCODINGS = ("utf-8", "gbk", "ascii")
LINE_KV_SEPARATORS = ("=", ":")
# An NMEA sentence ends in *HH, the XOR of the characters between the leading $ (or !) and the *.
_NMEA_TAIL = re.compile(r"\*[0-9A-Fa-f]{2}\Z")
# The bytes JSON may hold outside a string, besides brackets and quotes: punctuation, numbers,
# the letters of true, false and null, and whitespace. Any other byte means the value is not JSON.
_JSON_BYTES = frozenset(b",:0123456789-+.eEtruefalsn \t\n\r")
_NOT_JSON = -1


class LineParser(BaseParser):
    """Parse text records and JSON values.

    A record ends at the terminator ("\\n" by default) and has the whitespace at both ends
    stripped, so "\\n" also ends CRLF lines. Records may be:
      - CSV:  "val1,val2,val3" (auto-indexed ch0, ch1, ...)
      - KEY=VALUE: "temp=25.3,humidity=60" (or temp:25.3 with kvSeparator ":")
      - NMEA: "$GPGGA,...*47", kept only when its checksum matches, read as CSV without $ and *HH
    A buffer that starts with { or [ holds a JSON value instead; it ends where its brackets
    close, so it needs no terminator and may span lines: '{"temp": 25.3}', [1, 2]. A byte
    JSON cannot hold outside a string (such as =) ends the candidate: it is dropped through
    its first terminator and the records after it parse as usual.
    """

    def __init__(self, separator: str = ",", max_buffer: int = 65536, terminator: str = "\n",
                 kv_separator: str = "=", encoding: str = "utf-8"):
        # The checks run in a fixed order, so FluentHMI Studio names the same problem first.
        if not isinstance(separator, str) or not separator:
            raise ValueError("行分隔符不能为空")
        if not isinstance(terminator, str) or not terminator:
            raise ValueError("行结束符不能为空")
        if not isinstance(kv_separator, str) or kv_separator not in LINE_KV_SEPARATORS:
            raise ValueError("键值分隔符只能是 = 或 :")
        encoding = encoding.lower() if isinstance(encoding, str) else None
        if encoding not in LINE_ENCODINGS:
            raise ValueError("编码只能是 utf-8、gbk 或 ascii")
        self._buf = b""
        self._sep = separator
        self._kv = kv_separator
        self._encoding = encoding
        # Records are cut in bytes; a terminator is spelt in the link's encoding (ASCII text as UTF-8).
        self.terminator = terminator.encode("gbk" if encoding == "gbk" else "utf-8", errors="replace")
        self._max_buffer = max_buffer
        self._discarding = False

    @classmethod
    def from_config(cls, config: dict) -> "LineParser":
        """A parser for a ``parserConfig``; every key is optional."""
        get = config.get
        return cls(separator=get("separator", ","), terminator=get("terminator", "\n"),
                   kv_separator=get("kvSeparator", "="), encoding=get("encoding", "utf-8"))

    def reset(self):
        self._buf = b""
        self._discarding = False

    def parse(self, data: bytes) -> List[Dict[str, Any]]:
        results = []
        term = self.terminator
        self._buf += data
        while True:
            if self._discarding:  # past a message too long to keep, up to the next terminator
                at = self._buf.find(term)
                if at < 0:
                    keep = len(term) - 1  # a terminator may arrive split
                    self._buf = self._buf[-keep:] if keep else b""
                    break
                self._buf = self._buf[at + len(term):]
                self._discarding = False
            self._buf = self._buf.lstrip()
            if not self._buf:
                break
            json_value = self._buf[:1] in (b"{", b"[")
            if json_value:
                size = self._json_size(self._buf)
                if size == _NOT_JSON:  # dropped through its first terminator, here or yet to come
                    self._discarding = True
                    continue
                end = size
            else:
                at = self._buf.find(term)
                size = None if at < 0 else at
                end = None if at < 0 else at + len(term)
            if end is None:
                # Nothing more completes: more than max_buffer bytes waiting is noise, dropped up
                # to the next terminator (which may already be here, inside an unclosed value).
                if len(self._buf) > self._max_buffer:
                    self._discarding = True
                    continue
                break
            unit, self._buf = self._buf[:size], self._buf[end:]
            if json_value:
                if self._buf.startswith(term):  # the terminator after a value, if one follows
                    self._buf = self._buf[len(term):]
                parsed = self._parse_json(unit)
            else:
                parsed = self._parse_record(unit)
            if parsed:
                results.append(parsed)
        return results

    @staticmethod
    def _json_size(buf: bytes) -> Optional[int]:
        """The length of the JSON value ``buf`` starts with, by its brackets outside strings;
        None until they close, or _NOT_JSON at a byte JSON cannot hold outside a string. Any
        closing bracket closes any opening one: a mismatched value ends all the same and then
        fails to parse."""
        depth, in_string, index = 0, False, 0
        while index < len(buf):
            byte = buf[index]
            if in_string:
                if byte == 0x5C:  # backslash: the next character is escaped
                    index += 1
                elif byte == 0x22:
                    in_string = False
            elif byte == 0x22:
                in_string = True
            elif byte in (0x7B, 0x5B):
                depth += 1
            elif byte in (0x7D, 0x5D):
                depth -= 1
                if depth == 0:
                    return index + 1
            elif byte not in _JSON_BYTES:
                return _NOT_JSON
            index += 1
        return None

    def _parse_json(self, unit: bytes) -> Optional[Dict[str, Any]]:
        try:  # NaN and Infinity are not JSON, and FluentHMI Studio's parser rejects them too
            value = json.loads(unit.decode(self._encoding, errors="replace"),
                               parse_constant=_reject_constant)
        except ValueError:
            return None
        if isinstance(value, list):  # a top-level array is keyed by index: "0", "1", ...
            value = {str(index): item for index, item in enumerate(value)}
        return value if isinstance(value, dict) and value else None

    def _parse_record(self, record: bytes) -> Optional[Dict[str, Any]]:
        text = record.decode(self._encoding, errors="replace").strip()
        if not text:
            return None
        if text[0] in "$!" and _NMEA_TAIL.search(text):
            # The checksum covers the bytes as sent between the $ (or !) and the last *.
            sentence = record[record.index(text[0].encode()) + 1:record.rindex(b"*")]
            check = 0
            for byte in sentence:
                check ^= byte
            if check != int(text[-2:], 16):
                return None
            text = text[1:-3]  # what is left is an ordinary record, even an empty one
        return self._parse_line(text)

    def _parse_line(self, text: str) -> Optional[Dict[str, Any]]:
        parts = [p.strip() for p in text.split(self._sep)]

        # KEY=VALUE format (KEY:VALUE with kvSeparator ":")
        if any(self._kv in p for p in parts):
            result = {}
            for p in parts:
                if self._kv in p:
                    k, v = p.split(self._kv, 1)
                    result[k.strip()] = self._auto_number(v.strip())
            return result if result else None

        # pure CSV values — auto-index as ch0, ch1, ...
        result = {}
        for i, p in enumerate(parts):
            result[f"ch{i}"] = self._auto_number(p)
        return result

    @staticmethod
    def _auto_number(s: str):
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        return s


def _reject_constant(name):
    raise ValueError(name)


HEX_ENDIANS = ("大端(BE)", "小端(LE)")
# What a hex frame's length field counts: the data only, everything after the field, or the whole frame.
HEX_LENGTH_COVERS = ("数据", "长度字段之后", "整帧")
# Checksum algorithms and the bytes each puts on the wire, just before the footer.
HEX_CHECKSUMS = {"无": 0, "和校验": 1, "异或": 1, "CRC8": 1, "CRC16-Modbus": 2, "CRC16-CCITT": 2}
# Field types and their sizes; 0 takes any length (ASCII text up to a NUL, HEX text of the bytes).
HEX_FIELD_TYPES = {"uint8": 1, "int8": 1, "uint16": 2, "int16": 2, "uint32": 4, "int32": 4,
                   "float32": 4, "float64": 8, "ASCII": 0, "HEX": 0}
HEX_MAX_FRAME = 65536
HEX_MAX_IDLE = 60000


def hex_bytes(text) -> Optional[bytes]:
    """The bytes hex text spells, whitespace and case aside ("AA 55" is "aa55"); None if it is not hex."""
    if not isinstance(text, str):
        return None
    digits = "".join(text.split())
    if len(digits) % 2 or not re.fullmatch(r"[0-9A-Fa-f]*", digits):
        return None
    return bytes.fromhex(digits)


def _whole(value):
    """An integer setting, or None. JSON has one kind of number, so 2.0 is 2."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def hex_field(item):
    """A field-table entry [名字, 偏移, 长度, 类型(, 字节序)] as a 5-tuple; ValueError names a bad one."""
    entry = isinstance(item, (list, tuple))
    name = item[0] if entry and item and isinstance(item[0], str) else ""
    if entry and len(item) in (4, 5):
        offset, length, dtype = _whole(item[1]), _whole(item[2]), item[3]
        endian = item[4] if len(item) == 5 else HEX_ENDIANS[0]
        size = HEX_FIELD_TYPES.get(dtype) if isinstance(dtype, str) else None
        if (offset is not None and offset >= 0 and length is not None and length > 0
                and size is not None and size in (0, length) and endian in HEX_ENDIANS):
            return name, offset, length, dtype, endian
    raise ValueError(f"无效 HEX 字段: {name}")


def hex_checksum(algorithm: str, data: bytes) -> int:
    """The check value of ``data``; for b"123456789" these give DD 31 F4 4B37 29B1."""
    if algorithm == "和校验":
        return sum(data) & 0xFF
    if algorithm == "异或":
        value = 0
        for byte in data:
            value ^= byte
        return value
    if algorithm == "CRC8":  # polynomial 0x07, initial 0, no reflection, no final XOR
        crc = 0
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        return crc
    if algorithm == "CRC16-Modbus":
        return int.from_bytes(modbus_crc(data), "little")
    if algorithm == "CRC16-CCITT":  # CRC-16/CCITT-FALSE: polynomial 0x1021, initial 0xFFFF
        crc = 0xFFFF
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        return crc
    return 0


class HexFrameParser(BaseParser):
    """Cut binary frames out of a byte stream and read their fields.

    A frame is ``[帧头] [长度字段 …] [数据] [校验] [帧尾]``, every part but the data optional.
    Its end is found by the first rule configured: a fixed length, a length field, the
    footer. With none of them the frame is whatever came after the header before the line
    went quiet, returned by ``flush``. A candidate whose footer or checksum is wrong is not a
    frame: the parser drops one byte and looks again (resync). ``frames`` returns each frame
    whole, header to footer, so raw bindings count offsets from its first byte; field
    offsets count from the byte after the header. Defaults are those of projects that only
    knew a header, a footer and fields.
    """

    def __init__(self, header: Optional[bytes] = b"\xAA\x55", footer: Optional[bytes] = b"\x55\xAA",
                 fields: list = None, max_buffer: int = HEX_MAX_FRAME,
                 length_offset=-1, length_size=1, length_endian=HEX_ENDIANS[0],
                 length_covers=HEX_LENGTH_COVERS[0], fixed_length=0, checksum="无",
                 checksum_start=0, checksum_endian=HEX_ENDIANS[0], idle_timeout=0):
        # None stands for a setting that is not a number or not hex text (from_config). The checks
        # run in a fixed order, so FluentHMI Studio names the same problem in a config with several.
        if (footer == b"" and length_offset is not None and length_offset < 0
                and fixed_length == 0 and idle_timeout == 0):
            raise ValueError("HEX 帧需要帧尾、长度字段、固定帧长或空闲超时之一来分帧")
        if header is None or footer is None:
            raise ValueError("HEX 帧头或帧尾不是十六进制")
        if (fixed_length is not None and fixed_length > 0
                and length_offset is not None and length_offset >= 0):
            raise ValueError("固定帧长和长度字段只能选一个")
        if (length_offset is None or length_offset < -1 or length_size not in (1, 2)
                or length_endian not in HEX_ENDIANS or length_covers not in HEX_LENGTH_COVERS):
            raise ValueError("HEX 长度字段设置无效")
        if fixed_length is None or not 0 <= fixed_length <= HEX_MAX_FRAME:
            raise ValueError("HEX 固定帧长无效")
        if (not isinstance(checksum, str) or checksum not in HEX_CHECKSUMS
                or checksum_start is None or checksum_start < 0 or checksum_endian not in HEX_ENDIANS):
            raise ValueError("HEX 校验设置无效")
        if idle_timeout is None or not 0 <= idle_timeout <= HEX_MAX_IDLE:
            raise ValueError("HEX 空闲超时无效")
        if fields is None:
            fields = []
        if not isinstance(fields, (list, tuple)):
            raise ValueError("无效 HEX 字段: ")
        self._fields = [hex_field(item) for item in fields]
        self._buf = b""
        self._header, self._footer = header, footer
        self._max_buffer = max_buffer
        self._length_offset, self._length_size = length_offset, length_size
        self._length_order = "little" if length_endian == HEX_ENDIANS[1] else "big"
        self._length_covers = length_covers
        self._fixed_length = fixed_length
        self._checksum, self._checksum_size = checksum, HEX_CHECKSUMS[checksum]
        self._checksum_start = checksum_start
        self._checksum_order = "little" if checksum_endian == HEX_ENDIANS[1] else "big"
        self.idle_timeout = idle_timeout

    @classmethod
    def from_config(cls, config: dict) -> "HexFrameParser":
        """A parser for a ``parserConfig``; every key is optional."""
        get = config.get
        return cls(
            header=hex_bytes(get("header", "AA55")), footer=hex_bytes(get("footer", "55AA")),
            fields=get("fields", []),
            length_offset=_whole(get("lengthOffset", -1)), length_size=_whole(get("lengthSize", 1)),
            length_endian=get("lengthEndian", HEX_ENDIANS[0]),
            length_covers=get("lengthCovers", HEX_LENGTH_COVERS[0]),
            fixed_length=_whole(get("fixedLength", 0)), checksum=get("checksum", "无"),
            checksum_start=_whole(get("checksumStart", 0)),
            checksum_endian=get("checksumEndian", HEX_ENDIANS[0]),
            idle_timeout=_whole(get("idleTimeout", 0)))

    @property
    def _has_end_rule(self):
        return bool(self._fixed_length or self._length_offset >= 0 or self._footer)

    def frames(self, data: bytes) -> List[bytes]:
        self._buf += data
        found = []
        while self._buf:
            if self._header:
                start = self._buf.find(self._header)
                if start < 0:
                    keep = len(self._header) - 1
                    self._buf = self._buf[-keep:] if keep else b""
                    break
                self._buf = self._buf[start:]
            size = self._frame_size()
            if size is None:  # the end of the frame has not arrived
                if len(self._buf) > self._max_buffer:
                    self._drop_overflow()
                    continue
                break
            if size < 0 or not self._valid(self._buf[:size]):
                self._buf = self._buf[1:]  # resync: past this header's first byte
                continue
            frame, self._buf = self._buf[:size], self._buf[size:]
            if size <= self._max_buffer:  # a footer can close a frame longer than the buffer
                found.append(frame)
        return found

    def _drop_overflow(self):
        """The buffer holds more than any frame without one ending: drop bytes from the front to where
        dropping one at a time and looking again would stop, in one cut. Waiting for a footer or for
        silence fails from every later start too, so that is the first header in the last
        ``max_buffer`` bytes (with no header, the last ``max_buffer`` bytes)."""
        cut = len(self._buf) - self._max_buffer
        if not self._header:
            self._buf = self._buf[cut:]
            return
        start = self._buf.find(self._header, cut)
        if start >= 0:
            self._buf = self._buf[start:]
        else:
            keep = len(self._header) - 1
            self._buf = self._buf[-keep:] if keep else b""

    def _frame_size(self):
        """The length of the frame the buffer starts with: None until it has all arrived, -1 if
        the length field says this is no frame."""
        buf = self._buf
        if self._fixed_length:
            size = self._fixed_length
        elif self._length_offset >= 0:
            end = self._length_offset + self._length_size
            if len(buf) < end:
                return None
            value = int.from_bytes(buf[self._length_offset:end], self._length_order)
            tail = self._checksum_size + len(self._footer)
            if self._length_covers == "整帧":
                size = value
            elif self._length_covers == "长度字段之后":
                size = end + value
            else:  # 数据: the checksum and footer follow the counted bytes
                size = end + value + tail
            if size < end + tail or size < len(self._header) or size > self._max_buffer:
                return -1
        elif self._footer:
            at = buf.find(self._footer, len(self._header))
            return None if at < 0 else at + len(self._footer)
        else:
            return None  # framed by silence: flush() returns it
        return size if len(buf) >= size else None

    def _valid(self, frame: bytes) -> bool:
        """A frame must have room for its header, checksum and footer, a fixed or counted one must
        end in the footer, and the checksum must match."""
        if len(frame) < len(self._header) + self._checksum_size + len(self._footer):
            return False
        if self._footer and not frame.endswith(self._footer):
            return False
        if not self._checksum_size:
            return True
        at = len(frame) - len(self._footer) - self._checksum_size
        if self._checksum_start > at:
            return False
        sent = int.from_bytes(frame[at:at + self._checksum_size], self._checksum_order)
        return sent == hex_checksum(self._checksum, frame[self._checksum_start:at])

    def flush(self) -> List[bytes]:
        """The line went quiet: what follows the header is a frame, unless a rule should have ended
        it, in which case it is a frame cut short and is dropped."""
        buf, self._buf = self._buf, b""
        if self._has_end_rule or not buf or not buf.startswith(self._header):
            return []
        return [buf] if self._valid(buf) else []

    def parse(self, unit: bytes) -> List[Dict[str, Any]]:
        # Fields lie between the header and the checksum (or footer); one past that range is skipped.
        end = max(len(unit) - self._checksum_size - len(self._footer), 0)
        payload = unit[len(self._header):end]
        result = {}
        for name, offset, length, dtype, endian in self._fields:
            if offset + length <= len(payload):
                result[name] = _hex_value(payload[offset:offset + length], dtype, endian)
        return [result] if result else []


def _hex_value(raw: bytes, dtype: str, endian: str):
    order = "little" if endian == HEX_ENDIANS[1] else "big"
    if dtype in ("float32", "float64"):
        code = ("<" if order == "little" else ">") + ("f" if dtype == "float32" else "d")
        return struct.unpack(code, raw)[0]
    if dtype == "ASCII":
        return raw.split(b"\0", 1)[0].decode("ascii", errors="replace")
    if dtype == "HEX":
        return raw.hex()
    return int.from_bytes(raw, order, signed=dtype.startswith("int"))


# Register tables by read function code, as named in a response: hr100 is holding register 100.
# FC 0x17 (read/write multiple registers) answers with the holding registers it read.
MODBUS_TABLES = {0x01: "co", 0x02: "di", 0x03: "hr", 0x04: "ir", 0x17: "hr"}
# Responses of a fixed size, by function code: the bytes after the function code.
_MODBUS_FIXED = {0x05: 4, 0x06: 4, 0x0F: 4, 0x10: 4, 0x07: 1, 0x08: 4, 0x16: 6}
# Responses that give a byte count and then that many bytes, by function code: whether they
# carry registers, whose count must be even.
_MODBUS_COUNTED = {0x01: False, 0x02: False, 0x03: True, 0x04: True, 0x11: False, 0x17: True}
# Exception responses: the function code with its top bit set, then an exception code.
_MODBUS_EXCEPTIONS = {fc | 0x80 for fc in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                                           0x0F, 0x10, 0x11, 0x16, 0x17)}


def modbus_pdu_size(pdu: bytes) -> Optional[int]:
    """The size of the response PDU (function code onwards) ``pdu`` starts with: 0 if no
    response starts so, None until its byte count has arrived."""
    if not pdu:
        return None
    fc = pdu[0]
    if fc in _MODBUS_COUNTED:
        if len(pdu) < 2:
            return None
        count = pdu[1]
        if not 1 <= count <= 250 or (_MODBUS_COUNTED[fc] and count % 2):
            return 0
        return 2 + count
    if fc in _MODBUS_FIXED:
        return 1 + _MODBUS_FIXED[fc]
    return 2 if fc in _MODBUS_EXCEPTIONS else 0


def modbus_lrc(data: bytes) -> int:
    """The Modbus ASCII check byte: the two's complement of the sum of the bytes."""
    return -sum(data) & 0xFF


def modbus_ascii_body(frame: bytes) -> Optional[bytes]:
    """The bytes a Modbus ASCII frame ``:`` hex pairs, LRC, CR LF spells, without the LRC;
    None unless it is one, with an even number of hex digits (either case) and the right LRC."""
    frame = bytes(frame)
    if not (frame.startswith(b":") and frame.endswith(b"\r\n")):
        return None
    digits = frame[1:-2]
    if len(digits) < 4 or len(digits) % 2 or not re.fullmatch(rb"[0-9A-Fa-f]*", digits):
        return None
    raw = bytes.fromhex(digits.decode("ascii"))
    return raw[:-1] if modbus_lrc(raw[:-1]) == raw[-1] else None


class ModbusRequests:
    """Read requests recently sent over one link, so a response can be named by register address.

    A Modbus response does not repeat the start address. Modbus TCP echoes the request's
    transaction id; an RTU master waits for each reply, so an RTU response answers the
    latest read with the same slave and function code. Each parser answers such a read
    once, so every client of a server names its reply and a later reply is not named by
    a stale read. Requests are noted on the main thread while a serial reader thread
    reads them: a note is one dict assignment, and what a parser has answered is its own.
    """

    def __init__(self):
        self._latest = {}
        self._noted = 0  # numbers the RTU reads, so a parser can tell a new one from one it answered
        self._transactions = {}

    def note(self, slave, fc, address, count, transaction=None):
        if transaction is None:
            self._noted += 1
            self._latest[(slave, fc)] = (address, count, self._noted)
            return
        if len(self._transactions) >= 256:
            self._transactions.pop(next(iter(self._transactions)), None)
        self._transactions[transaction] = (slave, fc, address, count)

    def note_frame(self, frame, parser_type):
        """Note the read in an outgoing request frame, framed the way the link parses replies:
        a read (FC 01-04), or the read half of FC 0x17 read/write multiple registers."""
        frame = bytes(frame)
        transaction = None
        if parser_type == "modbus" and len(frame) >= 8 and modbus_crc(frame[:-2]) == frame[-2:]:
            body = frame[:-2]
        elif (parser_type == "modbus_tcp" and len(frame) >= 12 and frame[2:4] == b"\x00\x00"
              and int.from_bytes(frame[4:6], "big") == len(frame) - 6):
            body, transaction = frame[6:], int.from_bytes(frame[:2], "big")
        elif parser_type == "modbus_ascii":
            body = modbus_ascii_body(frame)
            if body is None or len(body) < 6:
                return
        else:
            return
        fc = body[1]
        # FC 0x17: read address and count, write address and count, byte count, the values
        # written; the length the write count gives is the check, as in FluentHMI Studio.
        if (fc in (1, 2, 3, 4) and len(body) == 6) or (
                fc == 0x17 and len(body) >= 11 and len(body) == 11 + 2 * int.from_bytes(body[8:10], "big")):
            self.note(body[0], fc, int.from_bytes(body[2:4], "big"),
                      int.from_bytes(body[4:6], "big"), transaction)

    def take(self, slave, fc, transaction=None, answered=None):
        """(address, count) of the read this response answers, or None.

        ``answered`` is the calling parser's record of the RTU reads it has answered;
        with it, a read names one reply per parser.
        """
        fc &= 0x7F  # an exception response answers the same request
        if transaction is None:
            entry = self._latest.get((slave, fc))
            if entry is None:
                return None
            address, count, number = entry
            if answered is not None:
                if answered.get((slave, fc)) == number:
                    return None
                answered[(slave, fc)] = number
            return address, count
        request = self._transactions.get(transaction)  # a server's clients all answer one request
        if request is None or request[:2] != (slave, fc):
            return None
        return request[2:]


class ModbusRTUParser(BaseParser):
    """Parse Modbus RTU response frames.

    Reads the replies to FC 01-08, 0x0F, 0x10, 0x11, 0x16 and 0x17 and exceptions as
    modbus_response does: register values become named fields reg0, reg1, … (or custom
    field names), plus hr100, … by register address when the request is known.
    """

    def __init__(self, fields: list = None, requests: ModbusRequests = None):
        self._buf = b""
        self._fields = fields or []
        self.requests = requests if requests is not None else ModbusRequests()
        self._answered = {}  # the reads this stream has answered (ModbusRequests.take)

    @staticmethod
    def _frame_length(buf):
        """Length of the RTU frame starting at buf[0] (slave, PDU, CRC); 0 if these bytes cannot start one."""
        if len(buf) < 3:
            return None
        if not 1 <= buf[0] <= 247:
            return 0
        size = modbus_pdu_size(buf[1:])
        return size + 3 if size else 0

    def parse(self, data: bytes) -> List[Dict[str, Any]]:
        self._buf += data
        results = []
        while len(self._buf) >= 5:
            length = self._frame_length(self._buf)
            if not length:
                self._buf = self._buf[1:]
                continue
            if len(self._buf) < length:
                # Noise may imitate a long header. Resync only to a complete,
                # CRC-verified response; otherwise keep the partial frame.
                found = False
                for offset in range(1, len(self._buf) - 4):
                    tail = self._buf[offset:]
                    size = self._frame_length(tail)
                    if size and len(tail) >= size and modbus_crc(tail[:size - 2]) == tail[size - 2:size]:
                        self._buf = tail
                        found = True
                        break
                if found:
                    continue
                break
            frame = self._buf[:length]
            if modbus_crc(frame[:-2]) != frame[-2:]:
                self._buf = self._buf[1:]
                continue
            self._buf = self._buf[length:]
            request = self.requests.take(frame[0], frame[1], answered=self._answered)
            results.append(modbus_response(frame[0], frame[1], frame[2:-2], self._fields, request))
        return results


def modbus_response(slave: int, fc: int, data: bytes, fields=(), request=None) -> Dict[str, Any]:
    """Interpret a response PDU body (the bytes after the function code).

    Shared by the RTU, TCP and ASCII parsers, so all produce the same dictionaries:
    ``reg0, reg1, …`` or ``coil0, coil1, …`` (or custom field names) for reads,
    ``address``/``value`` for write echoes and ``error`` for exceptions; FC 07 gives
    ``status``, 08 ``subfunction``/``data``, 11 ``id``/``run``/``extra``, 16
    ``address``/``andMask``/``orMask`` and 17 registers like 03. When the
    read it answers is known (``request`` is its address and count), ``start`` and
    keys by address follow: ``hr100``, ``ir100``, ``co100`` or ``di100``.
    """
    result: Dict[str, Any] = {"slave": slave, "fc": fc}
    values = []
    if fc in (0x03, 0x04, 0x17):
        payload = data[1:]
        regs = []
        for i in range(0, len(payload), 2):
            if i + 1 < len(payload):
                regs.append(int.from_bytes(payload[i:i + 2], "big"))
        for idx, val in enumerate(regs):
            name = fields[idx] if idx < len(fields) else f"reg{idx}"
            result[name] = val
        if request and request[1] == len(regs):
            values = regs
    elif fc in (0x01, 0x02):
        bits = []
        for b in data[1:]:
            for bit_i in range(8):
                bits.append((b >> bit_i) & 1)
        for idx, val in enumerate(bits):
            name = fields[idx] if idx < len(fields) else f"coil{idx}"
            result[name] = val
        if request and (request[1] + 7) // 8 == len(data) - 1:
            values = bits[:request[1]]  # the rest of the last byte is padding
    elif fc >= 0x80:
        result["error"] = data[0]
        if request:
            result["start"] = request[0]
    elif fc == 0x07:  # read exception status
        result["status"] = data[0]
    elif fc == 0x08:  # diagnostics echo their sub-function and data
        result["subfunction"] = int.from_bytes(data[0:2], "big")
        result["data"] = int.from_bytes(data[2:4], "big")
    elif fc == 0x11:  # report server id: the id, the run indicator, then device-specific bytes
        result["id"] = data[1]
        result["run"] = 1 if data[2:3] == b"\xff" else 0
        result["extra"] = data[3:].hex()
    elif fc == 0x16:  # mask write register echoes the request
        result["address"] = int.from_bytes(data[0:2], "big")
        result["andMask"] = int.from_bytes(data[2:4], "big")
        result["orMask"] = int.from_bytes(data[4:6], "big")
    else:
        result["address"] = int.from_bytes(data[0:2], "big")
        result["value"] = int.from_bytes(data[2:4], "big")
    if values:
        start = result["start"] = request[0]
        table = MODBUS_TABLES[fc]
        for offset, val in enumerate(values):
            result[f"{table}{start + offset}"] = val
    return result


class ModbusTCPParser(BaseParser):
    """Parse Modbus TCP response ADUs.

    An ADU is a 7-byte MBAP header (transaction id, protocol id 0, length, unit id)
    followed by the PDU; there is no CRC, so the length field and the PDU layout are
    the only framing checks. Output matches ModbusRTUParser, with the unit id as ``slave``.
    """

    def __init__(self, fields: list = None, requests: ModbusRequests = None):
        self._buf = b""
        self._fields = fields or []
        self.requests = requests if requests is not None else ModbusRequests()

    @staticmethod
    def _frame_length(buf):
        """Length of the ADU starting at buf[0]; 0 if these bytes cannot start one. The MBAP
        length counts the unit id and the PDU, and must match what the function code implies."""
        if int.from_bytes(buf[2:4], "big") != 0:
            return 0
        length = int.from_bytes(buf[4:6], "big")
        size = modbus_pdu_size(buf[7:])
        if not size or length != size + 1:
            return 0
        return 6 + length

    def parse(self, data: bytes) -> List[Dict[str, Any]]:
        self._buf += data
        results = []
        while len(self._buf) >= 9:  # the shortest ADU is an exception response
            length = self._frame_length(self._buf)
            if not length:
                self._buf = self._buf[1:]
                continue
            if len(self._buf) < length:
                break
            frame = self._buf[:length]
            self._buf = self._buf[length:]
            request = self.requests.take(frame[6], frame[7], int.from_bytes(frame[0:2], "big"))
            results.append(modbus_response(frame[6], frame[7], frame[8:], self._fields, request))
        return results


class ModbusASCIIParser(BaseParser):
    """Parse Modbus ASCII response frames.

    A frame is ``:``, the RTU frame without its CRC as hex pairs, an LRC and CR LF. A
    candidate runs from a ``:`` to the next CR LF; one that is not hex, has a wrong LRC or
    is not a response is dropped, and the search goes on from the next ``:``. Output and
    naming by register address match ModbusRTUParser: an ASCII master also waits for each reply.
    """

    MAX_FRAME = 511  # ":" + 2 × (slave + PDU of at most 253 bytes + LRC), before CR LF

    def __init__(self, fields: list = None, requests: ModbusRequests = None):
        self._buf = b""
        self._fields = fields or []
        self.requests = requests if requests is not None else ModbusRequests()
        self._answered = {}  # the reads this stream has answered (ModbusRequests.take)

    def parse(self, data: bytes) -> List[Dict[str, Any]]:
        self._buf += data
        results = []
        while True:
            start = self._buf.find(b":")
            if start < 0:
                self._buf = b""
                break
            self._buf = self._buf[start:]
            end = self._buf.find(b"\r\n", 1)
            if end < 0:
                if len(self._buf) > self.MAX_FRAME:  # too long for a frame: look from the next ':'
                    self._buf = self._buf[1:]
                    continue
                break
            body = modbus_ascii_body(self._buf[:end + 2])
            if body is None or len(body) < 2 or not 1 <= body[0] <= 247 or (
                    modbus_pdu_size(body[1:]) != len(body) - 1):
                self._buf = self._buf[1:]  # resync from the next ':'
                continue
            self._buf = self._buf[end + 2:]
            request = self.requests.take(body[0], body[1], answered=self._answered)
            results.append(modbus_response(body[0], body[1], body[2:], self._fields, request))
        return results


def modbus_crc(data: bytes) -> bytes:
    """Calculate Modbus RTU CRC-16."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, "little")


def build_modbus_frame(slave: int, func: int, address: int,
                       value: int = 0, count: int = 1, registers=()) -> bytes:
    """Build a Modbus RTU request frame.

    Supports FC 01-06 and 0x10.
    For FC 01-04: count = number of registers/coils to read.
    For FC 05: value = 0xFF00 (ON) or 0x0000 (OFF).
    For FC 06: value = register value to write.
    For FC 0x10: registers = the register values to write from address on.
    """
    pdu = bytes([slave, func])
    pdu += address.to_bytes(2, "big")

    if func in (0x01, 0x02, 0x03, 0x04):
        pdu += count.to_bytes(2, "big")
    elif func == 0x10:
        pdu += len(registers).to_bytes(2, "big") + bytes([2 * len(registers)])
        pdu += b"".join(register.to_bytes(2, "big") for register in registers)
    else:
        pdu += value.to_bytes(2, "big")

    return pdu + modbus_crc(pdu)


def build_modbus_ascii_frame(slave: int, func: int, address: int, value: int = 0,
                             count: int = 1, registers=()) -> bytes:
    """Build a Modbus ASCII request: ':', the RTU frame without CRC as uppercase hex, LRC, CR LF."""
    body = build_modbus_frame(slave, func, address, value, count, registers)[:-2]
    return b":" + (body + bytes([modbus_lrc(body)])).hex().upper().encode("ascii") + b"\r\n"


def build_modbus_tcp_frame(unit: int, func: int, address: int, value: int = 0,
                           count: int = 1, transaction: int = 0, registers=()) -> bytes:
    """Build a Modbus TCP request ADU: MBAP header plus the same PDU as RTU, without CRC."""
    pdu = build_modbus_frame(unit, func, address, value, count, registers)[1:-2]
    body = bytes([unit]) + pdu
    return (transaction.to_bytes(2, "big") + b"\x00\x00"
            + len(body).to_bytes(2, "big") + body)


# The parsing modes a link offers, as .uidp files and the property panel name them.
PARSER_TYPES = ("line", "hex", "modbus", "modbus_tcp", "modbus_ascii")


def text_encoding(parser_type, config=None):
    """The encoding a link's text arrives in: the line parser's, UTF-8 for every other parser."""
    if parser_type != "line":
        return "utf-8"
    encoding = (config or {}).get("encoding", "utf-8")
    return encoding.lower() if isinstance(encoding, str) else "utf-8"


def create_parser(parser_type: str, config: dict = None, requests: ModbusRequests = None) -> BaseParser:
    """A parser for one byte stream; Modbus parsers on one link share that link's requests."""
    config = config or {}
    if parser_type == "line":
        return LineParser.from_config(config)
    elif parser_type == "hex":
        return HexFrameParser.from_config(config)
    elif parser_type == "modbus":
        return ModbusRTUParser(fields=config.get("fields", []), requests=requests)
    elif parser_type == "modbus_tcp":
        return ModbusTCPParser(fields=config.get("fields", []), requests=requests)
    elif parser_type == "modbus_ascii":
        return ModbusASCIIParser(fields=config.get("fields", []), requests=requests)
    raise ValueError(f"未知解析模式: {parser_type}")

"""Modbus master queue, one per link, shared by the designer and standalone exports.

Every Modbus request a link carries goes through its master: a control's command, the
Modbus poller's reads. The master puts one request on the wire, waits for the reply that
answers it or for its timeout, then sends the next one, so a reply is never taken for the
answer to another request. Writes go ahead of the reads waiting in the queue (behind
earlier writes), so polling never holds up a button for more than the read already on the
wire. A reply answers the request in flight when its slave and function code match (an
exception, fc | 0x80, too) and so does the address it names: the start a read reply is
named by (Modbus requests) or the address a write reply echoes.

Also the block planner of the Modbus poller (modbus_poller): what bound widgets and chart
curves read, merged into as few reads as the gap and length limits allow.
"""
from PyQt5.QtCore import QObject, QTimer



# The link parsers that read Modbus replies; requests on other links are sent and not answered.
MODBUS_PARSERS = ("modbus", "modbus_tcp", "modbus_ascii")
MODBUS_EXCEPTIONS = {
    1: "非法功能码", 2: "非法数据地址", 3: "非法数据值", 4: "从站设备故障",
    5: "已确认，处理中", 6: "从站忙", 10: "网关路径不可用", 11: "网关目标设备无响应",
}


def modbus_problem(data):
    """Why a reply is not a success, or None: the exception code a device answered with."""
    code = data.get("error")
    if code is None:
        return None
    return f"异常 {code:02X} {MODBUS_EXCEPTIONS.get(code, '')}".rstrip()


_transaction = [0]


def next_modbus_transaction():
    """Successive MBAP transaction identifiers, wrapping at 16 bits."""
    _transaction[0] = (_transaction[0] + 1) & 0xFFFF
    return _transaction[0]


def modbus_frame(request, transaction=None, ascii_frame=False):
    """A validated request (command_runtime.modbus_request) as an RTU frame, as a Modbus TCP ADU
    given its transaction id, or as a Modbus ASCII frame."""
    slave, func, address, value = request
    registers, value = (value, 0) if func == 0x10 else ((), value)
    if transaction is not None:
        return build_modbus_tcp_frame(slave, func, address, value, value, transaction, registers)
    if ascii_frame:
        return build_modbus_ascii_frame(slave, func, address, value, value, registers)
    return build_modbus_frame(slave, func, address, value, value, registers)


def link_frame(link, request):
    """The request framed the way a link parses: MBAP for modbus_tcp, ASCII for modbus_ascii, else RTU."""
    parser_type = getattr(link, "parser_type", "")
    if parser_type == "modbus_tcp":
        return modbus_frame(request, next_modbus_transaction())
    return modbus_frame(request, ascii_frame=parser_type == "modbus_ascii")


def modbus_dispatch(hub, request, timeout_ms=1000, priority="write", on_done=None, owner=None,
                    modbus_only=False):
    """Send a validated request over every connected link of a hub (or over one link).

    A connected link that parses Modbus queues it in its master, which calls ``on_done``
    once with the outcome; any other link gets the frame at once and no answer is awaited
    (with ``modbus_only``, it gets nothing). A link answering as a Modbus slave gets nothing either.
    Returns ``(frame, master)`` for each link that took it; ``master`` is None for a link written directly.
    """
    links = getattr(hub, "connected_links", None)
    if links is None:  # a single link rather than a hub
        links = [hub] if hub.is_connected else []
    accepted = []
    for link in links:
        if getattr(link, "slave_active", False):
            continue
        master = getattr(link, "modbus_master", None)
        if master is not None and getattr(link, "parser_type", "") in MODBUS_PARSERS:
            frame = master.enqueue(request, timeout_ms, priority, on_done, owner=owner)
            if frame is not None:
                accepted.append((frame, master))
        elif not modbus_only:
            frame = link_frame(link, request)
            if link.send(frame):
                accepted.append((frame, None))
    return accepted


class ModbusResult:
    """What became of one request: ``ok``, the parsed reply (``message``, empty without one) and
    ``problem``: the exception, or why there is no reply; empty on success."""
    __slots__ = ("ok", "message", "problem")

    def __init__(self, ok, message, problem):
        self.ok, self.message, self.problem = ok, message, problem

    def __repr__(self):
        return f"ModbusResult({self.ok!r}, {self.message!r}, {self.problem!r})"


class _Queued:
    __slots__ = ("request", "frame", "timeout", "on_done", "write", "owner")

    def __init__(self, request, frame, timeout, on_done, write, owner):
        self.request, self.frame, self.timeout = request, frame, timeout
        self.on_done, self.write, self.owner = on_done, write, owner


class ModbusMaster(QObject):
    """The Modbus request queue of one link (a TCP server's peers share one: a reply from any
    of them answers)."""

    def __init__(self, link):
        super().__init__(link)
        self._link = link
        self._queue = []      # writes first, then reads, each in the order they came
        self._current = None  # the request on the wire
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        link.dataReceived.connect(self._on_data)
        link.disconnected.connect(self.cancel_all)

    def busy(self):
        """A request is on the wire, waiting for its reply."""
        return self._current is not None

    def pending(self):
        """Requests waiting for the one on the wire."""
        return len(self._queue)

    def enqueue(self, request, timeout_ms=1000, priority="read", on_done=None, owner=None):
        """Queue a request; the frame it goes out as, or None when it was not taken.

        ``priority`` ``"write"`` puts it ahead of the waiting reads, ``"read"`` at the end.
        ``on_done(result)`` is called once, with the reply, the exception or the timeout. A
        link that is down, or refuses a request that would go out at once, does not take it,
        and ``on_done`` is not called.
        """
        if not self._link.is_connected:
            return None
        entry = _Queued(request, link_frame(self._link, request), max(1, int(timeout_ms)),
                        on_done, priority == "write", owner)
        if self._current is None and not self._queue:
            return entry.frame if self._start(entry) else None
        if entry.write:
            self._queue.insert(sum(1 for queued in self._queue if queued.write), entry)
        else:
            self._queue.append(entry)
        return entry.frame

    def withdraw(self, owner):
        """Drop the queued requests of ``owner`` that have not gone out yet, without calling back."""
        self._queue = [entry for entry in self._queue if entry.owner is not owner]

    def cancel_all(self):
        """The link is gone: every request, on the wire or queued, ends as timed out."""
        entries = ([self._current] if self._current is not None else []) + self._queue
        self._current, self._queue = None, []
        self._timer.stop()
        for entry in entries:
            self._call(entry, ModbusResult(False, {}, f"无响应（{entry.timeout} ms 超时）"))

    # -- the wire ---------------------------------------------------------------

    def _start(self, entry):
        if not self._link.send(entry.frame):  # the link reports why through its error signal
            return False
        self._current = entry
        self._timer.start(entry.timeout)
        return True

    def _pump(self):
        while self._current is None and self._queue:
            entry = self._queue.pop(0)
            if not self._start(entry):
                self._call(entry, ModbusResult(False, {}, "发送失败"))

    @staticmethod
    def _call(entry, result):
        if entry.on_done is not None:
            entry.on_done(result)

    def _finish(self, result):
        entry, self._current = self._current, None
        self._timer.stop()
        # The caller hears first, so a read it queues in reply still goes behind a waiting write.
        self._call(entry, result)
        self._pump()

    def _on_timeout(self):
        if self._current is not None:
            self._finish(ModbusResult(False, {}, f"无响应（{self._current.timeout} ms 超时）"))

    def _answers(self, data):
        slave, fc, address = self._current.request[:3]
        reply = data.get("fc")
        if data.get("slave") != slave or reply not in (fc, fc | 0x80):
            return False
        if reply == fc and fc in (1, 2, 3, 4):
            # A read reply names its start when it holds what was asked; one without it
            # (another count of registers or coils) answers some other read.
            return data.get("start") == address
        where = data.get("start", data.get("address"))  # write replies echo the address
        return where is None or where == address

    def _on_data(self, data):
        if self._current is None or not self._answers(data):
            return  # not the answer; the bindings still get it
        problem = modbus_problem(data)
        self._finish(ModbusResult(problem is None, data, "" if problem is None else f"设备返回{problem}"))


# -- the polling plan -------------------------------------------------------------

FUNCTION_OF_TABLE = {"hr": 3, "ir": 4, "co": 1, "di": 2}
MAX_GAP = {3: 8, 4: 8, 1: 64, 2: 64}       # unused registers / bits a block may read across
MAX_LEN = {3: 120, 4: 120, 1: 1000, 2: 1000}  # registers / bits one block reads at most


def plan_blocks(needs, default_period):
    """Read blocks covering what is needed: ``[slave, fc, start, count, period]`` in (slave, fc, start) order.

    A need is a mapping of ``slave``, ``table`` (hr / ir / co / di), ``address``, ``count``
    (registers, or bits for coils and discrete inputs) and ``period`` in ms (0: the default).
    Needs of one slave and table, sorted by address, join the open block while the gap to it
    stays within MAX_GAP and the block within MAX_LEN; a block is read as often as its most
    frequent need. tests/data/poll_plan_vectors.json holds the cases both repositories check.
    """
    groups = {}
    for need in needs:
        fc = FUNCTION_OF_TABLE[need["table"]]
        period = need.get("period", 0) or default_period
        groups.setdefault((need["slave"], fc), []).append((need["address"], need["count"], period))
    blocks = []
    for (slave, fc), items in sorted(groups.items()):
        items.sort()
        start = end = period = None
        for address, count, need_period in items:
            need_end = address + count
            if start is not None and address <= end + MAX_GAP[fc] and need_end - start <= MAX_LEN[fc]:
                end = max(end, need_end)
                period = min(period, need_period)
            else:
                if start is not None:
                    blocks.append([slave, fc, start, end - start, period])
                start, end, period = address, need_end, need_period
        if start is not None:
            blocks.append([slave, fc, start, end - start, period])
    blocks.sort(key=lambda block: (block[0], block[1], block[2]))
    return blocks

"""The Modbus slave (RTU and TCP) of a link card in the 从站 role, shared by the designer preview and exports.

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



# The link parsers a slave answers with: RTU frames (modbus) or MBAP frames (modbus_tcp).
SLAVE_PARSERS = ("modbus", "modbus_tcp")
SLAVE_ROLE = "从站"
TABLES = ("co", "di", "hr", "ir")
READ_FUNCTIONS = {"co": 1, "di": 2, "hr": 3, "ir": 4}
# The tables by the area names bindings use, as binding_values.MODBUS_AREAS.
AREA_TABLES = {"保持寄存器": "hr", "输入寄存器": "ir", "线圈": "co", "离散输入": "di"}
DEFAULT_AREA = (0, 100)  # start, count
MAX_COUNT = 10000

EXCEPTION_NAMES = {1: "非法功能码", 2: "非法数据地址", 3: "非法数据值"}
FUNCTION_NAMES = {1: "读线圈", 2: "读离散输入", 3: "读保持寄存器", 4: "读输入寄存器",
                  5: "写单线圈", 6: "写单寄存器", 15: "写多个线圈", 16: "写多个寄存器"}

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
    """The data table a serial or TCP card's properties describe, as the card builds it at the start."""
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
        return f"功能码 {fc:02X}"
    text = FUNCTION_NAMES[fc]
    if len(pdu) >= 5:
        address, value = _u16(pdu, 1), _u16(pdu, 3)
        if fc == 5:
            text += f" 地址 {address} 值 {value:04X}"
        elif fc == 6:
            text += f" 地址 {address} 值 {value}"
        else:
            text += f" 地址 {address} 数量 {value}"
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
        line = f"收 {hex_text(frame)} · {describe(pdu)}"
        if broadcast and fc in (1, 2, 3, 4):
            return None, [[f"{line} · 广播 · 不应答", "info"]], []
        result, written = handle(self.store, pdu)
        emits = [self.store.message(self.slave, *written)] if written else []
        if isinstance(result, int):
            problem = f"异常 {result:02X} {EXCEPTION_NAMES[result]}"
            if broadcast:
                return None, [[f"{line} · {problem} · 广播 · 不应答", "warn"]], emits
            if not self.exceptions:
                return None, [[f"{line} · {problem} · 不应答", "warn"]], emits
            reply_pdu, ok = bytes([fc | 0x80, result]), False
        else:
            if broadcast:
                return None, [[f"{line} · 广播 · 不应答", "info"]], emits
            reply_pdu, ok = result, True
        if self.framing == "rtu":
            body = bytes([unit]) + reply_pdu
            reply = body + modbus_crc(body)
        else:
            reply = frame[:4] + (len(reply_pdu) + 1).to_bytes(2, "big") + bytes([unit]) + reply_pdu
        tail = "正常" if ok else problem
        return reply, [[line, "info"], [f"发 {hex_text(reply)} · {tail}", "ok" if ok else "warn"]], emits


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

"""The Modbus slave of a link card in the 从站 role, on its link: shared by the designer preview and exports.

A serial or TCP card whose 设计角色 is 从站 owns a ModbusSlaveDevice: the data table (modbus_slave.SlaveStore),
built from the card's areas and 初始值 when it is first needed and kept while the program runs, whether the
link is connected or not. Every write to it (an external master's, a control's, a command's, the register
table's) gives a slave message on ``written``, which the card publishes on its link like a parsed frame.

When the card connects its link and the link parses modbus or modbus_tcp, the link frames requests with the
device's framer and hands each one to ``receive``. A write takes effect at once; the reply goes out 响应延时
(``delay``) ms after its request came in, the replies one after another in the order the requests came. The
link's ``slaveLog`` carries the log lines (the reply's when it goes out), and the counts of replies and of
failed requests start from 0 at each connection.
"""
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal




class ModbusSlaveDevice(QObject):
    written = pyqtSignal(dict)    # a slave message: after a write, or one per area at the start
    statusChanged = pyqtSignal()  # a reply went out, or a request failed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.address = 1       # 默认从站: this slave's address
        self.exceptions = True  # 异常响应
        self.delay = 0         # 响应延时 ms
        self._areas = {table: DEFAULT_AREA for table in TABLES}
        self._init = ""
        self._store = None
        self._link = None      # the link answering with this table, and how
        self._slave = None
        self._pending = []     # (when it is due, reply, its log line, how to send it)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._pump)
        self.replies = self.errors = 0

    # -- the data table -----------------------------------------------------------

    def set_area(self, table, start=None, count=None):
        old_start, old_count = self._areas[table]
        self._areas[table] = (old_start if start is None else start, old_count if count is None else count)
        self._store = None

    def set_init(self, text):
        self._init = str(text)
        self._store = None

    @property
    def store(self):
        if self._store is None:
            self._store = SlaveStore(self._areas, self._init)
        return self._store

    def publish_start(self):
        """The whole table, one message per area that has addresses, so bound widgets show it from the start."""
        for message in self.store.start_messages(self.address):
            self.written.emit(message)

    def write(self, table, address, values):
        """Write ``values`` from ``address`` on and publish the change; False, writing nothing, unless every
        address is in the area."""
        store = self.store
        if not store.has(table, address, len(values)):
            return False
        store.set(table, address, values)
        self.written.emit(store.message(self.address, table, range(address, address + len(values))))
        return True

    # -- on the link -----------------------------------------------------------

    @staticmethod
    def framer(parser_type):
        return request_framer(parser_type)

    def begin(self, link, parser_type):
        """``link`` answers requests from now on, framed as ``parser_type`` (modbus or modbus_tcp)."""
        self.end()
        self._link = link
        self._slave = ModbusSlave("tcp" if parser_type == "modbus_tcp" else "rtu",
                                  self.address, self.exceptions, self.store)
        self.replies = self.errors = 0
        self.statusChanged.emit()

    def end(self):
        """The link stopped answering: replies not sent yet are dropped."""
        self._link = self._slave = None
        self._pending = []
        self._timer.stop()

    def receive(self, frame, send):
        """A request ``frame`` the link received; ``send(reply)`` writes the reply where the request came from
        and is True once it went out."""
        if self._slave is None:
            return
        reply, log, messages = self._slave.request(frame)
        if not log:
            return  # to another slave
        self._log(*log[0])
        if any(level == "warn" for _text, level in log):
            self.errors += 1
            self.statusChanged.emit()
        for message in messages:
            self.written.emit(message)
        if reply is not None:
            self._pending.append((time.monotonic() + self.delay / 1000, reply, log[1], send))
            self._pump()

    def _pump(self):
        while self._pending and not self._timer.isActive():
            due, reply, line, send = self._pending[0]
            wait = due - time.monotonic()
            if wait > 0:
                self._timer.start(max(1, round(wait * 1000)))
                return
            self._pending.pop(0)
            if send(reply):
                self.replies += 1
                self._log(*line)
                self.statusChanged.emit()

    def _log(self, text, level):
        if self._link is not None:
            self._link.slaveLog.emit(text, level)

    def status_text(self):
        """What the card shows after its connection: 从站 S · 应答 N, and · 异常 M once a request failed."""
        text = f"从站 {self.address} · 应答 {self.replies}"
        return f"{text} · 异常 {self.errors}" if self.errors else text

# coding: utf-8
"""Serial runtime shared by the designer and standalone exports."""
import sys
import time
from typing import List, Dict
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, QObject




try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


def _list_all_ports() -> List[Dict[str, str]]:
    """Enumerate serial ports, merging pyserial results with Windows registry
    to ensure virtual COM ports (Eltima, com0com, etc.) are included."""
    found: Dict[str, str] = {}

    if HAS_SERIAL:
        for p in serial.tools.list_ports.comports():
            device = p.device.upper() if sys.platform == "win32" else p.device
            found[device] = p.description

    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DEVICEMAP\SERIALCOMM",
            )
            i = 0
            while True:
                try:
                    _name, val, _ = winreg.EnumValue(key, i)
                    port_upper = val.upper()
                    if port_upper not in found:
                        found[port_upper] = val
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass

    def _sort_key(port: str) -> tuple:
        import re
        m = re.search(r"(\d+)$", port)
        return (int(m.group(1)) if m else 999, port)

    return [
        {"port": p, "description": d}
        for p, d in sorted(found.items(), key=lambda x: _sort_key(x[0]))
    ]


class SerialReaderThread(QThread):
    """Background thread continuously reading from serial port.

    Each raw unit the parser cuts is published before the messages read from it. A parser
    that frames by silence is flushed once the port has been quiet for its idle timeout,
    timed here, since this thread has no event loop for a timer.
    """

    rawReceived = pyqtSignal(bytes)
    parsedReceived = pyqtSignal(dict)
    errorOccurred = pyqtSignal(str)

    def __init__(self, port, parser: BaseParser, parent=None):
        super().__init__(parent)
        self._port = port
        self._parser = parser
        self._running = True

    def run(self):
        idle = self._parser.idle_timeout / 1000
        last_read = None  # when data last arrived, while the parser may hold a frame for flush()
        while self._running:
            try:
                if self._port.in_waiting > 0:
                    data = self._port.read(self._port.in_waiting)
                    self._publish(self._parser.frames(data))
                    if idle and data:
                        last_read = time.monotonic()
                else:
                    if last_read is not None and time.monotonic() - last_read >= idle:
                        last_read = None
                        self._publish(self._parser.flush())
                    # A short idle timeout needs a finer poll, or two bursts read as one.
                    self.msleep(10 if last_read is None else min(10, self._parser.idle_timeout))
            except Exception as e:
                if self._running:
                    self.errorOccurred.emit(str(e))
                break

    def _publish(self, units):
        for unit in units:
            self.rawReceived.emit(unit)
            for parsed in self._parser.parse(unit):
                self.parsedReceived.emit(parsed)

    def stop(self):
        self._running = False
        if not self.wait(2000):
            raise RuntimeError("串口读取线程未能停止")


class SerialHandler(QObject):
    """The serial link. Connected with a card's slave (slave_runtime.ModbusSlaveDevice) while it parses
    modbus or modbus_tcp, it answers the requests it reads instead of parsing replies."""
    text_encoding = "utf-8"  # of the text this link receives, for the receive log
    slave_data = False  # True while dataReceived carries a slave message (publish_slave_data)
    uses_port_settings = True  # the hub hands it the project's whole serial settings, not only the frame format
    dataReceived = pyqtSignal(dict)
    rawReceived = pyqtSignal(bytes)
    dataSent = pyqtSignal(bytes)
    connectionChanged = pyqtSignal(bool)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    error = pyqtSignal(str)
    slaveLog = pyqtSignal(str, str)  # a slave's log line and its level
    DEFAULT_CONFIG = {}

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self._port = None
        self._thread = None
        self._parser = None
        self.modbus_requests = ModbusRequests()  # names responses by register address
        self.modbus_master = ModbusMaster(self)  # one Modbus request on the wire at a time
        self.slave_device = None  # the slave answering on this link while it is connected as one
        self.configure(config or self.DEFAULT_CONFIG)

    def configure(self, config):
        self._config = {"baudRate": 115200, "dataBits": 8, "parity": "None",
                        "stopBits": 1, "flowControl": "none", "parser": "line",
                        "parserConfig": {"separator": ","}, **config}
        self.parser_type = self._config["parser"]  # Modbus commands are framed to match

    @property
    def is_connected(self):
        return self._port is not None and getattr(self._port, "is_open", False)

    @property
    def slave_active(self):
        """Answering as a Modbus slave: the poller and Modbus commands leave this link alone."""
        return self.slave_device is not None

    def publish_slave_data(self, message):
        """A slave message, published like a parsed frame; slave_data tells the log box to leave it out."""
        self.slave_data = True
        try:
            self.dataReceived.emit(message)
        finally:
            self.slave_data = False

    @staticmethod
    def list_ports():
        return _list_all_ports()

    def connect(self, port, baudrate=None, databits=None, parity=None, stopbits=None,
                flowcontrol=None, parser_type=None, parser_config=None, slave=None):
        if not HAS_SERIAL:
            self.error.emit("pyserial 未安装，请运行 pip install pyserial")
            return False
        cfg = self._config
        parity_map = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"}
        parity = parity if parity is not None else cfg["parity"]
        flow = flowcontrol if flowcontrol is not None else cfg["flowControl"]
        flow = {"无": "none", "RTS/CTS": "rtscts", "XON/XOFF": "xonxoff", "DTR/DSR": "dsrdtr"}.get(flow, flow)
        try:
            selected_parser = parser_type if parser_type is not None else cfg["parser"]
            selected_config = parser_config
            if selected_config is None:
                selected_config = cfg["parserConfig"] if selected_parser == cfg["parser"] else {}
            if selected_parser not in SLAVE_PARSERS:
                slave = None  # another mode: the card's slave settings do not count
            parser = (slave.framer(selected_parser) if slave is not None
                      else create_parser(selected_parser, selected_config, self.modbus_requests))
            if self._thread or self._port:
                self.disconnect()
            port_obj = serial.Serial(
                port=port, baudrate=baudrate if baudrate is not None else cfg["baudRate"],
                bytesize=databits if databits is not None else cfg["dataBits"],
                parity=parity_map.get(parity, parity),
                stopbits=stopbits if stopbits is not None else cfg["stopBits"],
                timeout=0.1, write_timeout=1,
                rtscts=flow == "rtscts", xonxoff=flow == "xonxoff", dsrdtr=flow == "dsrdtr")
        except Exception as exc:
            self.error.emit(f"串口打开失败: {exc}")
            return False
        self._port = port_obj
        self._parser = parser
        self.parser_type = selected_parser
        self.text_encoding = text_encoding(selected_parser, selected_config)
        self.slave_device = slave
        if slave is not None:
            slave.begin(self, selected_parser)
        self._thread = SerialReaderThread(port_obj, parser, self)
        self._thread.rawReceived.connect(self._on_raw)
        self._thread.parsedReceived.connect(self._on_parsed)
        self._thread.errorOccurred.connect(self._on_error)
        self._thread.start()
        self.connected.emit(port)
        self.connectionChanged.emit(True)
        return True

    def connect_port(self, port, baudrate=None, **kwargs):
        return self.connect(port, baudrate, **kwargs)

    def disconnect(self):
        if self._thread is None and self._port is None:
            return  # already idle; the hub disconnects every link
        if self._thread:
            self._thread.stop()
            self._thread.deleteLater()
            self._thread = None
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None
        if self.slave_device is not None:
            self.slave_device.end()
            self.slave_device = None
        self.disconnected.emit()
        self.connectionChanged.emit(False)

    def disconnect_port(self):
        self.disconnect()

    def send(self, data):
        """Return success only after the port accepts the entire payload."""
        if not self.is_connected:
            return False
        self.modbus_requests.note_frame(data, self.parser_type)  # before a fast reply can arrive
        try:
            written = self._port.write(data)
            if written != len(data):
                raise OSError(f"串口仅写入 {written}/{len(data)} 字节")
        except Exception as exc:
            self.error.emit(f"发送失败: {exc}")
            return False
        self.dataSent.emit(data)
        return True

    def send_text(self, text, encoding="utf-8"):
        return self.send(text.encode(encoding))

    def _send_reply(self, data):
        """A slave's reply: written like send(), but no read is noted for it."""
        if not self.is_connected:
            return False
        try:
            written = self._port.write(data)
            if written != len(data):
                raise OSError(f"串口仅写入 {written}/{len(data)} 字节")
        except Exception as exc:
            self.error.emit(f"发送失败: {exc}")
            return False
        self.dataSent.emit(bytes(data))
        return True

    @pyqtSlot(bytes)
    def _on_raw(self, data):
        # Events already queued by a stopped reader can arrive after reconnect.
        if self._thread is not None and self.sender() is self._thread:
            self.rawReceived.emit(data)
            if self.slave_device is not None:  # a request the slave answers
                self.slave_device.receive(data, self._send_reply)

    @pyqtSlot(dict)
    def _on_parsed(self, data):
        if self._thread is not None and self.sender() is self._thread:
            self.dataReceived.emit(data)

    @pyqtSlot(str)
    def _on_error(self, message):
        reader = self.sender()
        if reader is not self._thread or reader is None:
            return
        self.error.emit(message)
        # An error observer may already have opened a replacement connection.
        if self._thread is reader:
            self.disconnect()

SerialHandler.DEFAULT_CONFIG = {'baudRate': 115200, 'dataBits': 8, 'parity': 'None', 'stopBits': 1, 'parser': 'line', 'parserConfig': {'separator': ','}}
