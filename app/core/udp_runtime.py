"""UDP link shared by the designer and standalone exports.

Qt's own socket keeps everything on the GUI thread, as with TCP. The link binds a local port (0: the
system picks one) and is "connected" once bound. A command goes out as one datagram to the remote
host:port, or, with no remote set, to the sender of the last datagram received; before any has
arrived there is no one to send to.

Each sender address:port is one stream with its own parser, as each TCP server peer is, and each
datagram is a complete read, as an MQTT message is: a line-mode datagram without a trailing
terminator is still parsed, and a parser that frames by silence is flushed as soon as the datagram
has been read. A socket error after binding (an ICMP port unreachable) is reported and the link
stays open.

Connected with a card's slave (slave_runtime.ModbusSlaveDevice) while it parses modbus or modbus_tcp, the
link answers the requests it reads instead of parsing replies: each sender's stream frames its own, and a
reply goes back as one datagram to the sender of its request, whether or not a remote is set.
"""
from functools import partial

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtNetwork import QAbstractSocket, QHostAddress, QHostInfo, QUdpSocket

from .protocol_parser import ModbusRequests, create_parser, text_encoding
from .modbus_master import ModbusMaster
from .modbus_slave import SLAVE_PARSERS
from .i18n import tr

MAX_DATAGRAM = 65507  # the largest UDP payload over IPv4
MAX_STREAMS = 256     # senders with a parser of their own; one more starts over
SEND_BUFFER = 66560   # the send buffer a bound socket gets at least


def resolve_host(host):
    """The address of ``host``: an IP literal as is, a name looked up now (the first IPv4 address, else the
    first); None when it cannot be resolved."""
    address = QHostAddress(host)
    if not address.isNull():
        return address
    info = QHostInfo.fromName(host)
    addresses = info.addresses() if info.error() == QHostInfo.NoError else []
    if not addresses:
        return None
    return next((a for a in addresses if a.protocol() == QAbstractSocket.IPv4Protocol), addresses[0])


