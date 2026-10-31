"""The Modbus polling settings and status every link card (serial, TCP, MQTT) has, shared by the
designer preview and exported applications.

Every link card hands the running application's Modbus poller (modbus_poller.py) its 默认轮询(ms),
响应超时(ms) and 默认从站 (``modbusPeriod``, ``modbusTimeout``, ``modbusSlave``), which count while the
card is the first in the document whose link is connected and parses Modbus. While its link is
connected, parses Modbus and can send (a TCP server needs a client), the card's status reads
``<connection> · <poller status>``, with the poller's blocks as its tooltip; 等待连接 is never shown
there.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QSizePolicy
from qfluentwidgets import CaptionLabel

from .signal_lifetime import SignalConnections

MODBUS_DEFAULTS = (500, 1000, 1)  # modbusPeriod, modbusTimeout, modbusSlave: the poller's own defaults
MODBUS_RANGES = ((10, 60000), (10, 60000), (1, 247))


def status_label(text):
    """The status of a link card's title row: it takes the room the title leaves, so a long one (the
    Modbus poller's) never squeezes the title or widens the card; what does not fit is cut at the left."""
    label = CaptionLabel(text)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return label


def _modbus_setting(index, value):
    """A whole number within the setting's range; its default for what is not a number."""
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return MODBUS_DEFAULTS[index]
    low, high = MODBUS_RANGES[index]
    return min(max(number, low), high)


class ModbusLinkSettings:
    """The Modbus polling settings of a link card, and the poller's status on its status line.

    The card calls ``_init_modbus()`` while it is built and ``_with_poll_status(text)`` for its
    status while connected, and has ``_handler`` (its link), ``_connected`` and
    ``_show_connected()``, which shows the connected status again."""

    def _init_modbus(self):
        self._modbus_settings = MODBUS_DEFAULTS
        self._modbus_poller = None
        self._poll_shown = False  # the status shows the poller's
        self._poller_connections = SignalConnections(self)

    @property
    def link(self):
        """The card's link: whether it is connected and parses Modbus decides whose settings count."""
        return self._handler

    @property
    def modbus_settings(self):
        """(默认轮询 ms, 响应超时 ms, 默认从站) for the Modbus poller."""
        return self._modbus_settings

    def set_modbus_period(self, value):
        self._set_modbus_setting(0, value)

    def set_modbus_timeout(self, value):
        self._set_modbus_setting(1, value)

    def set_modbus_slave(self, value):
        self._set_modbus_setting(2, value)

    def _set_modbus_setting(self, index, value):
        settings = list(self._modbus_settings)
        settings[index] = _modbus_setting(index, value)
        self._modbus_settings = tuple(settings)
        if self._modbus_poller is not None:
            self._modbus_poller.settings_changed()  # counts at once

    def set_modbus_poller(self, poller):
        """The running application's Modbus poller: this card hands it its settings, in document
        order, and shows its status while the card's link is connected and parses Modbus."""
        if poller is self._modbus_poller:
            return
        self._poller_connections.clear()
        self._modbus_poller = poller
        if poller is not None:
            self._poller_connections.connect(poller.statusChanged, self._on_poll_status)
            poller.add_link_card(self)
        self._on_poll_status()

    def _on_poll_status(self, *_):
        """A card that shows the poller's status, or can show it now, shows it again; the others
        keep what they show (an error, say)."""
        poller = self._modbus_poller
        can_show = poller is not None and bool(poller.shown_status(self._handler))
        if self._connected and (self._poll_shown or can_show):
            self._show_connected()

    def _with_poll_status(self, text):
        """``text``, which describes the connection, then `` · `` and the poller's status while the
        link parses Modbus and can send; and the tooltip for it: the poller's blocks, one per line, or the whole
        text without blocks. The tooltip is None when the poller's status is not shown."""
        poller = self._modbus_poller
        status = poller.shown_status(self._handler) if poller is not None else ""
        self._poll_shown = bool(status)
        if not status:
            return text, None
        text = f"{text} · {status}"
        return text, poller.tooltip() if poller.blocks() else text
