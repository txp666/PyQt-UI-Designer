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


def modbus_request(slave, func, address, value):
    """Validate a Modbus request and return its integer fields."""
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
    return slave, func, address, value


def command_modbus_frame(slave, func, address, value):
    """A validated Modbus RTU request frame (CRC16 appended)."""
    slave, func, address, value = modbus_request(slave, func, address, value)
    from .protocol_parser import build_modbus_frame
    return build_modbus_frame(slave, func, address, value, value)


_transaction = [0]


def next_modbus_transaction():
    """Successive MBAP transaction identifiers, wrapping at 16 bits."""
    _transaction[0] = (_transaction[0] + 1) & 0xFFFF
    return _transaction[0]


def command_modbus_tcp_frame(slave, func, address, value, transaction=None):
    """A validated Modbus TCP request ADU (MBAP header, no CRC)."""
    slave, func, address, value = modbus_request(slave, func, address, value)
    from .protocol_parser import build_modbus_tcp_frame
    if transaction is None:
        transaction = next_modbus_transaction()
    return build_modbus_tcp_frame(slave, func, address, value, value, transaction)


def send_modbus_command(hub, slave, func, address, value):
    """Validate once, then send the request over every connected link, framed for that link.

    A link parsing Modbus TCP gets an MBAP frame, every other link an RTU frame. Returns
    the frames that were accepted; an invalid request raises before anything is sent.
    """
    request = modbus_request(slave, func, address, value)
    links = getattr(hub, "connected_links", None)
    if links is None:  # a single link rather than a hub
        links = [hub] if hub.is_connected else []
    frames = []
    for link in links:
        if getattr(link, "parser_type", "") == "modbus_tcp":
            frames.append((link, command_modbus_tcp_frame(*request)))
        else:
            frames.append((link, command_modbus_frame(*request)))
    return [frame for link, frame in frames if link.send(frame)]