class UdpHandler(QObject):
    text_encoding = "utf-8"  # of the text this link receives, for the receive log
    slave_data = False  # True while dataReceived carries a slave message (publish_slave_data)
    dataReceived = pyqtSignal(dict)
    rawReceived = pyqtSignal(bytes)
    dataSent = pyqtSignal(bytes)
    connectionChanged = pyqtSignal(bool)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    error = pyqtSignal(str)
    canSendChanged = pyqtSignal(bool)  # no remote set: the first datagram gave the link someone to send to
    slaveLog = pyqtSignal(str, str)  # a slave's log line and its level
    DEFAULT_CONFIG = {}

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self._socket = None
        self._remote = None       # (QHostAddress, port), or None: reply to the last sender
        self._last_sender = None  # (QHostAddress, port) of the last datagram received
        self._streams = {}        # (address text, port) -> (its parser, (QHostAddress, port))
        self._writing = False     # in writeDatagram, which reports its own failure
        self._parser_setup = ("line", {})
        self.modbus_requests = ModbusRequests()  # shared by every sender's parser
        self.modbus_master = ModbusMaster(self)  # one Modbus request at a time, answered by any sender
        self.slave_device = None  # the slave answering on this link while it is connected as one
        self._description = ""
        self.configure(config or self.DEFAULT_CONFIG)

    def configure(self, config):
        self._config = {"localPort": 0, "host": "127.0.0.1", "port": 8080,
                        "parser": "line", "parserConfig": {"separator": ","}, **config}
        self._parser_setup = (self._config["parser"], self._config["parserConfig"])

    @property
    def parser_type(self):
        """The parser in use; Modbus commands are framed to match (MBAP for modbus_tcp, ASCII for modbus_ascii)."""
        return self._parser_setup[0]

    @property
    def is_connected(self):
        return self._socket is not None and self._socket.state() == QAbstractSocket.BoundState

    @property
    def is_active(self):
        """Bound."""
        return self._socket is not None

    @property
    def slave_active(self):
        """Answering as a Modbus slave: the poller and Modbus commands leave this link alone."""
        return self.slave_device is not None

    def publish_slave_data(self, message):
        """A slave message, published like a parsed frame; slave_data tells the log box to leave it out."""
        self.slave_data = True
        try:
            self.dataReceived.emit(message)
        finally:
            self.slave_data = False

    @property
    def can_send(self):
        """Bound, with a remote set or a datagram received to reply to."""
        return self.is_connected and (self._remote is not None or self._last_sender is not None)

    @property
    def local_port(self):
        """The real local port: one asked for as 0 is picked by the system."""
        if self._socket is not None:
            return self._socket.localPort()
        return int(self._config["localPort"])

    @property
    def description(self):
        return self._description

    def connect(self, local_port=None, host=None, port=None, parser_type=None, parser_config=None,
                slave=None):
        """Bind the local port; the link is up (``connected``) when this returns True."""
        cfg = self._config
        try:
            local_port = int(local_port if local_port is not None else cfg["localPort"])
            if not 0 <= local_port <= 65535:
                raise ValueError(f"{tr('本地端口')} {local_port}")
            host = str(host if host is not None else cfg["host"]).strip()
            port = int(port if port is not None else cfg["port"])
            if host and not 1 <= port <= 65535:
                raise ValueError(tr("端口必须在 1–65535 之间"))
            if not host and local_port == 0:  # no one could reach it, and it sends nowhere
                raise ValueError(tr("请填写远程地址或本地端口"))
            selected_parser = parser_type if parser_type is not None else cfg["parser"]
            selected_config = parser_config
            if selected_config is None:
                selected_config = cfg["parserConfig"] if selected_parser == cfg["parser"] else {}
            if selected_parser not in SLAVE_PARSERS:
                slave = None  # another mode: the card's slave settings do not count
            if slave is None:
                create_parser(selected_parser, selected_config)
        except (TypeError, ValueError) as exc:
            self.error.emit(tr("UDP 参数无效: %1", exc))
            return False
        remote = None
        if host:
            address = resolve_host(host)
            if address is None:
                self.error.emit(tr("UDP 参数无效: %1", tr("无法解析地址 %1", host)))
                return False
            remote = (address, port)
        if self.is_active:
            self.disconnect()
        ipv6 = remote is not None and remote[0].protocol() == QAbstractSocket.IPv6Protocol
        socket = QUdpSocket(self)
        if not socket.bind(QHostAddress(QHostAddress.Any if ipv6 else QHostAddress.AnyIPv4), local_port):
            message = socket.errorString()
            socket.deleteLater()
            self.error.emit(tr("UDP 绑定失败: %1", message))
            return False
        # macOS sends no datagram larger than its 9216-byte default send buffer: room for the largest one.
        try:
            size = int(socket.socketOption(QAbstractSocket.SendBufferSizeSocketOption) or 0)
        except (TypeError, ValueError):
            size = 0
        if size < SEND_BUFFER:
            socket.setSocketOption(QAbstractSocket.SendBufferSizeSocketOption, SEND_BUFFER)
        socket.readyRead.connect(partial(self._on_ready_read, socket))
        socket.errorOccurred.connect(partial(self._on_error, socket))
        self._socket = socket
        self._remote = remote
        self._last_sender = None
        self._streams = {}
        self._parser_setup = (selected_parser, selected_config)
        self.text_encoding = text_encoding(selected_parser, selected_config)
        self.slave_device = slave
        if slave is not None:
            slave.begin(self, selected_parser)
        target = f"{host}:{port}" if remote is not None else tr("最后发送方")
        self._description = f"UDP :{socket.localPort()} → {target}"
        self.connected.emit(self._description)
        self.connectionChanged.emit(True)
        return True

    def disconnect(self):
        socket = self._socket
        if socket is None:
            return
        self._socket = self._remote = self._last_sender = None
        self._streams = {}
        socket.close()
        socket.deleteLater()
        if self.slave_device is not None:
            self.slave_device.end()  # drops the replies not sent yet
            self.slave_device = None
        self.disconnected.emit()
        self.connectionChanged.emit(False)

    def send(self, data):
        """One datagram to the remote, or to the last sender; False when there is no one to send to yet."""
        target = self._remote or self._last_sender
        if not self.is_connected or target is None:
            return False
        payload = bytes(data)
        if len(payload) > MAX_DATAGRAM:
            self.error.emit(tr("UDP 数据报过大: %1 字节（最多 65507）", len(payload)))
            return False
        self.modbus_requests.note_frame(payload, self.parser_type)
        if not self._write(target, payload):
            return False
        self.dataSent.emit(payload)
        return True

    def _write(self, target, payload):
        self._writing = True
        try:
            written = self._socket.writeDatagram(payload, *target)
        finally:
            self._writing = False
        if written != len(payload):
            self.error.emit(tr("发送失败: %1", self._socket.errorString()))
            return False
        return True

    def send_text(self, text, encoding="utf-8"):
        return self.send(text.encode(encoding))

    # ---- receiving ----

    def _on_error(self, socket, _code):
        # A failed write reports itself; any other error (an ICMP port unreachable read in place of a
        # datagram) leaves the link open.
        if socket is self._socket and not self._writing:
            self.error.emit(tr("UDP 错误: %1", socket.errorString()))

    def _on_ready_read(self, socket):
        while socket is self._socket and socket.hasPendingDatagrams():
            datagram = socket.receiveDatagram()
            if not datagram.isValid():
                break  # an error read in place of a datagram: reported by errorOccurred, and now cleared
            data = bytes(datagram.data())
            if data:
                self._receive((datagram.senderAddress(), datagram.senderPort()), data)

    def _receive(self, sender, data):
        could_send = self.can_send
        self._last_sender = sender
        key = (sender[0].toString(), sender[1])
        stream = self._streams.get(key)
        if stream is None:
            if len(self._streams) >= MAX_STREAMS:
                self._streams = {}
            if self.slave_device is not None:  # each sender's requests are framed apart
                parser = self.slave_device.framer(self.parser_type)
            else:
                parser = create_parser(*self._parser_setup, self.modbus_requests)
            stream = self._streams[key] = (parser, sender)
        if not could_send:
            self.canSendChanged.emit(True)
        parser = stream[0]
        units = parser.frames(data)
        if parser.idle_timeout > 0:
            units += parser.flush()
        for unit in units:
            self.rawReceived.emit(unit)
            message = unit
            if self.slave_device is None and self.parser_type == "line" and not unit.endswith(parser.terminator):
                message = unit + parser.terminator
            for parsed in parser.parse(message):
                self.dataReceived.emit(parsed)
            if self.slave_device is not None:  # a request the slave answers to its sender
                self.slave_device.receive(unit, partial(self._send_reply, parser))

    def _send_reply(self, parser, data):
        """A slave's reply, as one datagram to the sender whose parser framed the request, with no read noted
        for it. False once that stream is gone."""
        sender = next((sender for framer, sender in self._streams.values() if framer is parser), None)
        if sender is None or not self.is_connected:
            return False
        if not self._write(sender, bytes(data)):
            return False
        self.dataSent.emit(bytes(data))
        return True
