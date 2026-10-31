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


# Function codes by the names the designer shows, for widgets, the Modbus card and exports.
MODBUS_FUNCTIONS = {
    "01 读线圈": 0x01, "02 读离散输入": 0x02,
    "03 读保持寄存器": 0x03, "04 读输入寄存器": 0x04,
    "05 写单线圈": 0x05, "06 写单寄存器": 0x06, "16 写多个寄存器": 0x10,
}
MODBUS_DATA_TYPES = ("uint16", "int16", "uint32", "int32", "float32")
MODBUS_ORDERS = ("大端(AB CD)", "小端(CD AB)")
_REGISTER_FORMATS = {"uint16": "H", "int16": "h", "uint32": "I", "int32": "i", "float32": "f"}


def modbus_registers(value, data_type="uint16", reg_order="大端(AB CD)"):
    """A value as the 16-bit registers that hold it: one for 16-bit types, two for 32-bit ones."""
    fmt = _REGISTER_FORMATS.get(data_type)
    if fmt is None:
        raise ValueError(f"未知的 Modbus 数据类型: {data_type}")
    try:
        number = float(value) if fmt == "f" else int(value)
        if fmt == "f" and not math.isfinite(number):
            raise ValueError("non-finite value")
        raw = struct.pack(">" + fmt, number)
    except (TypeError, ValueError, OverflowError, struct.error) as exc:
        raise ValueError(f"Modbus 值无效或超出 {data_type} 的范围") from exc
    registers = [int.from_bytes(raw[i:i + 2], "big") for i in range(0, len(raw), 2)]
    if reg_order != MODBUS_ORDERS[0]:
        registers.reverse()
    return tuple(registers)


def modbus_request(slave, func, address, value, data_type="uint16", reg_order="大端(AB CD)"):
    """Validate a Modbus request and return its integer fields.

    The value is the count for reads and the coil or register value for FC 05/06 (FC 06
    also takes an int16); for FC 16 it becomes the registers holding the typed value.
    """
    try:
        slave, func, address = (int(item) for item in (slave, func, address))
        if func not in (0x06, 0x10):
            value = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Modbus 地址和值必须是整数") from exc
    if not 1 <= slave <= 247 or not 0 <= address <= 65535:
        raise ValueError("Modbus 从站地址或寄存器地址超出范围")
    if func in (0x06, 0x10):
        if func == 0x06 and data_type not in ("uint16", "int16"):
            raise ValueError("32 位数据占两个寄存器，请用 16 写多个寄存器")
        registers = modbus_registers(value, data_type, reg_order)
        if address + len(registers) > 65536:
            raise ValueError("Modbus 从站地址或寄存器地址超出范围")
        return slave, func, address, registers[0] if func == 0x06 else registers
    if func in (1, 2):
        valid = 1 <= value <= 2000
    elif func in (3, 4):
        valid = 1 <= value <= 125
    elif func == 5:
        valid = value in (0, 0xFF00)
    else:
        valid = False
    if not valid:
        raise ValueError("Modbus 值或读取数量超出功能码允许范围")
    return slave, func, address, value


def _modbus_frame(request, transaction=None, ascii_frame=False):
    """A validated request as an RTU frame, as a Modbus TCP ADU given its transaction id, or
    as a Modbus ASCII frame."""
    slave, func, address, value = request
    registers, value = (value, 0) if func == 0x10 else ((), value)
    if transaction is not None:
        from .protocol_parser import build_modbus_tcp_frame
        return build_modbus_tcp_frame(slave, func, address, value, value, transaction, registers)
    if ascii_frame:
        from .protocol_parser import build_modbus_ascii_frame
        return build_modbus_ascii_frame(slave, func, address, value, value, registers)
    from .protocol_parser import build_modbus_frame
    return build_modbus_frame(slave, func, address, value, value, registers)


def command_modbus_frame(slave, func, address, value, data_type="uint16", reg_order="大端(AB CD)"):
    """A validated Modbus RTU request frame (CRC16 appended)."""
    return _modbus_frame(modbus_request(slave, func, address, value, data_type, reg_order))


_transaction = [0]


def next_modbus_transaction():
    """Successive MBAP transaction identifiers, wrapping at 16 bits."""
    _transaction[0] = (_transaction[0] + 1) & 0xFFFF
    return _transaction[0]


def command_modbus_tcp_frame(slave, func, address, value, transaction=None,
                             data_type="uint16", reg_order="大端(AB CD)"):
    """A validated Modbus TCP request ADU (MBAP header, no CRC)."""
    request = modbus_request(slave, func, address, value, data_type, reg_order)
    if transaction is None:
        transaction = next_modbus_transaction()
    return _modbus_frame(request, transaction)


def send_modbus_command(hub, slave, func, address, value, data_type="uint16", reg_order="大端(AB CD)"):
    """Validate once, then send the request over every connected link, framed for that link.

    A link parsing Modbus TCP gets an MBAP frame, one parsing Modbus ASCII an ASCII frame,
    every other link an RTU frame. Returns the frames that were accepted; an invalid request
    raises before anything is sent.
    """
    request = modbus_request(slave, func, address, value, data_type, reg_order)
    links = getattr(hub, "connected_links", None)
    if links is None:  # a single link rather than a hub
        links = [hub] if hub.is_connected else []
    frames = []
    for link in links:
        parser_type = getattr(link, "parser_type", "")
        if parser_type == "modbus_tcp":
            frames.append((link, _modbus_frame(request, next_modbus_transaction())))
        else:
            frames.append((link, _modbus_frame(request, ascii_frame=parser_type == "modbus_ascii")))
    return [frame for link, frame in frames if link.send(frame)]
