# coding: utf-8
"""Data binding engine — connects serial data to widget properties.

Supports four parse modes:
  - 键值匹配: match key from parsed dict (serialDataReceived)
  - JSON路径: traverse nested parsed dict via dot-path (serialDataReceived)
  - HEX字节提取: extract bytes from raw serial data (serialRawReceived)
  - Modbus: extract register/coil from ModbusRTUParser output (serialDataReceived)
"""
import struct
from typing import Dict, Any, Optional, List

from PyQt5.QtCore import QObject, QSignalBlocker

from app.common.signal_bus import signalBus
from app.core.protocol_parser import RawFrameBuffer
from app.core.binding_values import (
    binding_boolean, binding_float, binding_integer, binding_led, binding_register,
)

_STRUCT_FMT = {
    "uint8": ("B", 1), "int8": ("b", 1),
    "uint16": ("H", 2), "int16": ("h", 2),
    "uint32": ("I", 4), "int32": ("i", 4),
    "float32": ("f", 4),
}


class BindingEntry:
    """A single binding: data source -> widget property."""

    def __init__(self, widget_id: str, prop_name: str,
                 type_name: str = "", display_format: str = "自动",
                 parse_mode: str = "键值匹配",
                 key: str = "", json_path: str = "",
                 byte_offset: int = 0, data_type: str = "uint16",
                 byte_order: str = "大端(BE)",
                 expression: Optional[str] = None,
                 frame_header: str = "", frame_tail: str = "",
                 mb_reg_index: int = 0, mb_slave_filter: int = -1,
                 mb_data_type: str = "uint16", mb_reg_order: str = "大端(AB CD)",
                 mb_fc_filter: int = -1,
                 led_on_value: str = "1", led_off_value: str = "0"):
        self.widget_id = widget_id
        self.prop_name = prop_name
        self.type_name = type_name
        self.display_format = display_format
        self.parse_mode = parse_mode
        self.key = key
        self.json_path = json_path
        self.byte_offset = byte_offset
        self.data_type = data_type
        self.byte_order = byte_order
        self.expression = expression
        self.led_on_value = led_on_value
        self.led_off_value = led_off_value
        self.frame_header = self._hex_to_bytes(frame_header)
        self.frame_tail = self._hex_to_bytes(frame_tail)
        self._raw_frames = RawFrameBuffer(self.frame_header, self.frame_tail)
        self.mb_reg_index = mb_reg_index
        self.mb_slave_filter = mb_slave_filter
        self.mb_data_type = mb_data_type
        self.mb_reg_order = mb_reg_order
        self.mb_fc_filter = mb_fc_filter

    @staticmethod
    def _hex_to_bytes(s: str) -> bytes:
        s = s.replace(" ", "")
        if not s:
            return b""
        if len(s) % 2 != 0:
            s = "0" + s
        try:
            return bytes.fromhex(s)
        except ValueError:
            return b""

    # -- extraction ----------------------------------------------------------

    def extract_from_parsed(self, data: dict) -> Any:
        """Extract value from parsed dict (键值匹配 / JSON路径 / Modbus)."""
        if self.parse_mode == "键值匹配":
            return data.get(self.key)

        if self.parse_mode == "JSON路径":
            return self._resolve_path(data, self.json_path)

        if self.parse_mode == "Modbus":
            return self._extract_modbus(data)

        return None

    def _extract_modbus(self, data: dict) -> Any:
        """Extract register/coil value from ModbusRTUParser output.

        Supports single-register types (uint16, int16) and dual-register
        types (uint32, int32, float32) with configurable register order.
        """
        if self.mb_slave_filter >= 0:
            if data.get("slave") != self.mb_slave_filter:
                return None
        fc = data.get("fc", 0)
        if self.mb_fc_filter >= 0 and fc != self.mb_fc_filter:
            return None
        idx = self.mb_reg_index

        if fc in (0x01, 0x02):
            return data.get(f"coil{idx}")

        dt = self.mb_data_type
        r0 = data.get(f"reg{idx}")
        if r0 is None:
            return None
        r0 = binding_register(r0)

        if dt == "uint16":
            return r0
        if dt == "int16":
            return r0 - 65536 if r0 > 32767 else r0

        r1 = data.get(f"reg{idx + 1}")
        if r1 is None:
            return None
        r1 = binding_register(r1)
        if self.mb_reg_order == "大端(AB CD)":
            high, low = r0, r1
        else:
            high, low = r1, r0
        raw_bytes = high.to_bytes(2, "big") + low.to_bytes(2, "big")

        if dt == "uint32":
            return int.from_bytes(raw_bytes, "big")
        if dt == "int32":
            return int.from_bytes(raw_bytes, "big", signed=True)
        if dt == "float32":
            return struct.unpack(">f", raw_bytes)[0]
        return r0

    def _strip_frame(self, raw: bytes) -> Optional[bytes]:
        """Match frame header/tail and return the payload between them.
        If no header/tail configured, return raw as-is.
        Returns None if header/tail are configured but not found."""
        data = raw
        if self.frame_header:
            idx = data.find(self.frame_header)
            if idx < 0:
                return None
            data = data[idx + len(self.frame_header):]
        if self.frame_tail:
            idx = data.find(self.frame_tail)
            if idx < 0:
                return None
            data = data[:idx]
        return data

    def extract_from_raw(self, raw: bytes) -> Any:
        """Extract value from raw bytes (HEX字节提取)."""
        if self.parse_mode != "HEX字节提取":
            return None

        payload = self._strip_frame(raw)
        if payload is None:
            return None

        dt = self.data_type
        if dt == "ASCII":
            end = payload.find(0, self.byte_offset)
            if end < 0:
                end = len(payload)
            return payload[self.byte_offset:end].decode("ascii", errors="replace")

        fmt_info = _STRUCT_FMT.get(dt)
        if not fmt_info:
            return None
        fmt_char, size = fmt_info
        if self.byte_offset + size > len(payload):
            return None
        bo = ">" if self.byte_order == "大端(BE)" else "<"
        try:
            return struct.unpack(bo + fmt_char,
                                 payload[self.byte_offset:self.byte_offset + size])[0]
        except struct.error:
            return None

    def extract_all_from_raw(self, raw: bytes):
        for frame in self._raw_frames.feed(raw):
            value = self.extract_from_raw(frame)
            if value is not None:
                yield value

    @staticmethod
    def _resolve_path(data: Any, path: str) -> Any:
        """Traverse nested dict/list via dot-notation path like 'a.b.0.c'."""
        for part in path.split("."):
            if data is None:
                return None
            if isinstance(data, dict):
                data = data.get(part)
            elif isinstance(data, (list, tuple)):
                try:
                    data = data[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return data

    # -- transform / format --------------------------------------------------

    def evaluate(self, raw_value) -> Any:
        if not self.expression:
            return raw_value
        try:
            return eval(self.expression, {"__builtins__": {}}, {"value": raw_value})
        except Exception:
            return raw_value

    def format_value(self, value) -> Any:
        if self.display_format == "自动" or self.prop_name not in ("text", "value"):
            return value
        try:
            num = int(float(value)) if not isinstance(value, int) else value
        except (ValueError, TypeError, OverflowError):
            return value
        if self.display_format == "十六进制(HEX)":
            return f"0x{num:02X}" if num >= 0 else f"-0x{abs(num):02X}"
        if self.display_format == "二进制(BIN)":
            return f"0b{num:08b}" if num >= 0 else f"-0b{abs(num):08b}"
        if self.display_format == "十进制":
            return str(num)
        return value


class DataBindingEngine(QObject):
    """Manages bindings between serial data and widget properties."""

    _instance: Optional["DataBindingEngine"] = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if DataBindingEngine._initialized:
            return
        super().__init__()
        DataBindingEngine._initialized = True
        self._bindings: List[BindingEntry] = []
        self._widget_map: Dict[str, Any] = {}
        self._latest_data: Dict[str, Any] = {}
        self._active = False

        signalBus.serialDataReceived.connect(self._on_data)
        signalBus.serialRawReceived.connect(self._on_raw)
        signalBus.serialDisconnected.connect(self.reset_stream)

    def reset_stream(self):
        for binding in self._bindings:
            binding._raw_frames.reset()

    def start(self):
        self._active = True

    def stop(self):
        self._active = False
        self.reset_stream()

    def clear(self):
        self._bindings.clear()
        self._widget_map.clear()
        self._latest_data.clear()

    def register_widget(self, widget_id: str, widget):
        self._widget_map[widget_id] = widget

    def add_binding(self, binding: BindingEntry):
        self._bindings.append(binding)

    def load_bindings_from_project(self, widgets_data: list):
        self._bindings.clear()
        self._walk_bindings(widgets_data)

    def _walk_bindings(self, items: list):
        for wd in items:
            binding = wd.get("binding")
            if not binding:
                self._walk_bindings(wd.get("children", []))
                continue

            pm = binding.get("parseMode", "键值匹配")
            has_config = (
                (pm == "键值匹配" and binding.get("key"))
                or (pm == "JSON路径" and binding.get("jsonPath"))
                or (pm == "HEX字节提取")
                or (pm == "Modbus")
            )
            if not has_config:
                self._walk_bindings(wd.get("children", []))
                continue

            props = wd.get("properties", {})
            entry = BindingEntry(
                widget_id=wd["id"],
                prop_name=self._default_bind_prop(wd["type"]),
                type_name=wd["type"],
                display_format=props.get("displayFormat", "自动"),
                parse_mode=pm,
                key=binding.get("key", ""),
                json_path=binding.get("jsonPath", ""),
                byte_offset=int(binding.get("byteOffset", 0)),
                data_type=binding.get("dataType", "uint16"),
                byte_order=binding.get("byteOrder", "大端(BE)"),
                expression=binding.get("expression"),
                frame_header=binding.get("frameHeader", ""),
                frame_tail=binding.get("frameTail", ""),
                mb_reg_index=int(binding.get("mbRegIndex", 0)),
                mb_slave_filter=int(binding.get("mbSlaveFilter", -1)),
                mb_data_type=binding.get("mbDataType", "uint16"),
                mb_reg_order=binding.get("mbRegOrder", "大端(AB CD)"),
                mb_fc_filter=int(binding.get("mbFcFilter", -1)),
                led_on_value=str(props.get("onValue", "1")),
                led_off_value=str(props.get("offValue", "0")),
            )
            self._bindings.append(entry)
            self._walk_bindings(wd.get("children", []))

    @staticmethod
    def _default_bind_prop(type_name: str) -> str:
        mapping = {
            "Label": "text",
            "LEDIndicator": "on",
            "NumericDisplay": "value",
            "ProgressBar": "value",
            "ProgressRingDisplay": "value",
            "GaugeMeter": "value",
            "ToggleSwitch": "checked",
            "Slider": "value",
            "SpinBox": "value",
        }
        return mapping.get(type_name, "text")

    # -- data handlers -------------------------------------------------------

    def _on_data(self, data: dict):
        """Handle parsed data — 键值匹配, JSON路径, Modbus modes."""
        if not self._active:
            return
        self._latest_data.update(data)
        for b in self._bindings:
            if b.parse_mode not in ("键值匹配", "JSON路径", "Modbus"):
                continue
            try:
                value = b.extract_from_parsed(data)
                if value is not None:
                    self._push_value(b, value)
            except (TypeError, ValueError, OverflowError, struct.error):
                # A malformed device field must not stop the other bindings.
                continue

    def _on_raw(self, raw: bytes):
        """Handle raw bytes — HEX字节提取 mode."""
        if not self._active:
            return
        for b in self._bindings:
            if b.parse_mode != "HEX字节提取":
                continue
            for value in b.extract_all_from_raw(raw):
                try:
                    self._push_value(b, value)
                except (TypeError, ValueError, OverflowError, struct.error):
                    continue

    def _push_value(self, b: BindingEntry, raw_value):
        value = b.evaluate(raw_value)
        value = b.format_value(value)
        widget = self._widget_map.get(b.widget_id)
        if widget:
            self._apply_to_widget(widget, b, value)

    def _apply_to_widget(self, widget, binding: BindingEntry, value):
        prop = binding.prop_name

        # Device feedback updates the display without sending the value back
        # as another user command (or showing a user-action notification).
        if binding.type_name == "ToggleSwitch" and prop == "checked":
            value = binding_boolean(value)
            with QSignalBlocker(widget._switch):
                widget._switch.setChecked(value)
            return
        if binding.type_name in ("Slider", "SpinBox") and prop == "value":
            value = binding_integer(value)
            with QSignalBlocker(widget):
                widget.setValue(value)
            if binding.type_name == "Slider":
                # Fluent's separate handle normally moves in valueChanged,
                # which is blocked to prevent a device-to-command feedback loop.
                widget._adjustHandlePos()
            return

        if prop == "__append__":
            if hasattr(widget, "append_value"):
                try:
                    widget.append_value(float(value))
                except (ValueError, TypeError):
                    pass
            return

        if prop == "value":
            if binding.type_name in ("ProgressBar", "ProgressRingDisplay"):
                value = binding_integer(value)
            elif binding.type_name == "GaugeMeter":
                value = binding_float(value)

        if binding.type_name == "LEDIndicator" and prop == "on":
            value = binding_led(value, binding.led_on_value, binding.led_off_value)

        from app.widgets.basic import apply_property
        try:
            apply_property(widget, binding.type_name, prop, value)
        except Exception:
            if hasattr(widget, f"set_{prop}"):
                getattr(widget, f"set_{prop}")(value)
            elif hasattr(widget, "setText"):
                widget.setText(str(value))

    @property
    def latest_data(self) -> Dict[str, Any]:
        return dict(self._latest_data)


bindingEngine = DataBindingEngine()
