"""TCP client/server link shared by the designer and standalone exports.

Qt's own sockets keep everything on the GUI thread: no reader thread and no cross-thread
queue. A client is one byte stream with one parser. A server accepts any number of peers,
each with its own parser, so interleaved streams cannot corrupt each other's frames; a
command is written to every connected peer. A parser that frames by silence gets a
single-shot timer per stream, restarted by every read, that flushes it when it fires.
"""
from functools import partial

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer, QTcpSocket

from serial_handler import ModbusRequests, create_parser, text_encoding

CLIENT, SERVER = "客户端", "服务端"
_MODES = {CLIENT: CLIENT, SERVER: SERVER, "client": CLIENT, "server": SERVER}


def tcp_mode(value):
    text = str(value).strip()
    mode = _MODES.get(text) or _MODES.get(text.lower())
    if mode is None:
        raise ValueError(f"未知 TCP 模式: {value}")
    return mode


class TcpHandler(QObject):
    text_encoding = "utf-8"  # of the text this link receives, for the receive log
    dataReceived = pyqtSignal(dict)
    rawReceived = pyqtSignal(bytes)
    dataSent = pyqtSignal(bytes)
    connectionChanged = pyqtSignal(bool)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    error = pyqtSignal(str)
    peersChanged = pyqtSignal(int)  # server mode: number of connected clients
    DEFAULT_CONFIG = {}

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self._socket = None
        self._server = None
        self._peers = {}  # peer socket -> its parser
        self._idle_timers = {}  # parser -> the timer that flushes it, for parsers that frame by silence
        self._parser = None
        self._parser_setup = ("line", {})
        self.modbus_requests = ModbusRequests()  # shared by every peer's parser
        self._mode = CLIENT
        self._description = ""
        self._pending_error = ""
        self._announced = False  # connected() emitted for the current client socket
        self.configure(config or self.DEFAULT_CONFIG)

    def configure(self, config):
        self._config = {"mode": CLIENT, "host": "127.0.0.1", "port": 8080,
                        "parser": "line", "parserConfig": {"separator": ","}, **config}
        self._parser_setup = (self._config["parser"], self._config["parserConfig"])

    @property
    def parser_type(self):
        """The parser in use; Modbus commands are framed to match (MBAP for modbus_tcp, ASCII for modbus_ascii)."""
        return self._parser_setup[0]

    @property
    def is_connected(self):
        if self._server is not None:
            return self._server.isListening()
        return (self._socket is not None
                and self._socket.state() == QAbstractSocket.ConnectedState)

    @property
    def is_active(self):
        """Listening, connected, or still connecting."""
        return self._server is not None or self._socket is not None

    @property
    def mode(self):
        return self._mode

    @property
    def peer_count(self):
        return len(self._peers)

    @property
    def port(self):
        """The real port: a server that asked for port 0 gets one from the system."""
        if self._server is not None:
            return self._server.serverPort()
        if self._socket is not None:
            return self._socket.peerPort()
        return int(self._config["port"])

    @property
    def description(self):
        return self._description

    def connect(self, host=None, port=None, mode=None, parser_type=None, parser_config=None):
        """Start connecting (client) or listening (server).

        A server is up when this returns True. A client only begins its attempt: the
        ``connected`` signal reports success, ``error`` then ``disconnected`` a failure.
        """
        cfg = self._config
        try:
            mode = tcp_mode(mode if mode is not None else cfg["mode"])
            port = int(port if port is not None else cfg["port"])
            if not 0 <= port <= 65535 or (mode == CLIENT and port == 0):
                raise ValueError("端口必须在 1–65535 之间")
            selected_parser = parser_type if parser_type is not None else cfg["parser"]
            selected_config = parser_config
            if selected_config is None:
                selected_config = cfg["parserConfig"] if selected_parser == cfg["parser"] else {}
            parser = create_parser(selected_parser, selected_config, self.modbus_requests)
        except (TypeError, ValueError) as exc:
            self.error.emit(f"TCP 参数无效: {exc}")
            return False
        host = str(host if host is not None else cfg["host"]).strip()
        if mode == CLIENT and not host:
            self.error.emit("TCP 参数无效: 请填写服务器地址")
            return False
        if self.is_active:
            self.disconnect()
        self._parser_setup = (selected_parser, selected_config)
        self._parser = parser
        self.text_encoding = text_encoding(selected_parser, selected_config)
        self._mode = mode
        if mode == CLIENT:
            self._watch_idle(parser)
        if mode == SERVER:
            return self._listen(host, port)
        socket = QTcpSocket(self)
        socket.connected.connect(partial(self._on_client_connected, socket))
        socket.disconnected.connect(partial(self._on_client_disconnected, socket))
        socket.readyRead.connect(partial(self._on_client_ready_read, socket))
        socket.errorOccurred.connect(partial(self._on_client_error, socket))
        self._socket = socket
        self._announced = False
        self._description = f"TCP {host}:{port}"
        socket.connectToHost(host, port)
        return True

    def _listen(self, host, port):
        if not host or host in ("0.0.0.0", "*"):
            address, shown = QHostAddress(QHostAddress.Any), "0.0.0.0"
        else:
            address, shown = QHostAddress(host), host
            if address.isNull():
                self.error.emit(f"TCP 参数无效: 监听地址必须是本机 IP，不能是 {host!r}")
                return False
        server = QTcpServer(self)
        if not server.listen(address, port):
            message = server.errorString()
            server.deleteLater()
            self.error.emit(f"TCP 监听失败: {message}")
            return False
        server.newConnection.connect(partial(self._on_new_connection, server))
        self._server = server
        self._description = f"TCP 服务端 {shown}:{server.serverPort()}"
        self.connected.emit(self._description)
        self.connectionChanged.emit(True)
        return True

    def disconnect(self):
        socket, server, peers = self._socket, self._server, list(self._peers)
        self._socket = self._server = None
        self._peers = {}
        self._pending_error = ""
        for timer in self._idle_timers.values():
            timer.stop()
            timer.deleteLater()
        self._idle_timers = {}
        for peer in peers:
            self._drop(peer)
        if peers:
            self.peersChanged.emit(0)
        if server is not None:
            server.close()
            server.deleteLater()
        if socket is not None:
            self._drop(socket)
        if socket is not None or server is not None:
            self.disconnected.emit()
            self.connectionChanged.emit(False)

    @staticmethod
    def _drop(socket):
        # Slots compare the sender against the current socket, so whatever abort()
        # emits for this retired one is ignored.
        socket.flush()
        socket.abort()
        socket.deleteLater()

    def send(self, data):
        """Return success only after every target accepted the entire payload."""
        if not self.is_connected:
            return False
        self.modbus_requests.note_frame(data, self.parser_type)
        try:
            if self._server is not None:
                peers = [peer for peer in self._peers
                         if peer.state() == QAbstractSocket.ConnectedState]
                if not peers:
                    raise OSError("没有已连接的 TCP 客户端")
                for peer in peers:
                    self._write(peer, data)
            else:
                self._write(self._socket, data)
        except Exception as exc:
            self.error.emit(f"发送失败: {exc}")
            return False
        self.dataSent.emit(bytes(data))
        return True

    @staticmethod
    def _write(socket, data):
        written = socket.write(bytes(data))
        if written != len(data):
            raise OSError(f"TCP 仅写入 {written}/{len(data)} 字节")
        socket.flush()

    def send_text(self, text, encoding="utf-8"):
        return self.send(text.encode(encoding))

    # ---- client ----

    def _on_client_connected(self, socket):
        if socket is not self._socket:
            return
        self._announced = True
        self.connected.emit(self._description)
        self.connectionChanged.emit(True)

    def _on_client_ready_read(self, socket):
        if socket is self._socket:
            self._feed(self._parser, bytes(socket.readAll()))

    def _on_client_error(self, socket, code):
        if socket is not self._socket:
            return
        if code == QAbstractSocket.RemoteHostClosedError:
            # Qt reports the peer closing as an error; its disconnected signal follows.
            self._pending_error = "TCP 连接已被对方关闭"
            return
        # A refused loopback connect can pass through the connected state on macOS before
        # the error arrives, so word the failure by what this link has announced.
        message = socket.errorString()
        if self._announced:
            self.error.emit(f"TCP 连接错误: {message}")
        else:
            self.error.emit(f"TCP 连接失败: {message}")
        self.disconnect()

    def _on_client_disconnected(self, socket):
        if socket is not self._socket:
            return
        if self._pending_error:
            self.error.emit(self._pending_error)
        self.disconnect()

    # ---- server ----

    def _on_new_connection(self, server):
        if server is not self._server:
            return
        while server.hasPendingConnections():
            peer = server.nextPendingConnection()
            if peer is None:
                break
            self._peers[peer] = parser = create_parser(*self._parser_setup, self.modbus_requests)
            self._watch_idle(parser)
            peer.readyRead.connect(partial(self._on_peer_ready_read, peer))
            peer.disconnected.connect(partial(self._on_peer_disconnected, peer))
            self.peersChanged.emit(len(self._peers))

    def _on_peer_ready_read(self, peer):
        parser = self._peers.get(peer)
        if parser is not None:
            self._feed(parser, bytes(peer.readAll()))

    def _on_peer_disconnected(self, peer):
        parser = self._peers.pop(peer, None)
        if parser is None:
            return
        timer = self._idle_timers.pop(parser, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        peer.deleteLater()
        self.peersChanged.emit(len(self._peers))

    # ---- receiving ----

    def _watch_idle(self, parser):
        if parser.idle_timeout <= 0:
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(parser.idle_timeout)
        timer.timeout.connect(partial(self._on_idle, parser))
        self._idle_timers[parser] = timer

    def _on_idle(self, parser):
        if parser in self._idle_timers:  # not a stream that has since been closed
            self._publish(parser, parser.flush())

    def _feed(self, parser, data):
        if not data:
            return
        self._publish(parser, parser.frames(data))
        timer = self._idle_timers.get(parser)
        if timer is not None:
            timer.start()

    def _publish(self, parser, units):
        for unit in units:
            self.rawReceived.emit(unit)
            for parsed in parser.parse(unit):
                self.dataReceived.emit(parsed)

TcpHandler.DEFAULT_CONFIG = {'parser': 'line', 'parserConfig': {'separator': ','}}
