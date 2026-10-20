# coding: utf-8
"""Auto-generated data binding."""
import struct
from PyQt5.QtCore import QSignalBlocker
from ui import RealtimeLineChart

"""Conversions shared by live bindings and standalone exported applications."""
import math


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


def binding_boolean(value):
    """Read explicit boolean tokens or finite numbers; reject unknown text."""
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in ("true", "on", "yes"):
            return True
        if token in ("false", "off", "no"):
            return False
    return bool(binding_float(value))


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
    def __init__(self, ui, serial_handler):
        self.ui = ui
        self.serial = serial_handler
        ui._serial_handler = serial_handler
        for w in ui.widgets.values():
            if hasattr(w, "set_serial_handler"):
                w.set_serial_handler(serial_handler)
            if isinstance(w, RealtimeLineChart):
                serial_handler.dataReceived.connect(w.on_parsed)
                serial_handler.rawReceived.connect(w.on_raw)
                serial_handler.disconnected.connect(w.reset_stream)
        self.serial.dataReceived.connect(self._on_data)

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
