"""One hub for every communication link, shared by the designer and standalone exports.

The serial, TCP and MQTT links expose the same signals. The hub forwards all of them on
one surface, so bindings, charts, tables and log boxes never need to know which link a
frame came from, and a command goes out over every link that is currently connected.
"""
from functools import partial

from PyQt5.QtCore import QObject, pyqtSignal

from serial_handler import SerialHandler
from tcp_handler import TcpHandler
from mqtt_handler import MqttHandler

LINK_NAMES = ("serial", "tcp", "mqtt")


def shared_link_config(config):
    """The frame format belongs to the device, not to the link carrying its bytes."""
    return {key: config[key] for key in ("parser", "parserConfig") if key in config}


class CommHub(QObject):
    dataReceived = pyqtSignal(dict)
    rawReceived = pyqtSignal(bytes)
    dataSent = pyqtSignal(bytes)
    connectionChanged = pyqtSignal(bool)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.serial = SerialHandler(self)
        self.tcp = TcpHandler(self)
        self.mqtt = MqttHandler(self)
        self.raw_encoding = "utf-8"  # of the bytes rawReceived is carrying right now
        for link in self.links:
            link.dataReceived.connect(self.dataReceived)
            link.rawReceived.connect(partial(self._forward_raw, link))
            link.dataSent.connect(self.dataSent)
            link.connected.connect(self.connected)
            link.disconnected.connect(self.disconnected)
            link.error.connect(self.error)
            link.connectionChanged.connect(self._on_link_state)
        if config:
            self.configure(config)

    def _forward_raw(self, link, data):
        # Raw bytes carry no link, so the encoding of the link they came from rides alongside.
        self.raw_encoding = link.text_encoding
        self.rawReceived.emit(data)

    def decode_raw(self, data):
        """The text of bytes just published by rawReceived, in their link's encoding."""
        return data.decode(self.raw_encoding, errors="replace")

    @property
    def links(self):
        return (self.serial, self.tcp, self.mqtt)

    def link(self, name):
        if name not in LINK_NAMES:
            raise ValueError(f"未知链路: {name}")
        return getattr(self, name)

    def configure(self, config):
        self.serial.configure(config)
        shared = shared_link_config(config)
        self.tcp.configure(shared)
        self.mqtt.configure(shared)

    @property
    def is_connected(self):
        return any(link.is_connected for link in self.links)

    @property
    def connected_links(self):
        return [link for link in self.links if link.is_connected]

    def send(self, data):
        """Deliver to every connected link; True once at least one accepted the whole payload."""
        targets = self.connected_links
        if not targets:
            return False
        return any([link.send(data) for link in targets])

    def send_text(self, text, encoding="utf-8"):
        return self.send(text.encode(encoding))

    def disconnect(self):
        for link in self.links:
            link.disconnect()

    def _on_link_state(self, _state):
        self.connectionChanged.emit(self.is_connected)
