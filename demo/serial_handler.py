# coding: utf-8
"""Data frame parsers for serial communication."""
import json
from typing import Optional, Dict, Any, List


class BaseParser:
    """Incremental parsers return every complete message, in arrival order."""

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        raise NotImplementedError


class RawFrameBuffer:
    """Frame raw widget bindings when both delimiters are configured.

    Without both delimiters, the read chunk remains the legacy input unit:
    no total packet length can be inferred from a single widget's byte offset.
    """
    def __init__(self, header=b"", footer=b"", max_buffer=65536):
        self.header, self.footer = header, footer
        self.max_buffer = max_buffer
        self._buf = b""

    def reset(self):
        self._buf = b""

    def feed(self, data):
        if not self.header or not self.footer:
            return [data]
        self._buf += data
        frames = []
        while self._buf:
            start = self._buf.find(self.header)
            if start < 0:
                keep = len(self.header) - 1
                self._buf = self._buf[-keep:] if keep else b""
                break
            self._buf = self._buf[start:]
            end = self._buf.find(self.footer, len(self.header))
            if end < 0:
                if len(self._buf) > self.max_buffer:
                    self._buf = self._buf[1:]
                    continue
                break
            end += len(self.footer)
            if end <= self.max_buffer:
                frames.append(self._buf[:end])
            self._buf = self._buf[end:]
        return frames


class LineParser(BaseParser):
    """Parse newline-terminated ASCII lines.

    Supports formats:
      - CSV:  "key1,val1,key2,val2\\n"  or  "val1,val2,val3\\n" (auto-indexed)
      - KEY=VALUE: "temp=25.3,humidity=60\\n"
      - JSON per line: '{"temp": 25.3}\\n'
    """

    def __init__(self, separator: str = ",", max_buffer: int = 65536):
        if not separator:
            raise ValueError("行分隔符不能为空")
        self._buf = b""
        self._sep = separator
        self._max_buffer = max_buffer
        self._discarding = False

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        # Only actual LF terminates a record. JSON may contain escaped \n.
        results = []
        parts = data.split(b"\n")
        for index, part in enumerate(parts):
            complete = index < len(parts) - 1
            if not self._discarding:
                if len(self._buf) + len(part) > self._max_buffer:
                    self._buf = b""
                    self._discarding = True
                else:
                    self._buf += part
            if complete:
                if not self._discarding:
                    text = self._buf.decode("utf-8", errors="replace").strip()
                    if text:
                        parsed = self._parse_line(text)
                        if parsed:
                            results.append(parsed)
                self._buf = b""
                self._discarding = False
        return results

    def _parse_line(self, text: str) -> Optional[Dict[str, Any]]:
        # try JSON
        if text.startswith("{"):
            try:
                value = json.loads(text)
                return value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                return None

        parts = [p.strip() for p in text.split(self._sep)]

        # KEY=VALUE format
        if any("=" in p for p in parts):
            result = {}
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                    result[k.strip()] = self._auto_number(v.strip())
            return result if result else None

        # pure CSV values — auto-index as ch0, ch1, ...
        result = {}
        for i, p in enumerate(parts):
            result[f"ch{i}"] = self._auto_number(p)
        return result

    @staticmethod
    def _auto_number(s: str):
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        return s


