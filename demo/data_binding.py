# coding: utf-8
"""Auto-generated data binding."""
import struct
from ui import RealtimeLineChart


def _format_display(value, fmt):
    if fmt == "自动": return value
    try:
        num = int(float(value)) if not isinstance(value, int) else value
    except (ValueError, TypeError): return value
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
        if 'temperature' in data:
            value = data['temperature']
            w = self.ui.widgets.get('temperature')
            if w:
                w.set_value(str(value))

        if 'pressure' in data:
            value = data['pressure']
            w = self.ui.widgets.get('pressure')
            if w:
                w.set_value(str(value))

        if 'pressure' in data:
            value = data['pressure']
            w = self.ui.widgets.get('gauge')
            if w:
                w.set_value(float(value))

        if 'running' in data:
            value = data['running']
            w = self.ui.widgets.get('running')
            if w:
                _sv = str(value).strip()
                if _sv == '1': w.set_on(True)
                elif _sv == '0': w.set_on(False)
                else:
                    try: w.set_on(float(_sv) == float('1'))
                    except (ValueError, TypeError): w.set_on(bool(_sv))
