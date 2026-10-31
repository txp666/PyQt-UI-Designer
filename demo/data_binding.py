# coding: utf-8
"""Auto-generated data binding."""
import struct
from PyQt5.QtCore import QSignalBlocker
from ui import RealtimeLineChart

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


# Where a Modbus binding reads: 响应内序号 counts registers within one response (reg0, coil0),
# the tables name them by register address (hr100), which the request for each response gives.
MODBUS_AREAS = {"响应内序号": None, "保持寄存器": "hr", "输入寄存器": "ir",
                "线圈": "co", "离散输入": "di"}
# The registers a value of each type takes; coils and discrete inputs are one bit each.
MODBUS_REGISTERS = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}


def modbus_need(area, address, data_type="uint16", slave_filter=-1, period=0):
    """What a Modbus binding or chart curve reads, for the Modbus card's 自动 polling:
    ``(slave, table, address, count, period)``, or None for 响应内序号, which takes whatever
    response comes. A slave of 0 or less stands for the card's 默认从站, a period of 0 for
    its 轮询ms."""
    table = MODBUS_AREAS.get(area)
    if table is None:
        return None
    count = 1 if table in ("co", "di") else MODBUS_REGISTERS.get(data_type, 1)
    return int(slave_filter), table, int(address), count, max(0, min(60000, int(period)))


def modbus_value(data, index, data_type="uint16", reg_order="大端(AB CD)",
                 fc_filter=-1, slave_filter=-1, area="响应内序号"):
    """One value from a parsed Modbus response, or None when the response does not hold it.

    32-bit types take the register at index and the next one, which must be in the same
    response. Coils and discrete inputs are 0 or 1 whatever the data type.
    """
    if slave_filter >= 0 and data.get("slave") != slave_filter:
        return None
    fc = data.get("fc", 0)
    if fc_filter >= 0 and fc != fc_filter:
        return None
    table = MODBUS_AREAS.get(area)
    if table is None:
        if fc in (0x01, 0x02):
            return data.get(f"coil{index}")
        table = "reg"
    elif table in ("co", "di"):
        return data.get(f"{table}{index}")
    r0 = data.get(f"{table}{index}")
    if r0 is None:
        return None
    r0 = binding_register(r0)
    if data_type == "uint16":
        return r0
    if data_type == "int16":
        return r0 - 65536 if r0 > 32767 else r0
    r1 = data.get(f"{table}{index + 1}")
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

"""Explicit Qt signal lifetimes, including compiled Python callables."""


class SignalConnections:
    """Disconnect external signals when their owning QObject is destroyed.

    PyQt cannot always infer the QObject receiver of a compiled bound method.
    Relays therefore have an explicit lifetime and release their callback before
    disconnecting, so already queued deliveries also become harmless.
    """

    def __init__(self, owner):
        self._connections = []
        owner.destroyed.connect(self.clear)

    def connect(self, signal, slot, *args, **kwargs):
        callback = [slot]

        def relay(*values):
            current = callback[0]
            if current is not None:
                current(*values)

        connection = signal.connect(relay, *args, **kwargs)
        self._connections.append((signal, connection, callback))
        return connection

    def clear(self, *_):
        connections, self._connections = self._connections, []
        for _signal, _connection, callback in connections:
            callback[0] = None
        for signal, connection, _callback in connections:
            try:
                signal.disconnect(connection)
            except (TypeError, RuntimeError):
                # The sender or its connection may already have been destroyed.
                pass


def _format_display(value, fmt):
    if fmt == "自动": return value
    try:
        num = int(float(value)) if not isinstance(value, int) else value
    except (ValueError, TypeError, OverflowError): return value
    if fmt == "十六进制(HEX)":
        return f"0x{num:02X}" if num >= 0 else f"-0x{abs(num):02X}"
    if fmt == "二进制(BIN)":
        return f"0b{num:08b}" if num >= 0 else f"-0b{abs(num):08b}"
    if fmt == "十进制": return str(num)
    return value


def _resolve_path(data, path):
    for part in path.split("."):
        if data is None: return None
        if isinstance(data, dict): data = data.get(part)
        elif isinstance(data, (list, tuple)):
            try: data = data[int(part)]
            except (ValueError, IndexError): return None
        else: return None
    return data


_STRUCT_FMT = {
    "uint8": ("B", 1), "int8": ("b", 1),
    "uint16": ("H", 2), "int16": ("h", 2),
    "uint32": ("I", 4), "int32": ("i", 4),
    "float32": ("f", 4),
}


class DataBinding:
    """Wire the hub (serial, TCP and MQTT links) to bound widgets and command senders."""
    def __init__(self, ui, hub):
        self.ui = ui
        self.hub = hub
        self._connections = SignalConnections(ui)
        ui._comm_hub = hub
        for w in ui.widgets.values():
            if hasattr(w, "set_serial_handler"):
                w.set_serial_handler(hub)  # connection cards pick their own link
            if isinstance(w, RealtimeLineChart):
                w._serial_connections.clear()
                w._serial_connections.connect(hub.dataReceived, w.on_parsed)
                w._serial_connections.connect(hub.rawReceived, w.on_raw)
                w._serial_connections.connect(hub.disconnected, w.reset_stream)
        self._connections.connect(self.hub.dataReceived, self._on_data)

    def _on_data(self, data: dict):
        try:
            if 'temperature' in data and data['temperature'] is not None:
                value = data['temperature']
                w = self.ui.widgets.get('temperature')
                if w:
                    w.set_value(str(value))

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'pressure' in data and data['pressure'] is not None:
                value = data['pressure']
                w = self.ui.widgets.get('pressure')
                if w:
                    w.set_value(str(value))

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'pressure' in data and data['pressure'] is not None:
                value = data['pressure']
                w = self.ui.widgets.get('pressure_ring')
                if w:
                    w.set_value(binding_integer(value))

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'running' in data and data['running'] is not None:
                value = data['running']
                w = self.ui.widgets.get('running')
                if w:
                    w.set_on(binding_led(value, '1', '0'))

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'setpoint' in data and data['setpoint'] is not None:
                value = data['setpoint']
                w = self.ui.widgets.get('setpoint_slider')
                if w:
                    value = binding_integer(value)
                    with QSignalBlocker(w):
                        w.setValue(value)
                    # Fluent normally moves its handle in the blocked valueChanged signal.
                    w._adjustHandlePos()

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'setpoint' in data and data['setpoint'] is not None:
                value = data['setpoint']
                w = self.ui.widgets.get('setpoint_spin')
                if w:
                    value = binding_integer(value)
                    with QSignalBlocker(w):
                        w.setValue(value)

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'running' in data and data['running'] is not None:
                value = data['running']
                w = self.ui.widgets.get('run_switch')
                if w:
                    value = binding_boolean(value)
                    with QSignalBlocker(w._switch):
                        w._switch.setChecked(value)

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
