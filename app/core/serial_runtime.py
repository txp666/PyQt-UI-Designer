# coding: utf-8
"""Serial runtime shared by the designer and standalone exports."""
import sys
from typing import List, Dict
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from .protocol_parser import BaseParser, create_parser

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
            parser = create_parser(parser_type if parser_type is not None else cfg["parser"],
                                   parser_config if parser_config is not None else cfg["parserConfig"])
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
        self._thread.rawReceived.connect(self.rawReceived)
        self._thread.parsedReceived.connect(self.dataReceived)
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
        if self.is_connected:
            try:
                self._port.write(data)
                self.dataSent.emit(data)
            except Exception as exc:
                self.error.emit(f"发送失败: {exc}")

    def send_text(self, text, encoding="utf-8"):
        self.send(text.encode(encoding))

    def _on_error(self, message):
        self.error.emit(message)
        self.disconnect()
