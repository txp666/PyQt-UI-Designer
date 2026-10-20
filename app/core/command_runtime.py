"""Command encoders shared by preview and standalone applications."""
import math
import struct

def _command_hex(text):
    """Accept whitespace and a leading half-byte, but never drop invalid fields."""
    compact = "".join(str(text).split())
    if len(compact) % 2:
        compact = "0" + compact
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("HEX 格式错误，请检查内容、帧头和帧尾") from exc


def command_hex_frame(command, header="", tail=""):
    return _command_hex(header) + _command_hex(command) + _command_hex(tail)


def command_packed_frame(value, fmt, cast=int, template="{value}", header="", tail=""):
    try:
        number = cast(value)
        if isinstance(number, float) and not math.isfinite(number):
            raise ValueError("non-finite value")
        payload = struct.pack(fmt, number)
    except (TypeError, ValueError, OverflowError, struct.error) as exc:
        raise ValueError("数值无效或超出数据类型范围") from exc
    return command_hex_frame(template.replace("{value}", payload.hex()), header, tail)


def command_modbus_frame(slave, func, address, value):
    try:
        slave, func, address, value = (int(item) for item in (slave, func, address, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Modbus 地址和值必须是整数") from exc
    if not 1 <= slave <= 247 or not 0 <= address <= 65535:
        raise ValueError("Modbus 从站地址或寄存器地址超出范围")
    if func in (1, 2):
        valid = 1 <= value <= 2000
    elif func in (3, 4):
        valid = 1 <= value <= 125
    elif func == 5:
        valid = value in (0, 0xFF00)
    elif func == 6:
        valid = 0 <= value <= 65535
    else:
        valid = False
    if not valid:
        raise ValueError("Modbus 值或读取数量超出功能码允许范围")
    from .protocol_parser import build_modbus_frame
    return build_modbus_frame(slave, func, address, value, value)