class HexFrameParser(BaseParser):
    """Parse fixed-header hex frames.

    Expected config:
      header: bytes (e.g. b'\\xAA\\x55')
      footer: bytes (e.g. b'\\x55\\xAA')
      fields: list of (name, offset, length, type)
    """

    def __init__(self, header: bytes = b"\xAA\x55", footer: bytes = b"\x55\xAA",
                 fields: list = None, max_buffer: int = 65536):
        if not header or not footer:
            raise ValueError("HEX 帧头和帧尾不能为空")
        self._buf = b""
        self._header = header
        self._footer = footer
        self._fields = fields or []
        self._max_buffer = max_buffer
        sizes = {"uint8": 1, "int8": 1, "uint16": 2, "int16": 2, "float32": 4}
        for name, offset, length, dtype in self._fields:
            if offset < 0 or length <= 0 or (dtype in sizes and length != sizes[dtype]):
                raise ValueError(f"无效 HEX 字段: {name}")

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        self._buf += data
        results = []
        while self._buf:
            start = self._buf.find(self._header)
            if start < 0:
                self._buf = self._buf[-(len(self._header) - 1):] if len(self._header) > 1 else b""
                break
            self._buf = self._buf[start:]
            end = self._buf.find(self._footer, len(self._header))
            if end < 0:
                if len(self._buf) > self._max_buffer:
                    self._buf = self._buf[1:]
                    continue
                break
            frame_end = end + len(self._footer)
            if frame_end <= self._max_buffer:
                parsed = self._parse_payload(self._buf[len(self._header):end])
                if parsed:
                    results.append(parsed)
            self._buf = self._buf[frame_end:]
        return results

    def _parse_payload(self, payload: bytes) -> Dict[str, Any]:
        result = {}
        for name, offset, length, dtype in self._fields:
            if offset + length > len(payload):
                continue
            raw = payload[offset:offset + length]
            if dtype == "uint8":
                result[name] = raw[0]
            elif dtype == "int8":
                v = raw[0]
                result[name] = v - 256 if v > 127 else v
            elif dtype == "uint16":
                result[name] = int.from_bytes(raw, "big")
            elif dtype == "int16":
                result[name] = int.from_bytes(raw, "big", signed=True)
            elif dtype == "float32":
                import struct
                result[name] = struct.unpack(">f", raw)[0]
            else:
                result[name] = raw.hex()
        return result


class ModbusRTUParser(BaseParser):
    """Parse Modbus RTU response frames.

    Extracts register values from FC 01-04 responses and maps them
    to named fields: reg0, reg1, … (or custom field names).
    """

    def __init__(self, fields: list = None):
        self._buf = b""
        self._fields = fields or []

    @staticmethod
    def _frame_length(buf):
        if len(buf) < 3:
            return None
        if not 1 <= buf[0] <= 247:
            return 0
        fc = buf[1]
        if fc in (1, 2, 3, 4):
            count = buf[2]
            if not 1 <= count <= 250 or (fc in (3, 4) and count % 2):
                return 0
            return count + 5
        if fc in (5, 6, 15, 16):
            return 8
        if fc in (0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x8F, 0x90):
            return 5
        return 0

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        self._buf += data
        results = []
        while len(self._buf) >= 5:
            length = self._frame_length(self._buf)
            if not length:
                self._buf = self._buf[1:]
                continue
            if len(self._buf) < length:
                # Noise may imitate a long header. Resync only to a complete,
                # CRC-verified response; otherwise keep the partial frame.
                found = False
                for offset in range(1, len(self._buf) - 4):
                    tail = self._buf[offset:]
                    size = self._frame_length(tail)
                    if size and len(tail) >= size and modbus_crc(tail[:size - 2]) == tail[size - 2:size]:
                        self._buf = tail
                        found = True
                        break
                if found:
                    continue
                break
            frame = self._buf[:length]
            if modbus_crc(frame[:-2]) != frame[-2:]:
                self._buf = self._buf[1:]
                continue
            self._buf = self._buf[length:]
            slave, fc = frame[:2]
            if fc in (1, 2, 3, 4):
                results.append(self._parse_read_response(slave, fc, frame[3:-2]))
            elif fc >= 0x80:
                results.append({"slave": slave, "fc": fc, "error": frame[2]})
            else:
                results.append({"slave": slave, "fc": fc,
                                "address": int.from_bytes(frame[2:4], "big"),
                                "value": int.from_bytes(frame[4:6], "big")})
        return results

    def _parse_read_response(self, slave: int, fc: int,
                             payload: bytes) -> Dict[str, Any]:
        result: Dict[str, Any] = {"slave": slave, "fc": fc}
        if fc in (0x03, 0x04):
            regs = []
            for i in range(0, len(payload), 2):
                if i + 1 < len(payload):
                    regs.append(int.from_bytes(payload[i:i + 2], "big"))
            for idx, val in enumerate(regs):
                name = self._fields[idx] if idx < len(self._fields) else f"reg{idx}"
                result[name] = val
        elif fc in (0x01, 0x02):
            bits = []
            for b in payload:
                for bit_i in range(8):
                    bits.append((b >> bit_i) & 1)
            for idx, val in enumerate(bits):
                name = self._fields[idx] if idx < len(self._fields) else f"coil{idx}"
                result[name] = val
        return result


