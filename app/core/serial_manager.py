# coding: utf-8
"""Serial port manager with background reading thread."""
import sys
from typing import Optional, List, Dict

from PyQt5.QtCore import QThread, pyqtSignal

from app.common.signal_bus import signalBus
from app.core.protocol_parser import BaseParser, create_parser

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
                    parsed = self._parser.feed(data)
                    if parsed:
                        self.parsedReceived.emit(parsed)
                else:
                    self.msleep(10)
            except Exception as e:
                if self._running:
                    self.errorOccurred.emit(str(e))
                break

    def stop(self):
        self._running = False
        self.wait(2000)


class SerialManager:
    """Manages serial port connection and data flow."""

    _instance: Optional["SerialManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._port = None
            cls._instance._thread = None
            cls._instance._parser = None
        return cls._instance

    @property
    def is_connected(self) -> bool:
        return self._port is not None and getattr(self._port, "is_open", False)

    @staticmethod
    def list_ports():
        return _list_all_ports()

    def connect(self, port: str, baudrate: int = 115200,
                databits: int = 8, parity: str = "N", stopbits: float = 1,
                flowcontrol: str = "none",
                parser_type: str = "line", parser_config: dict = None):
        if self.is_connected:
            self.disconnect()

        if not HAS_SERIAL:
            signalBus.serialError.emit("pyserial 未安装，请运行 pip install pyserial")
            return False

        parity_map = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S",
                      "N": "N", "E": "E", "O": "O", "M": "M", "S": "S"}
        stop_map = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE, 2: serial.STOPBITS_TWO}
        data_map = {5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS, 8: serial.EIGHTBITS}

        rtscts = flowcontrol == "rtscts"
        xonxoff = flowcontrol == "xonxoff"
        dsrdtr = flowcontrol == "dsrdtr"

        try:
            self._port = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=data_map.get(databits, serial.EIGHTBITS),
                parity=parity_map.get(parity, "N"),
                stopbits=stop_map.get(stopbits, serial.STOPBITS_ONE),
                timeout=0.1,
                rtscts=rtscts,
                xonxoff=xonxoff,
                dsrdtr=dsrdtr,
            )
        except Exception as e:
            signalBus.serialError.emit(f"串口打开失败: {e}")
            return False

        self._parser = create_parser(parser_type, parser_config)
        self._thread = SerialReaderThread(self._port, self._parser)
        self._thread.rawReceived.connect(signalBus.serialRawReceived.emit)
        self._thread.parsedReceived.connect(signalBus.serialDataReceived.emit)
        self._thread.errorOccurred.connect(self._on_error)
        self._thread.start()
        signalBus.serialConnected.emit(port)
        return True

    def disconnect(self):
        if self._thread:
            self._thread.stop()
            self._thread = None
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None
        signalBus.serialDisconnected.emit()

    def send(self, data: bytes):
        if self.is_connected:
            try:
                self._port.write(data)
                signalBus.serialDataSent.emit(data)
            except Exception as e:
                signalBus.serialError.emit(f"发送失败: {e}")

    def send_text(self, text: str, encoding: str = "utf-8"):
        self.send(text.encode(encoding))

    def _on_error(self, msg: str):
        signalBus.serialError.emit(msg)
        self.disconnect()


serialManager = SerialManager()
