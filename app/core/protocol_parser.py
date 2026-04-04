# coding: utf-8
"""Data frame parsers for serial communication."""
import json
import re
from typing import Optional, Dict, Any


class BaseParser:
    """Base class for protocol parsers."""

    def feed(self, data: bytes) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class LineParser(BaseParser):
    """Parse newline-terminated ASCII lines.

    Supports formats:
      - CSV:  "key1,val1,key2,val2\\n"  or  "val1,val2,val3\\n" (auto-indexed)
      - KEY=VALUE: "temp=25.3,humidity=60\\n"
      - JSON per line: '{"temp": 25.3}\\n'
    """

    def __init__(self, separator: str = ","):
        self._buf = b""
        self._sep = separator

    def feed(self, data: bytes) -> Optional[Dict[str, Any]]:
        self._buf += data
        # Normalize literal escape sequences (\r\n, \n) to real newline bytes
        self._buf = self._buf.replace(b"\\r\\n", b"\n").replace(b"\\n", b"\n")
        results = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            parsed = self._parse_line(text)
            if parsed:
                results.append(parsed)
        # Fallback: no newline found but buffer looks like a complete message
        if not results and self._buf:
            text = self._buf.decode("utf-8", errors="replace").strip()
            if text and ("=" in text or text.startswith("{")):
                parsed = self._parse_line(text)
                if parsed:
                    results.append(parsed)
                    self._buf = b""
        return results[-1] if results else None

    def _parse_line(self, text: str) -> Optional[Dict[str, Any]]:
        # try JSON
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

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
                 fields: list = None):
        self._buf = b""
        self._header = header
        self._footer = footer
        self._fields = fields or []

    def feed(self, data: bytes) -> Optional[Dict[str, Any]]:
        self._buf += data
        results = []

        while True:
            hdr_idx = self._buf.find(self._header)
            if hdr_idx < 0:
                break
            ftr_idx = self._buf.find(self._footer, hdr_idx + len(self._header))
            if ftr_idx < 0:
                break

            frame = self._buf[hdr_idx:ftr_idx + len(self._footer)]
            self._buf = self._buf[ftr_idx + len(self._footer):]

            payload = frame[len(self._header):-len(self._footer)]
            parsed = self._parse_payload(payload)
            if parsed:
                results.append(parsed)

        return results[-1] if results else None

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

    def feed(self, data: bytes) -> Optional[Dict[str, Any]]:
        self._buf += data
        results = []

        while len(self._buf) >= 5:
            slave = self._buf[0]
            fc = self._buf[1]

            if fc in (0x01, 0x02, 0x03, 0x04):
                if len(self._buf) < 3:
                    break
                byte_count = self._buf[2]
                frame_len = 3 + byte_count + 2
                if len(self._buf) < frame_len:
                    break
                frame = self._buf[:frame_len]
                if modbus_crc(frame[:-2]) != frame[-2:]:
                    self._buf = self._buf[1:]
                    continue
                self._buf = self._buf[frame_len:]
                parsed = self._parse_read_response(slave, fc, frame[3:3 + byte_count])
                if parsed:
                    results.append(parsed)

            elif fc in (0x05, 0x06, 0x0F, 0x10):
                frame_len = 8
                if len(self._buf) < frame_len:
                    break
                frame = self._buf[:frame_len]
                if modbus_crc(frame[:-2]) != frame[-2:]:
                    self._buf = self._buf[1:]
                    continue
                self._buf = self._buf[frame_len:]
                addr = int.from_bytes(frame[2:4], "big")
                val = int.from_bytes(frame[4:6], "big")
                results.append({"slave": slave, "fc": fc,
                                "address": addr, "value": val})

            elif fc >= 0x80:
                frame_len = 5
                if len(self._buf) < frame_len:
                    break
                frame = self._buf[:frame_len]
                self._buf = self._buf[frame_len:]
                results.append({"slave": slave, "fc": fc,
                                "error": frame[2]})
            else:
                self._buf = self._buf[1:]

        return results[-1] if results else None

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
    return LineParser()
