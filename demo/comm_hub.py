"""One hub for every communication link, shared by the designer and standalone exports.

The hub owns no link: every link card (serial, TCP, MQTT) owns its own and registers it here
(``add_link``), in document order, and takes it off again (``remove_link``) when the card lets it
go; a link that is destroyed leaves by itself. A project may hold any number of cards of one kind,
each with a link of its own. The links expose the same signals and the hub forwards all of them on
one surface, so bindings, charts, tables and log boxes never need to know which link a frame came
from, and a command goes out over every link that is currently connected. A serial or TCP link
answering as a Modbus slave adds its log lines (slaveLog) and publishes its slave messages on
dataReceived like parsed frames, with slave_data set meanwhile.
"""
from functools import partial

from PyQt5.QtCore import QObject, pyqtSignal


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
    slaveLog = pyqtSignal(str, str)  # a slave's log line and its level
    linksChanged = pyqtSignal()  # a link was registered or taken off

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self._links = []        # the registered links, in the order they came
        self._connections = {}  # id(link) -> its forwarding connections
        self._config = None     # the project's serial settings, once configured
        self.raw_encoding = "utf-8"  # of the bytes rawReceived is carrying right now
        if config:
            self.configure(config)

    @property
    def links(self):
        """The registered links, in the order they were registered."""
        return list(self._links)

    def add_link(self, link):
        """Register a link: its signals are forwarded and the project's settings, if any, apply to it."""
        if any(known is link for known in self._links):
            return
        self._links.append(link)
        connections = [
            (link.dataReceived, link.dataReceived.connect(self.dataReceived)),
            (link.rawReceived, link.rawReceived.connect(partial(self._forward_raw, link))),
            (link.dataSent, link.dataSent.connect(self.dataSent)),
            (link.connected, link.connected.connect(self.connected)),
            (link.disconnected, link.disconnected.connect(self.disconnected)),
            (link.error, link.error.connect(self.error)),
            (link.connectionChanged, link.connectionChanged.connect(self._on_link_state)),
            (link.destroyed, link.destroyed.connect(partial(self._forget, id(link)))),
        ]
        if hasattr(link, "slaveLog"):
            connections.append((link.slaveLog, link.slaveLog.connect(self.slaveLog)))
        self._connections[id(link)] = connections
        if self._config is not None:
            self._configure_link(link)
        self.linksChanged.emit()
        if link.is_connected:
            self.connectionChanged.emit(True)

    def remove_link(self, link):
        """Take a link off: the hub no longer forwards it, sends over it or disconnects it."""
        if not any(known is link for known in self._links):
            return
        for signal, connection in self._connections.pop(id(link), ()):
            try:
                signal.disconnect(connection)
            except (TypeError, RuntimeError):
                pass  # the link is going away already
        was_connected = link.is_connected
        self._links = [known for known in self._links if known is not link]
        self.linksChanged.emit()
        if was_connected:
            self.connectionChanged.emit(self.is_connected)

    def _forget(self, link_id, *_):
        """A registered link was destroyed: Qt dropped its connections, the hub drops the link."""
        self._connections.pop(link_id, None)
        self._links = [link for link in self._links if id(link) != link_id]
        try:
            self.linksChanged.emit()
            self.connectionChanged.emit(self.is_connected)
        except RuntimeError:
            pass  # the hub was destroyed first

    def _forward_raw(self, link, data):
        # Raw bytes carry no link, so the encoding of the link they came from rides alongside.
        self.raw_encoding = link.text_encoding
        self.rawReceived.emit(data)

    def decode_raw(self, data):
        """The text of bytes just published by rawReceived, in their link's encoding."""
        return data.decode(self.raw_encoding, errors="replace")

    def configure(self, config):
        """The project's serial settings, for the registered links and those registered later."""
        self._config = dict(config)
        for link in self._links:
            self._configure_link(link)

    def _configure_link(self, link):
        # A serial link takes the port settings too; TCP and MQTT only the frame format.
        port_settings = getattr(link, "uses_port_settings", False)
        link.configure(self._config if port_settings else shared_link_config(self._config))

    @property
    def slave_data(self):
        """dataReceived is carrying a slave message, not a frame a link received."""
        return any(getattr(link, "slave_data", False) for link in self._links)

    @property
    def is_connected(self):
        return any(link.is_connected for link in self._links)

    @property
    def connected_links(self):
        return [link for link in self._links if link.is_connected]

    def send(self, data):
        """Deliver to every connected link; True once at least one accepted the whole payload."""
        targets = self.connected_links
        if not targets:
            return False
        return any([link.send(data) for link in targets])

    def send_text(self, text, encoding="utf-8"):
        return self.send(text.encode(encoding))

    def disconnect(self):
        for link in list(self._links):
            link.disconnect()

    def _on_link_state(self, _state):
        self.connectionChanged.emit(self.is_connected)
