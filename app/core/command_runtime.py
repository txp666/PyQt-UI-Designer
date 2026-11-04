"""Command encoders shared by preview and standalone applications."""
import math
import struct

from .modbus_master import (  # noqa: F401  (_transaction: the MBAP counter, for callers of this module)
    _transaction, modbus_dispatch, modbus_frame as _modbus_frame, next_modbus_transaction,
)
from .modbus_slave import AREA_TABLES
from .i18n import tr


def _command_hex(text):
    """Accept whitespace and a leading half-byte, but never drop invalid fields."""
    compact = "".join(str(text).split())
    if len(compact) % 2:
        compact = "0" + compact
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError(tr("HEX 格式错误，请检查内容、帧头和帧尾")) from exc


def command_hex_frame(command, header="", tail=""):
    return _command_hex(header) + _command_hex(command) + _command_hex(tail)


def command_packed_frame(value, fmt, cast=int, template="{value}", header="", tail=""):
    try:
        number = cast(value)
        if isinstance(number, float) and not math.isfinite(number):
            raise ValueError("non-finite value")
        payload = struct.pack(fmt, number)
    except (TypeError, ValueError, OverflowError, struct.error) as exc:
        raise ValueError(tr("数值无效或超出数据类型范围")) from exc
    return command_hex_frame(template.replace("{value}", payload.hex()), header, tail)


# Function codes by the names the designer shows, for widgets and exports.
MODBUS_FUNCTIONS = {
    "01 读线圈": 0x01, "02 读离散输入": 0x02,  # i18n: value
    "03 读保持寄存器": 0x03, "04 读输入寄存器": 0x04,  # i18n: value
    "05 写单线圈": 0x05, "06 写单寄存器": 0x06, "16 写多个寄存器": 0x10,  # i18n: value
}
MODBUS_DATA_TYPES = ("uint16", "int16", "uint32", "int32", "float32")
MODBUS_ORDERS = ("大端(AB CD)", "小端(CD AB)")  # i18n: value
_REGISTER_FORMATS = {"uint16": "H", "int16": "h", "uint32": "I", "int32": "i", "float32": "f"}


def modbus_registers(value, data_type="uint16", reg_order=MODBUS_ORDERS[0]):
    """A value as the 16-bit registers that hold it: one for 16-bit types, two for 32-bit ones."""
    fmt = _REGISTER_FORMATS.get(data_type)
    if fmt is None:
        raise ValueError(tr("未知的 Modbus 数据类型: %1", data_type))
    try:
        number = float(value) if fmt == "f" else int(value)
        if fmt == "f" and not math.isfinite(number):
            raise ValueError("non-finite value")
        raw = struct.pack(">" + fmt, number)
    except (TypeError, ValueError, OverflowError, struct.error) as exc:
        raise ValueError(tr("Modbus 值无效或超出 %1 的范围", data_type)) from exc
    registers = [int.from_bytes(raw[i:i + 2], "big") for i in range(0, len(raw), 2)]
    if reg_order != MODBUS_ORDERS[0]:
        registers.reverse()
    return tuple(registers)


def modbus_request(slave, func, address, value, data_type="uint16", reg_order=MODBUS_ORDERS[0]):
    """Validate a Modbus request and return its integer fields.

    The value is the count for reads and the coil or register value for FC 05/06 (FC 06
    also takes an int16); for FC 16 it becomes the registers holding the typed value.
    """
    try:
        slave, func, address = (int(item) for item in (slave, func, address))
        if func not in (0x06, 0x10):
            value = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(tr("Modbus 地址和值必须是整数")) from exc
    if not 1 <= slave <= 247 or not 0 <= address <= 65535:
        raise ValueError(tr("Modbus 从站地址或寄存器地址超出范围"))
    if func in (0x06, 0x10):
        if func == 0x06 and data_type not in ("uint16", "int16"):
            raise ValueError(tr("32 位数据占两个寄存器，请用 16 写多个寄存器"))
        registers = modbus_registers(value, data_type, reg_order)
        if address + len(registers) > 65536:
            raise ValueError(tr("Modbus 从站地址或寄存器地址超出范围"))
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
        raise ValueError(tr("Modbus 值或读取数量超出功能码允许范围"))
    return slave, func, address, value


