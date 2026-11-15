"""Classic S7 addresses and Siemens wire values, independent of Qt and the SDK."""
from dataclasses import dataclass
import ipaddress
import math
import re
import struct


S7_TYPES = ("BOOL", "BYTE", "SINT", "WORD", "INT", "DWORD", "DINT", "REAL")
_FORMATS = {"BYTE": "B", "SINT": "b", "WORD": "H", "INT": "h", "DWORD": "I", "DINT": "i", "REAL": "f"}
_LIMITS = {"BYTE": (0, 255), "SINT": (-128, 127), "WORD": (0, 65535), "INT": (-32768, 32767),
           "DWORD": (0, 4294967295), "DINT": (-2147483648, 2147483647)}
DEFAULT_POINT = {"address": "DB1.DBD4", "dataType": "REAL", "period": 0}
DEFAULT_CONFIG = {"host": "127.0.0.1", "port": 102, "rack": 0, "slot": 1, "connectionType": 1,
                  "period": 500, "timeout": 1000, "autoConnect": False, "autoReconnect": True,
                  "reconnectInterval": 1000}
_AREAS = {"DB": 0x84, "M": 0x83, "I": 0x81, "Q": 0x82}


@dataclass(frozen=True)
class S7Address:
    canonical: str
    area: int
    db: int
    offset: int
    size: int
    bit: int = -1


def parse_s7_address(text, data_type):
    """Parse an absolute byte/bit address and verify its storage width."""
    kind = str(data_type).strip().upper()
    if kind not in S7_TYPES:
        raise ValueError("Unsupported S7 data type: " + str(data_type))
    address = str(text).strip().upper()
    match = re.fullmatch(r"DB(\d+)\.DB([XBWD])(\d+)(?:\.([0-7]))?", address)
    if match:
        db, width, offset, bit = match.groups()
        db = int(db)
        if not 1 <= db <= 65535:
            raise ValueError("S7 DB number must be between 1 and 65535")
        prefix = "DB"
        canonical = f"DB{db}.DB{width}{int(offset)}"
    else:
        match = re.fullmatch(r"([MIQ])([XBWD]?)(\d+)(?:\.([0-7]))?", address)
        if not match:
            raise ValueError("Invalid absolute S7 address: " + str(text))
        prefix, width, offset, bit = match.groups()
        db = 0
        width = width or "X"
        canonical = prefix + ("" if width == "X" else width) + str(int(offset))
    if (width == "X") != (bit is not None):
        raise ValueError("S7 bit addresses require a bit index from 0 to 7")
    size = {"X": 1, "B": 1, "W": 2, "D": 4}[width]
    expected = 1 if kind == "BOOL" else struct.calcsize(_FORMATS[kind])
    if (kind == "BOOL") != (width == "X") or expected != size:
        raise ValueError("S7 address width does not match " + kind)
    offset = int(offset)
    if offset + size > 2097152:
        raise ValueError("S7 address exceeds the 24-bit wire address range")
    if bit is not None:
        canonical += "." + str(int(bit))
    return S7Address(canonical, _AREAS[prefix], db, offset, size, int(bit) if bit is not None else -1)


def encode_s7(value, data_type):
    kind = str(data_type).strip().upper()
    if kind == "BOOL":
        if isinstance(value, str):
            value = value.strip().lower()
            if value in ("true", "1"):
                return b"\x01"
            if value in ("false", "0"):
                return b"\x00"
        elif value is True or value == 1:
            return b"\x01"
        elif value is False or value == 0:
            return b"\x00"
        raise ValueError("S7 BOOL requires true, false, 0 or 1")
    if kind not in _FORMATS:
        raise ValueError("Unsupported S7 data type: " + str(data_type))
    if isinstance(value, bool):
        raise ValueError("S7 numeric values cannot be booleans")
    if kind != "REAL" and isinstance(value, str) and not re.fullmatch(r"[+-]?[0-9]+", value.strip()):
        raise ValueError("S7 integer text must be a decimal integer")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Invalid S7 numeric value") from error
    if not math.isfinite(number):
        raise ValueError("S7 values must be finite")
    if kind != "REAL":
        low, high = _LIMITS[kind]
        if not number.is_integer() or not low <= number <= high:
            raise ValueError("S7 value is outside the range of " + kind)
        number = int(number)
    try:
        data = struct.pack(">" + _FORMATS[kind], number)
        if kind == "REAL" and not math.isfinite(struct.unpack(">f", data)[0]):
            raise ValueError("S7 REAL is outside the finite float32 range")
        return data
    except (struct.error, OverflowError) as error:
        raise ValueError("S7 value is outside the range of " + kind) from error


def decode_s7(data, data_type, bit=0):
    kind = str(data_type).strip().upper()
    if kind == "BOOL":
        return bool(data[0] & (1 << bit))
    return struct.unpack(">" + _FORMATS[kind], data)[0]


def _integer(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid S7 " + label)
    if int(value) != value or not low <= value <= high:
        raise ValueError("Invalid S7 " + label)
    return int(value)


def s7_point(value=None):
    if value is not None and not isinstance(value, dict):
        raise ValueError("S7 point must be an object")
    point = {**DEFAULT_POINT, **(value or {})}
    kind = str(point["dataType"]).strip().upper()
    address = parse_s7_address(point["address"], kind)
    return {"address": address.canonical, "dataType": kind,
            "period": _integer(point["period"], 0, 60000, "period")}


def s7_config(value):
    config = {key: value.get(key, default) for key, default in DEFAULT_CONFIG.items()}
    config["host"] = str(config["host"]).strip()
    try:
        ipaddress.IPv4Address(config["host"])
    except ipaddress.AddressValueError as error:
        raise ValueError("S7 host must be an IPv4 address") from error
    for key, low, high in (("port", 1, 65535), ("rack", 0, 7), ("slot", 0, 31),
                            ("connectionType", 1, 3), ("period", 1, 60000),
                            ("timeout", 1, 60000), ("reconnectInterval", 1, 60000)):
        config[key] = _integer(config[key], low, high, key)
    for key in ("autoConnect", "autoReconnect"):
        if not isinstance(config[key], bool):
            raise ValueError("S7 " + key + " must be a boolean")
    return config


def s7_sample_value(sample, source_id, point):
    """Select a typed sample without falling back to any other connection."""
    if sample.get("quality") != "good" or sample.get("sourceCardId") != source_id:
        return None
    requested = s7_point(point)
    if (sample.get("address"), sample.get("dataType")) != (requested["address"], requested["dataType"]):
        return None
    return sample.get("value")


def project_uses_s7(widgets):
    for item in widgets:
        props = item.get("properties", {})
        if (item.get("type") == "S7ConfigCard" or (item.get("binding") or {}).get("parseMode") == "S7"
                or props.get("commandMode") == "S7"
                or any(key.endswith("_parseMode") and value == "S7" for key, value in props.items())):
            return True
        if project_uses_s7(item.get("children", [])):
            return True
    return False
