# coding: utf-8
"""Data frame parsers for serial communication."""
import json
from typing import Optional, Dict, Any, List


class BaseParser:
    """Incremental parsers return every complete message, in arrival order."""

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        raise NotImplementedError


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


class LineParser(BaseParser):
    """Parse newline-terminated ASCII lines.

    Supports formats:
      - CSV:  "key1,val1,key2,val2\\n"  or  "val1,val2,val3\\n" (auto-indexed)
      - KEY=VALUE: "temp=25.3,humidity=60\\n"
      - JSON per line: '{"temp": 25.3}\\n'
    """

    def __init__(self, separator: str = ",", max_buffer: int = 65536):
        if not separator:
            raise ValueError("行分隔符不能为空")
        self._buf = b""
        self._sep = separator
        self._max_buffer = max_buffer
        self._discarding = False

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        # Only actual LF terminates a record. JSON may contain escaped \n.
        results = []
        parts = data.split(b"\n")
        for index, part in enumerate(parts):
            complete = index < len(parts) - 1
            if not self._discarding:
                if len(self._buf) + len(part) > self._max_buffer:
                    self._buf = b""
                    self._discarding = True
                else:
                    self._buf += part
            if complete:
                if not self._discarding:
                    text = self._buf.decode("utf-8", errors="replace").strip()
                    if text:
                        parsed = self._parse_line(text)
                        if parsed:
                            results.append(parsed)
                self._buf = b""
                self._discarding = False
        return results

    def _parse_line(self, text: str) -> Optional[Dict[str, Any]]:
        # try JSON
        if text.startswith("{"):
            try:
                value = json.loads(text)
                return value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                return None

        parts = [p.strip() for p in text.split(self._sep)]

        # KEY=VALUE format
        if any("=" in p for p in parts):
            result = {}
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
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


class HexFrameParser(BaseParser):
    """Parse fixed-header hex frames.

    Expected config:
      header: bytes (e.g. b'\\xAA\\x55')
      footer: bytes (e.g. b'\\x55\\xAA')
      fields: list of (name, offset, length, type)
    """

    def __init__(self, header: bytes = b"\xAA\x55", footer: bytes = b"\x55\xAA",
                 fields: list = None, max_buffer: int = 65536):
        if not header or not footer:
            raise ValueError("HEX 帧头和帧尾不能为空")
        self._buf = b""
        self._header = header
        self._footer = footer
        self._fields = fields or []
        self._max_buffer = max_buffer
        sizes = {"uint8": 1, "int8": 1, "uint16": 2, "int16": 2, "float32": 4}
        for name, offset, length, dtype in self._fields:
            if offset < 0 or length <= 0 or (dtype in sizes and length != sizes[dtype]):
                raise ValueError(f"无效 HEX 字段: {name}")

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        self._buf += data
        results = []
        while self._buf:
            start = self._buf.find(self._header)
            if start < 0:
                self._buf = self._buf[-(len(self._header) - 1):] if len(self._header) > 1 else b""
                break
            self._buf = self._buf[start:]
            end = self._buf.find(self._footer, len(self._header))
            if end < 0:
                if len(self._buf) > self._max_buffer:
                    self._buf = self._buf[1:]
                    continue
                break
            frame_end = end + len(self._footer)
            if frame_end <= self._max_buffer:
                parsed = self._parse_payload(self._buf[len(self._header):end])
                if parsed:
                    results.append(parsed)
            self._buf = self._buf[frame_end:]
        return results

    def _parse_payload(self, payload: bytes) -> Dict[str, Any]:
        result = {}
        for name, offset, length, dtype in self._fields:
            if offset + length > len(payload):
                continue
            raw = payload[offset:offset + length]
            if dtype == "uint8":
                result[name] = raw[0]
            elif dtype == "int8":
                v = raw[0]
                result[name] = v - 256 if v > 127 else v
            elif dtype == "uint16":
                result[name] = int.from_bytes(raw, "big")
            elif dtype == "int16":
                result[name] = int.from_bytes(raw, "big", signed=True)
            elif dtype == "float32":
                import struct
                result[name] = struct.unpack(">f", raw)[0]
            else:
                result[name] = raw.hex()
        return result


class ModbusRTUParser(BaseParser):
    """Parse Modbus RTU response frames.

    Extracts register values from FC 01-04 responses and maps them
    to named fields: reg0, reg1, … (or custom field names).
    """

    def __init__(self, fields: list = None):
        self._buf = b""
        self._fields = fields or []

    @staticmethod
    def _frame_length(buf):
        if len(buf) < 3:
            return None
        if not 1 <= buf[0] <= 247:
            return 0
        fc = buf[1]
        if fc in (1, 2, 3, 4):
            count = buf[2]
            if not 1 <= count <= 250 or (fc in (3, 4) and count % 2):
                return 0
            return count + 5
        if fc in (5, 6, 15, 16):
            return 8
        if fc in (0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x8F, 0x90):
            return 5
        return 0

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
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
            slave, fc = frame[:2]
            if fc in (1, 2, 3, 4):
                results.append(self._parse_read_response(slave, fc, frame[3:-2]))
            elif fc >= 0x80:
                results.append({"slave": slave, "fc": fc, "error": frame[2]})
            else:
                results.append({"slave": slave, "fc": fc,
                                "address": int.from_bytes(frame[2:4], "big"),
                                "value": int.from_bytes(frame[4:6], "big")})
        return results

    def _parse_read_response(self, slave: int, fc: int,
                             payload: bytes) -> Dict[str, Any]:
        result: Dict[str, Any] = {"slave": slave, "fc": fc}
        if fc in (0x03, 0x04):
            regs = []
            for i in range(0, len(payload), 2):
                if i + 1 < len(payload):
                    regs.append(int.from_bytes(payload[i:i + 2], "big"))
            for idx, val in enumerate(regs):
                name = self._fields[idx] if idx < len(self._fields) else f"reg{idx}"
                result[name] = val
        elif fc in (0x01, 0x02):
            bits = []
            for b in payload:
                for bit_i in range(8):
                    bits.append((b >> bit_i) & 1)
            for idx, val in enumerate(bits):
                name = self._fields[idx] if idx < len(self._fields) else f"coil{idx}"
                result[name] = val
        return result


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
                       value: int = 0, count: int = 1) -> bytes:
    """Build a Modbus RTU request frame.

    Supports FC 01-06, 0x0F, 0x10.
    For FC 01-04: count = number of registers/coils to read.
    For FC 05: value = 0xFF00 (ON) or 0x0000 (OFF).
    For FC 06: value = register value to write.
    """
    pdu = bytes([slave, func])
    pdu += address.to_bytes(2, "big")

    if func in (0x01, 0x02, 0x03, 0x04):
        pdu += count.to_bytes(2, "big")
    elif func in (0x05, 0x06):
        pdu += value.to_bytes(2, "big")
    else:
        pdu += count.to_bytes(2, "big")

    return pdu + modbus_crc(pdu)


def create_parser(parser_type: str, config: dict = None) -> BaseParser:
    config = config or {}
    if parser_type == "line":
        return LineParser(separator=config.get("separator", ","))
    elif parser_type == "hex":
        return HexFrameParser(
            header=bytes.fromhex(config.get("header", "AA55")),
            footer=bytes.fromhex(config.get("footer", "55AA")),
            fields=config.get("fields", []),
        )
    elif parser_type == "modbus":
        return ModbusRTUParser(fields=config.get("fields", []))
    raise ValueError(f"未知解析模式: {parser_type}")