def command_modbus_frame(slave, func, address, value, data_type="uint16", reg_order=MODBUS_ORDERS[0]):
    """A validated Modbus RTU request frame (CRC16 appended)."""
    return _modbus_frame(modbus_request(slave, func, address, value, data_type, reg_order))


def command_modbus_tcp_frame(slave, func, address, value, transaction=None,
                             data_type="uint16", reg_order=MODBUS_ORDERS[0]):
    """A validated Modbus TCP request ADU (MBAP header, no CRC)."""
    request = modbus_request(slave, func, address, value, data_type, reg_order)
    if transaction is None:
        transaction = next_modbus_transaction()
    return _modbus_frame(request, transaction)


def send_modbus_command(hub, slave, func, address, value, data_type="uint16", reg_order=MODBUS_ORDERS[0]):
    """Validate once, then send the request over every connected link, framed for that link.

    A link parsing Modbus TCP gets an MBAP frame, one parsing Modbus ASCII an ASCII frame,
    every other link an RTU frame; a link answering as a Modbus slave gets none. A link that parses Modbus
    queues the request in its
    ModbusMaster ahead of any polling reads, with a 1000 ms timeout, so it never collides
    with a read on the wire; the others are written at once. Returns the frames that were
    accepted (queued, or written); an invalid request raises before anything is sent.
    """
    request = modbus_request(slave, func, address, value, data_type, reg_order)
    return [frame for frame, _master in modbus_dispatch(hub, request, 1000, "write")]


# -- the data tables of the link cards in the 从站 role (modbus_slave.py, slave_runtime.py) --------------

_TYPE_RANGES = {"uint16": (0, 0xFFFF), "int16": (-0x8000, 0x7FFF), "uint32": (0, 0xFFFFFFFF),
                "int32": (-0x80000000, 0x7FFFFFFF), "float32": (-3.4028234663852886e38, 3.4028234663852886e38)}


def slave_devices(widgets):
    """The slaves of the link cards in the slave role among ``widgets``, in their order (the document's)."""
    return [device for device in (getattr(widget, "slave_device", None) for widget in widgets)
            if device is not None]


def slave_control_write(devices, area, address, value, data_type="uint16", reg_order=MODBUS_ORDERS[0]):
    """A user's change of a control with a Modbus binding, written into every slave's data table at the
    binding's area and address: 1 or 0 for a coil or discrete input, the registers of the value packed as its
    type (and clamped to the type's range) for registers, as a Modbus write command packs them. A table that
    has not every address in its area is left alone."""
    table = AREA_TABLES.get(area)
    if table is None or not devices:
        return
    if table in ("co", "di"):
        values = [1 if value else 0]
    else:
        low, high = _TYPE_RANGES.get(data_type, _TYPE_RANGES["uint16"])
        number = float(value) if data_type == "float32" else int(value)
        try:
            values = list(modbus_registers(min(max(number, low), high), data_type, reg_order))
        except ValueError:
            return
    for device in devices:
        device.write(table, int(address), values)


def slave_command_write(devices, request):
    """A validated Modbus command (modbus_request) carried out on every slave's data table, whatever slave
    it names: 05 writes 1 for a value that is not 0, 06 and 16 the registers the command packs; a read does
    nothing. True when a table took it."""
    _slave, func, address, value = request
    if func == 0x05:
        table, values = "co", [1 if value else 0]
    elif func == 0x06:
        table, values = "hr", [value]
    elif func == 0x10:
        table, values = "hr", list(value)
    else:
        return False
    return any([device.write(table, address, values) for device in devices])