def modbus_crc(data: bytes) -> bytes:
    """Calculate Modbus RTU CRC-16."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, "little")


def build_modbus_frame(slave: int, func: int, address: int,
                       value: int = 0, count: int = 1) -> bytes:
    """Build a Modbus RTU request frame.

    Supports FC 01-06, 0x0F, 0x10.
    For FC 01-04: count = number of registers/coils to read.
    For FC 05: value = 0xFF00 (ON) or 0x0000 (OFF).
    For FC 06: value = register value to write.
    """
    pdu = bytes([slave, func])
    pdu += address.to_bytes(2, "big")

    if func in (0x01, 0x02, 0x03, 0x04):
        pdu += count.to_bytes(2, "big")
    elif func in (0x05, 0x06):
        pdu += value.to_bytes(2, "big")
    else:
        pdu += count.to_bytes(2, "big")

    return pdu + modbus_crc(pdu)


def create_parser(parser_type: str, config: dict = None) -> BaseParser:
    config = config or {}
    if parser_type == "line":
        return LineParser(separator=config.get("separator", ","))
    elif parser_type == "hex":
        return HexFrameParser(
            header=bytes.fromhex(config.get("header", "AA55")),
            footer=bytes.fromhex(config.get("footer", "55AA")),
            fields=config.get("fields", []),
        )
    elif parser_type == "modbus":
        return ModbusRTUParser(fields=config.get("fields", []))
    raise ValueError(f"未知解析模式: {parser_type}")

# coding: utf-8
"""Serial runtime shared by the designer and standalone exports."""
import sys
from typing import List, Dict
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, QObject


try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


def _list_all_ports() -> List[Dict[str, str]]:
    """Enumerate serial ports, merging pyserial results with Windows registry
    to ensure virtual COM ports (Eltima, com0com, etc.) are included."""
    found: Dict[str, str] = {}

    if HAS_SERIAL:
        for p in serial.tools.list_ports.comports():
            device = p.device.upper() if sys.platform == "win32" else p.device
            found[device] = p.description

    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DEVICEMAP\SERIALCOMM",
            )
            i = 0
            while True:
                try:
                    _name, val, _ = winreg.EnumValue(key, i)
                    port_upper = val.upper()
                    if port_upper not in found:
                        found[port_upper] = val
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass

    def _sort_key(port: str) -> tuple:
        import re
        m = re.search(r"(\d+)$", port)
        return (int(m.group(1)) if m else 999, port)

    return [
        {"port": p, "description": d}
        for p, d in sorted(found.items(), key=lambda x: _sort_key(x[0]))
    ]


class SerialReaderThread(QThread):
    """Background thread continuously reading from serial port."""

    rawReceived = pyqtSignal(bytes)
    parsedReceived = pyqtSignal(dict)
    errorOccurred = pyqtSignal(str)

    def __init__(self, port, parser: BaseParser, parent=None):
        super().__init__(parent)
        self._port = port
        self._parser = parser
        self._running = True

    def run(self):
        while self._running:
            try:
                if self._port.in_waiting > 0:
                    data = self._port.read(self._port.in_waiting)
                    self.rawReceived.emit(data)
                    for parsed in self._parser.feed(data):
                        self.parsedReceived.emit(parsed)
                else:
                    self.msleep(10)
            except Exception as e:
                if self._running:
                    self.errorOccurred.emit(str(e))
                break

    def stop(self):
        self._running = False
        if not self.wait(2000):
            raise RuntimeError("串口读取线程未能停止")


class SerialHandler(QObject):
    dataReceived = pyqtSignal(dict)
    rawReceived = pyqtSignal(bytes)
    dataSent = pyqtSignal(bytes)
    connectionChanged = pyqtSignal(bool)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    error = pyqtSignal(str)
    DEFAULT_CONFIG = {}

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self._port = None
        self._thread = None
        self._parser = None
        self.configure(config or self.DEFAULT_CONFIG)

    def configure(self, config):
        self._config = {"baudRate": 115200, "dataBits": 8, "parity": "None",
                        "stopBits": 1, "flowControl": "none", "parser": "line",
                        "parserConfig": {"separator": ","}, **config}

    @property
    def is_connected(self):
        return self._port is not None and getattr(self._port, "is_open", False)

    @staticmethod
    def list_ports():
        return _list_all_ports()

    def connect(self, port, baudrate=None, databits=None, parity=None, stopbits=None,
                flowcontrol=None, parser_type=None, parser_config=None):
        if not HAS_SERIAL:
            self.error.emit("pyserial 未安装，请运行 pip install pyserial")
            return False
        cfg = self._config
        parity_map = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"}
        parity = parity if parity is not None else cfg["parity"]
        flow = flowcontrol if flowcontrol is not None else cfg["flowControl"]
        flow = {"无": "none", "RTS/CTS": "rtscts", "XON/XOFF": "xonxoff", "DTR/DSR": "dsrdtr"}.get(flow, flow)
        try:
            selected_parser = parser_type if parser_type is not None else cfg["parser"]
            selected_config = parser_config
            if selected_config is None:
                selected_config = cfg["parserConfig"] if selected_parser == cfg["parser"] else {}
            parser = create_parser(selected_parser, selected_config)
            if self._thread or self._port:
                self.disconnect()
            port_obj = serial.Serial(
                port=port, baudrate=baudrate if baudrate is not None else cfg["baudRate"],
                bytesize=databits if databits is not None else cfg["dataBits"],
                parity=parity_map.get(parity, parity),
                stopbits=stopbits if stopbits is not None else cfg["stopBits"],
                timeout=0.1, write_timeout=1,
                rtscts=flow == "rtscts", xonxoff=flow == "xonxoff", dsrdtr=flow == "dsrdtr")
        except Exception as exc:
            self.error.emit(f"串口打开失败: {exc}")
            return False
        self._port = port_obj
        self._parser = parser
        self._thread = SerialReaderThread(port_obj, parser, self)
        self._thread.rawReceived.connect(self._on_raw)
        self._thread.parsedReceived.connect(self._on_parsed)
        self._thread.errorOccurred.connect(self._on_error)
        self._thread.start()
        self.connected.emit(port)
        self.connectionChanged.emit(True)
        return True

    def connect_port(self, port, baudrate=None, **kwargs):
        return self.connect(port, baudrate, **kwargs)

    def disconnect(self):
        if self._thread:
            self._thread.stop()
            self._thread.deleteLater()
            self._thread = None
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None
        self.disconnected.emit()
        self.connectionChanged.emit(False)

    def disconnect_port(self):
        self.disconnect()

    def send(self, data):
        """Return success only after the port accepts the entire payload."""
        if not self.is_connected:
            return False
        try:
            written = self._port.write(data)
            if written != len(data):
                raise OSError(f"串口仅写入 {written}/{len(data)} 字节")
        except Exception as exc:
            self.error.emit(f"发送失败: {exc}")
            return False
        self.dataSent.emit(data)
        return True

    def send_text(self, text, encoding="utf-8"):
        return self.send(text.encode(encoding))

    @pyqtSlot(bytes)
    def _on_raw(self, data):
        # Events already queued by a stopped reader can arrive after reconnect.
        if self._thread is not None and self.sender() is self._thread:
            self.rawReceived.emit(data)

    @pyqtSlot(dict)
    def _on_parsed(self, data):
        if self._thread is not None and self.sender() is self._thread:
            self.dataReceived.emit(data)

    @pyqtSlot(str)
    def _on_error(self, message):
        reader = self.sender()
        if reader is not self._thread or reader is None:
            return
        self.error.emit(message)
        # An error observer may already have opened a replacement connection.
        if self._thread is reader:
            self.disconnect()

SerialHandler.DEFAULT_CONFIG = {'baudRate': 115200, 'dataBits': 8, 'parity': 'None', 'stopBits': 1, 'parser': 'line', 'parserConfig': {'separator': ','}}
