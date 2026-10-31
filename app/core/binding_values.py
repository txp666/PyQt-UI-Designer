"""Conversions shared by live bindings and standalone exported applications."""
import math
import struct


def binding_integer(value):
    """Accept integer-compatible values that fit Qt's signed 32-bit API."""
    number = int(value)
    if not -(2 ** 31) <= number < 2 ** 31:
        raise OverflowError("绑定整数超出 Qt 支持的范围")
    return number


def binding_float(value):
    """Reject NaN/infinity before passing a sample to a numeric widget."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("绑定数值必须是有限数")
    return number


def binding_register(value):
    """Modbus register payloads must be unsigned 16-bit integers."""
    if not isinstance(value, int) or not 0 <= value <= 65535:
        raise ValueError("Modbus 寄存器值必须是 0 到 65535 的整数")
    return value


# Where a Modbus binding or chart curve reads: a register table, whose registers a reply names by
# address (hr100), from the request it answers. 保持寄存器 when a binding names none.
MODBUS_AREAS = {"保持寄存器": "hr", "输入寄存器": "ir", "线圈": "co", "离散输入": "di"}
DEFAULT_MODBUS_AREA = "保持寄存器"
# The registers a value of each type takes; coils and discrete inputs are one bit each.
MODBUS_REGISTERS = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}


def modbus_need(area, address, data_type="uint16", slave_filter=-1, period=0):
    """What a Modbus binding or chart curve reads, for the Modbus poller:
    ``(slave, table, address, count, period)``, or None for an area that is not a register table.
    A slave of 0 or less stands for the poller's default slave, a period of 0 for its default period."""
    table = MODBUS_AREAS.get(area)
    if table is None:
        return None
    count = 1 if table in ("co", "di") else MODBUS_REGISTERS.get(data_type, 1)
    return int(slave_filter), table, int(address), count, max(0, min(60000, int(period)))


def modbus_value(data, address, data_type="uint16", reg_order="大端(AB CD)",
                 fc_filter=-1, slave_filter=-1, area=DEFAULT_MODBUS_AREA):
    """One value from a parsed Modbus response, or None when the response does not hold it.

    The value is the register (or coil, or discrete input) at ``address`` of the area's table,
    named by address in a reply to a read this program sent (hr100, co3). 32-bit types take the
    register at the address and the next one, which must be in the same response. Coils and
    discrete inputs are 0 or 1 whatever the data type.
    """
    if slave_filter >= 0 and data.get("slave") != slave_filter:
        return None
    fc = data.get("fc", 0)
    if fc_filter >= 0 and fc != fc_filter:
        return None
    table = MODBUS_AREAS.get(area)
    if table is None:
        return None
    if table in ("co", "di"):
        return data.get(f"{table}{address}")
    r0 = data.get(f"{table}{address}")
    if r0 is None:
        return None
    r0 = binding_register(r0)
    if data_type == "uint16":
        return r0
    if data_type == "int16":
        return r0 - 65536 if r0 > 32767 else r0
    r1 = data.get(f"{table}{address + 1}")
    if r1 is None:
        return None
    r1 = binding_register(r1)
    high, low = (r0, r1) if reg_order == "大端(AB CD)" else (r1, r0)
    raw = high.to_bytes(2, "big") + low.to_bytes(2, "big")
    if data_type == "uint32":
        return int.from_bytes(raw, "big")
    if data_type == "int32":
        return int.from_bytes(raw, "big", signed=True)
    if data_type == "float32":
        return struct.unpack(">f", raw)[0]
    return r0


def binding_boolean(value):
    """Read explicit boolean tokens or finite numbers; reject unknown text."""
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in ("true", "on", "yes"):
            return True
        if token in ("false", "off", "no"):
            return False
    return bool(binding_float(value))


def binding_decimals(value, places="自动"):
    """A number shown with a fixed count of decimal places; anything else (text, flags, NaN) as it came."""
    if places in ("自动", "", None) or isinstance(value, bool):
        if isinstance(value, float) and math.isfinite(value):
            # 15 significant digits: the noise of binary arithmetic (267 * 0.1 = 26.700000000000003)
            # goes, every digit a double really holds stays.
            return float(f"{value:.15g}")
        return value
    try:
        number = float(value)
        places = int(places)
    except (TypeError, ValueError, OverflowError):
        return value
    if not math.isfinite(number):
        return value
    return f"{number:.{places}f}"


def binding_led(value, on_value="1", off_value="0"):
    """Preserve custom LED states before falling back to boolean conversion."""
    text = str(value).strip()
    if text == on_value:
        return True
    if text == off_value:
        return False
    try:
        return binding_float(value) == binding_float(on_value)
    except (TypeError, ValueError, OverflowError):
        return binding_boolean(value)
