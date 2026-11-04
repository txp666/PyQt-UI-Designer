"""The Modbus polling settings and status every link card (serial, TCP, MQTT) has, shared by the
designer preview and exported applications.

Every link card hands the running application's Modbus poller (modbus_poller.py) its 默认轮询(ms),
响应超时(ms) and 默认从站 (``modbusPeriod``, ``modbusTimeout``, ``modbusSlave``), which count while the
card is the first in the document whose link is connected and parses Modbus. While its link is
connected, parses Modbus and can send (a TCP server needs a client), the card's status reads
``<connection> · <poller status>``, with the poller's blocks as its tooltip; 等待连接 is never shown
there.

A serial or TCP card also has a Modbus role (ModbusSlaveSettings). As 从站 it owns a slave data table
(slave_runtime.ModbusSlaveDevice) and connects its link as a slave whenever the link parses modbus or
modbus_tcp; while the link answers, the card shows ``<connection> · 从站 S · 应答 N`` in place of the
poller's status.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QSizePolicy
from qfluentwidgets import CaptionLabel

from .signal_lifetime import SignalConnections
from .slave_runtime import ModbusSlaveDevice
from .modbus_slave import SLAVE_ROLE

MODBUS_DEFAULTS = (500, 1000, 1)  # modbusPeriod, modbusTimeout, modbusSlave: the poller's own defaults
MODBUS_RANGES = ((10, 60000), (10, 60000), (1, 247))
SLAVE_DELAY_RANGE = (0, 5000)  # 响应延时(ms)
SLAVE_START_RANGE, SLAVE_COUNT_RANGE = (0, 65535), (0, 10000)  # 起始 / 数量 of an area


def status_label(text):
    """The status of a link card's title row: it takes the room the title leaves, so a long one (the
    Modbus poller's) never squeezes the title or widens the card; what does not fit is cut at the left."""
    label = CaptionLabel(text)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return label


def _whole(value, default, low, high):
    """A whole number within low–high; the default for what is not a number."""
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return min(max(number, low), high)


def _modbus_setting(index, value):
    """A whole number within the setting's range; its default for what is not a number."""
    return _whole(value, MODBUS_DEFAULTS[index], *MODBUS_RANGES[index])


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
        text without blocks. The tooltip is None when the poller's status is not shown. While the link answers
        as this card's slave, the slave's status takes the poller's place."""
        slave = getattr(self._handler, "slave_device", None)
        if slave is not None and slave is getattr(self, "_slave_device", None):
            self._poll_shown = False
            text = f"{text} · {slave.status_text()}"
            return text, text
        poller = self._modbus_poller
        status = poller.shown_status(self._handler) if poller is not None else ""
        self._poll_shown = bool(status)
        if not status:
            return text, None
        text = f"{text} · {status}"
        return text, poller.tooltip() if poller.blocks() else text


class ModbusSlaveSettings(ModbusLinkSettings):
    """The Modbus role of a serial or TCP card (``modbusRole``), set at design time, and the slave settings
    that count in the 从站 role: 响应延时(ms), 异常响应, the four areas and 初始值, with 默认从站 as this
    slave's address. ``slave_device`` is the card's slave, None in the 主站 role; the card passes it to its
    link's connect(), which answers with it while it parses modbus or modbus_tcp."""

    def _init_modbus(self):
        super()._init_modbus()
        self._modbus_role = "主站"
        self._slave_device = ModbusSlaveDevice(self)
        self._slave_device.written.connect(self._on_slave_written)
        self._slave_device.statusChanged.connect(self._on_slave_status)

    @property
    def slave_device(self):
        return self._slave_device if self._modbus_role == SLAVE_ROLE else None

    def set_modbus_role(self, value):
        self._modbus_role = SLAVE_ROLE if value == SLAVE_ROLE else "主站"

    def set_modbus_slave(self, value):
        super().set_modbus_slave(value)
        self._slave_device.address = self._modbus_settings[2]

    def set_modbus_delay(self, value):
        self._slave_device.delay = _whole(value, 0, *SLAVE_DELAY_RANGE)

    def set_modbus_exceptions(self, value):
        self._slave_device.exceptions = bool(value)

    def _set_slave_start(self, table, value):
        self._slave_device.set_area(table, start=_whole(value, 0, *SLAVE_START_RANGE))

    def _set_slave_count(self, table, value):
        self._slave_device.set_area(table, count=_whole(value, 100, *SLAVE_COUNT_RANGE))

    def set_slave_co_start(self, value): self._set_slave_start("co", value)
    def set_slave_co_count(self, value): self._set_slave_count("co", value)
    def set_slave_di_start(self, value): self._set_slave_start("di", value)
    def set_slave_di_count(self, value): self._set_slave_count("di", value)
    def set_slave_hr_start(self, value): self._set_slave_start("hr", value)
    def set_slave_hr_count(self, value): self._set_slave_count("hr", value)
    def set_slave_ir_start(self, value): self._set_slave_start("ir", value)
    def set_slave_ir_count(self, value): self._set_slave_count("ir", value)

    def set_slave_init(self, value):
        self._slave_device.set_init(value)

    def _on_slave_written(self, message):
        """A write to the data table: published on the card's link, connected or not, like a frame it read."""
        publish = getattr(self._handler, "publish_slave_data", None)
        if publish is not None and self.slave_device is not None:
            publish(message)

    def _on_slave_status(self):
        if self._connected and getattr(self._handler, "slave_device", None) is self._slave_device:
            self._show_connected()


# The slave settings of PROPERTY_SETTERS, after the role and the polling settings.
SLAVE_PROPERTY_SETTERS = (
    ("modbusDelay", "set_modbus_delay", 0),
    ("modbusExceptions", "set_modbus_exceptions", True),
    ("slaveCoStart", "set_slave_co_start", 0),
    ("slaveCoCount", "set_slave_co_count", 100),
    ("slaveDiStart", "set_slave_di_start", 0),
    ("slaveDiCount", "set_slave_di_count", 100),
    ("slaveHrStart", "set_slave_hr_start", 0),
    ("slaveHrCount", "set_slave_hr_count", 100),
    ("slaveIrStart", "set_slave_ir_start", 0),
    ("slaveIrCount", "set_slave_ir_count", 100),
    ("slaveInit", "set_slave_init", ""),
)
