# coding: utf-8
"""Auto-generated data binding."""
import struct
from PyQt5.QtCore import QSignalBlocker
from ui import RealtimeLineChart

"""Conversions shared by live bindings and standalone exported applications."""
import math
import struct


def binding_integer(value):
    """Accept integer-compatible values that fit Qt's signed 32-bit API."""
    number = int(value)
    if not -(2 ** 31) <= number < 2 ** 31:
        raise OverflowError("绑定整数超出 Qt 支持的范围")
    return number


def binding_float(value):
    """Reject NaN/infinity before passing a sample to a numeric widget."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("绑定数值必须是有限数")
    return number


def binding_register(value):
    """Modbus register payloads must be unsigned 16-bit integers."""
    if not isinstance(value, int) or not 0 <= value <= 65535:
        raise ValueError("Modbus 寄存器值必须是 0 到 65535 的整数")
    return value


# Where a Modbus binding or chart curve reads: a register table, whose registers a reply names by
# address (hr100), from the request it answers. 保持寄存器 when a binding names none.
MODBUS_AREAS = {"保持寄存器": "hr", "输入寄存器": "ir", "线圈": "co", "离散输入": "di"}
DEFAULT_MODBUS_AREA = "保持寄存器"
# The registers a value of each type takes; coils and discrete inputs are one bit each.
MODBUS_REGISTERS = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}


def modbus_need(area, address, data_type="uint16", slave_filter=-1, period=0):
    """What a Modbus binding or chart curve reads, for the Modbus poller:
    ``(slave, table, address, count, period)``, or None for an area that is not a register table.
    A slave of 0 or less stands for the poller's default slave, a period of 0 for its default period."""
    table = MODBUS_AREAS.get(area)
    if table is None:
        return None
    count = 1 if table in ("co", "di") else MODBUS_REGISTERS.get(data_type, 1)
    return int(slave_filter), table, int(address), count, max(0, min(60000, int(period)))


def modbus_value(data, address, data_type="uint16", reg_order="大端(AB CD)",
                 fc_filter=-1, slave_filter=-1, area=DEFAULT_MODBUS_AREA):
    """One value from a parsed Modbus response, or None when the response does not hold it.

    The value is the register (or coil, or discrete input) at ``address`` of the area's table,
    named by address in a reply to a read this program sent (hr100, co3). 32-bit types take the
    register at the address and the next one, which must be in the same response. Coils and
    discrete inputs are 0 or 1 whatever the data type.
    """
    if slave_filter >= 0 and data.get("slave") != slave_filter:
        return None
    fc = data.get("fc", 0)
    if fc_filter >= 0 and fc != fc_filter:
        return None
    table = MODBUS_AREAS.get(area)
    if table is None:
        return None
    if table in ("co", "di"):
        return data.get(f"{table}{address}")
    r0 = data.get(f"{table}{address}")
    if r0 is None:
        return None
    r0 = binding_register(r0)
    if data_type == "uint16":
        return r0
    if data_type == "int16":
        return r0 - 65536 if r0 > 32767 else r0
    r1 = data.get(f"{table}{address + 1}")
    if r1 is None:
        return None
    r1 = binding_register(r1)
    high, low = (r0, r1) if reg_order == "大端(AB CD)" else (r1, r0)
    raw = high.to_bytes(2, "big") + low.to_bytes(2, "big")
    if data_type == "uint32":
        return int.from_bytes(raw, "big")
    if data_type == "int32":
        return int.from_bytes(raw, "big", signed=True)
    if data_type == "float32":
        return struct.unpack(">f", raw)[0]
    return r0


def binding_boolean(value):
    """Read explicit boolean tokens or finite numbers; reject unknown text."""
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in ("true", "on", "yes"):
            return True
        if token in ("false", "off", "no"):
            return False
    return bool(binding_float(value))


def binding_decimals(value, places="自动"):
    """A number shown with a fixed count of decimal places; anything else (text, flags, NaN) as it came."""
    if places in ("自动", "", None) or isinstance(value, bool):
        if isinstance(value, float) and math.isfinite(value):
            # 15 significant digits: the noise of binary arithmetic (267 * 0.1 = 26.700000000000003)
            # goes, every digit a double really holds stays.
            return float(f"{value:.15g}")
        return value
    try:
        number = float(value)
        places = int(places)
    except (TypeError, ValueError, OverflowError):
        return value
    if not math.isfinite(number):
        return value
    return f"{number:.{places}f}"


def binding_led(value, on_value="1", off_value="0"):
    """Preserve custom LED states before falling back to boolean conversion."""
    text = str(value).strip()
    if text == on_value:
        return True
    if text == off_value:
        return False
    try:
        return binding_float(value) == binding_float(on_value)
    except (TypeError, ValueError, OverflowError):
        return binding_boolean(value)

"""Explicit Qt signal lifetimes, including compiled Python callables."""


class SignalConnections:
    """Disconnect external signals when their owning QObject is destroyed.

    PyQt cannot always infer the QObject receiver of a compiled bound method.
    Relays therefore have an explicit lifetime and release their callback before
    disconnecting, so already queued deliveries also become harmless.
    """

    def __init__(self, owner):
        self._connections = []
        owner.destroyed.connect(self.clear)

    def connect(self, signal, slot, *args, **kwargs):
        callback = [slot]

        def relay(*values):
            current = callback[0]
            if current is not None:
                current(*values)

        connection = signal.connect(relay, *args, **kwargs)
        self._connections.append((signal, connection, callback))
        return connection

    def clear(self, *_):
        connections, self._connections = self._connections, []
        for _signal, _connection, callback in connections:
            callback[0] = None
        for signal, connection, _callback in connections:
            try:
                signal.disconnect(connection)
            except (TypeError, RuntimeError):
                # The sender or its connection may already have been destroyed.
                pass

"""The Modbus poller of a running application, shared by the designer preview and exports.

Each running project has one poller. As soon as a link that parses Modbus can send (a TCP
server needs a client), it reads what the project's Modbus bindings and chart curves show:
before each request it gathers what the widgets on screen read, merges neighbouring addresses
into read blocks (modbus_master.plan_blocks) and sends the block that is due first; a block is
due again one period after it went out: the shortest 采集周期 (``mbPeriod``) of its bindings, or
the default period. Reads go only to the links that parse Modbus, through their ModbusMaster,
one request on the wire at a time, so a control's write goes out between two reads.

Its settings are the link cards' (serial, TCP, MQTT; link_card.ModbusLinkSettings): the first
card in document order whose link is connected and parses Modbus hands it its 默认轮询(ms)
(``modbusPeriod``), 响应超时(ms) (``modbusTimeout``) and 默认从站 (``modbusSlave``, read by the
bindings that filter no slave). Without such a card the period is 500 ms, a read waits 1000 ms
for its reply and the slave is 1. A change counts at once. A link card whose link is connected,
parses Modbus and can send shows the poller's status after its own.
"""
import time
from functools import partial

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal

from serial_handler import MODBUS_PARSERS, modbus_problem, plan_blocks


DEFAULT_PERIOD = 500    # ms: how often what sets no 采集周期 of its own is read
DEFAULT_TIMEOUT = 1000  # ms a read waits for its reply
DEFAULT_SLAVE = 1       # the slave of bindings that filter none (mbSlaveFilter 0 or less)
DUE_EARLY = 10          # ms: a block this close to due goes now, rather than a whole tick late
WAITING = "等待连接"    # the status while no link that parses Modbus can send; link cards do not show it


def modbus_block_tip(blocks):
    """The tooltip of the status: one line per block."""
    return "\n".join(f"从站 {slave} · 功能码 {fc} · 地址 {start}–{start + count - 1} · 周期 {period} ms"
                     for slave, fc, start, count, period in blocks)


def _relay(slot, read, result):
    if slot:  # emptied when the poller is destroyed; a master may still answer its last read
        slot[0](read, result)


def _forget(slot, *_):
    slot.clear()


def _forget_card(cards, card_id, *_):
    cards[:] = [card for card in cards if id(card) != card_id]  # by id: the slot keeps no card alive


def _can_send(link):
    """Connected, and with someone to send to (a TCP server needs a client)."""
    return getattr(link, "can_send", link.is_connected)


def _parses_modbus(link):
    """Connected, and parsing Modbus RTU, TCP or ASCII."""
    return (link is not None and link.is_connected
            and getattr(link, "parser_type", "") in MODBUS_PARSERS)


class _BlockRead:
    """The read of one block, sent over every link that can: done once the master of each link
    that queued it has answered, with the first success, else the first failure."""
    __slots__ = ("index", "block", "waiting", "success", "failure")

    def __init__(self, index, block):
        self.index, self.block, self.waiting = index, block, 0
        self.success = self.failure = None


class ModbusPoller(QObject):
    """Reads the Modbus bindings and chart curves of a running application, block by block.

    ``hub`` is the CommHub (or a single link) whose links it reads over; ``needs`` returns what
    the bindings and curves read, as data_binding's ``modbus_needs`` lists it. The runtime hands
    it the link cards in document order (``add_link_card``), calls ``start()`` once its widgets
    and bindings are up and ``stop()`` when it goes away.
    """

    statusChanged = pyqtSignal(str, str)  # the status, and its tooltip

    def __init__(self, hub, needs=None, parent=None):
        super().__init__(parent)
        self._hub = hub
        self._needs = needs
        self._period, self._timeout, self._slave = DEFAULT_PERIOD, DEFAULT_TIMEOUT, DEFAULT_SLAVE
        self._cards = []        # the link cards, in document order
        self._active = False    # between start() and stop()
        self._blocks = []       # the read blocks planned last: [slave, fc, start, count, period]
        self._due = {}          # block -> when it is due next (ms, _now)
        self._results = {}      # block index -> problem (None: answered) in this round
        self._round_status = None  # how the last round went
        self._read = None       # the block read awaiting its replies (_BlockRead)
        self._status = ("", "")  # nothing before start()
        self._reply_slot = [self._on_read_done]
        self.destroyed.connect(partial(_forget, self._reply_slot))
        self._link_connections = SignalConnections(self)
        self._timer = QTimer(self)
        # Each block keeps its own period; a coarse timer would let them drift by 5 %.
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    # -- what the runtime and the link cards call ---------------------------------

    def set_needs(self, needs):
        """What the bindings and curves read: a callable returning (widget_id, slave, table,
        address, count, period, visible) tuples."""
        self._needs = needs

    def add_link_card(self, card):
        """A link card, in document order: its ``link`` (the card's link, or None) and its
        ``modbus_settings`` (period, timeout, slave), which count while it is the first card
        whose link is connected and parses Modbus."""
        if any(known is card for known in self._cards):
            return
        self._cards.append(card)
        card.destroyed.connect(partial(_forget_card, self._cards, id(card)))
        self._tick()  # its settings may count already

    def settings_changed(self):
        """A link card's settings changed: they count at once. A block whose period changes is a
        new block, read right away; a new timeout counts from the next read on."""
        self._tick()

    def _link_settings(self):
        """The settings of the first link card whose link is connected and parses Modbus."""
        for card in self._cards:
            if _parses_modbus(card.link):
                return card.modbus_settings
        return DEFAULT_PERIOD, DEFAULT_TIMEOUT, DEFAULT_SLAVE

    @property
    def default_period(self):
        return self._period

    @property
    def timeout(self):
        return self._timeout

    @property
    def default_slave(self):
        return self._slave

    def status(self):
        return self._status[0]

    def tooltip(self):
        return self._status[1]

    def shown_status(self, link):
        """What a link card shows after its connection text: the status, while its ``link`` is
        connected, parses Modbus and can send (a TCP server needs a client); nothing before start()
        or while no link can send (等待连接)."""
        if not _parses_modbus(link) or not _can_send(link) or self._status[0] in ("", WAITING):
            return ""
        return self._status[0]

    def blocks(self):
        """The blocks planned last, [slave, fc, start, count, period] each."""
        return [list(block) for block in self._blocks]

    def start(self):
        """The runtime is up: read whenever a link that parses Modbus can send, from now on."""
        if self._active:
            return
        self._active = True
        for link in self._links():
            for signal in (link.connected, link.disconnected, getattr(link, "peersChanged", None)):
                if signal is not None:  # a link that comes or goes, or a TCP server's clients
                    self._link_connections.connect(signal, self._on_link_changed)
        self._period, self._timeout, self._slave = self._link_settings()
        self._timer.start(self._period)  # it looks for a link that can send, too
        self._tick()

    def stop(self):
        """The runtime goes away: no more reads; those not sent yet are withdrawn."""
        self._active = False
        self._link_connections.clear()
        self._timer.stop()
        self._withdraw()

    # -- polling ------------------------------------------------------------------

    @staticmethod
    def _now():
        return int(time.monotonic() * 1000)

    def _links(self):
        return list(getattr(self._hub, "links", None) or (self._hub,))

    def _masters(self):
        """The Modbus masters of the links that parse Modbus and can send."""
        return [link.modbus_master for link in self._links()
                if _parses_modbus(link) and _can_send(link)
                and getattr(link, "modbus_master", None) is not None]

    def _withdraw(self):
        """Forget the read awaiting replies, and drop this poller's reads not sent yet; one on the
        wire still gets its reply, which no longer counts."""
        self._read = None
        for link in self._links():
            master = getattr(link, "modbus_master", None)
            if master is not None:
                master.withdraw(self)

    def _set_status(self, text, tip=None):
        status = (text, text if tip is None else tip)
        if status != self._status:
            self._status = status
            self.statusChanged.emit(*status)

    def _on_link_changed(self, *_):
        self._tick()

    def _set_interval(self, interval):
        """The timer ticks at the shortest period of the blocks and the default period."""
        if self._timer.interval() != interval:
            self._timer.start(interval)

    def _plan(self):
        """The read blocks for what the bindings on screen and the chart curves read."""
        needs = []
        for _widget, slave, table, address, count, period, visible in (self._needs() if self._needs else ()):
            slave = slave if slave > 0 else self._slave
            if visible and 1 <= slave <= 247 and 0 <= address <= 65535:
                needs.append({"slave": slave, "table": table, "address": address,
                              "count": count, "period": max(0, period)})
        return plan_blocks(needs, self._period)

    def _tick(self):
        """Take the link cards' settings, plan again, then send the block due first if every master
        is free."""
        self._period, self._timeout, self._slave = self._link_settings()
        if not self._active:
            return
        masters = self._masters()
        if not masters:  # nothing to read with: a link that comes back starts afresh
            self._blocks, self._due, self._results, self._round_status = [], {}, {}, None
            self._set_status(WAITING)
            return
        blocks = self._plan()
        if blocks != self._blocks:  # a new plan: its blocks start their round afresh
            self._blocks = blocks
            self._due = {tuple(block): self._due.get(tuple(block), 0) for block in blocks}
            self._results, self._round_status = {}, None
        self._set_interval(min([block[4] for block in blocks] + [self._period]))
        if not blocks:
            self._set_status("没有 Modbus 绑定")
            return
        self._set_status(self._round_status or f"{len(blocks)} 块 · 轮询中", modbus_block_tip(blocks))
        if self._read is not None or any(master.busy() for master in masters):
            return  # a read or a control's write is on the wire
        now = self._now()
        due, index = min((self._due[tuple(block)], index) for index, block in enumerate(blocks))
        if due > now + DUE_EARLY:
            return
        block = blocks[index]
        self._due[tuple(block)] = now + block[4]
        read = _BlockRead(index, block)
        callback = partial(_relay, self._reply_slot, read)
        for master in masters:
            if master.enqueue(tuple(block[:4]), self._timeout, "read", callback, owner=self) is not None:
                read.waiting += 1
        if read.waiting:
            self._read = read
        else:  # no link took it: the device cannot have answered
            self._block_done(index, block, "无响应")

    def _on_read_done(self, read, result):
        if read is not self._read:
            return  # stopped since it went out
        if result.ok:
            read.success = read.success or result
        else:
            read.failure = read.failure or result
        read.waiting -= 1
        if read.waiting > 0:
            return  # another link has it still
        self._read = None
        result = read.success or read.failure
        # An exception the device answered with, or no reply (a timeout, or a link that could not send).
        problem = None if result.ok else modbus_problem(result.message) or "无响应"
        self._block_done(read.index, read.block, problem)

    def _block_done(self, index, block, problem):
        """A block's read is done; a round ends once every block of the plan has been read."""
        if index < len(self._blocks) and self._blocks[index] == block:
            if self._results.get(index) is None:  # a block that failed once in a round stays failed
                self._results[index] = problem
            if len(self._results) == len(self._blocks):
                failed = [i for i in range(len(self._blocks)) if self._results[i] is not None]
                if not failed:
                    self._round_status = f"{len(self._blocks)} 块 · 正常"
                else:
                    number, problem = failed[0], self._results[failed[0]]
                    slave, fc, start = self._blocks[number][:3]
                    if problem == "无响应":
                        self._round_status = f"第 {number + 1} 块无响应（从站 {slave} 功能码 {fc} 地址 {start}）"
                    else:
                        self._round_status = f"第 {number + 1} 块{problem}"
                self._results = {}
        self._tick()


def _format_display(value, fmt):
    if fmt == "自动": return value
    try:
        num = int(float(value)) if not isinstance(value, int) else value
    except (ValueError, TypeError, OverflowError): return value
    if fmt == "十六进制(HEX)":
        return f"0x{num:02X}" if num >= 0 else f"-0x{abs(num):02X}"
    if fmt == "二进制(BIN)":
        return f"0b{num:08b}" if num >= 0 else f"-0b{abs(num):08b}"
    if fmt == "十进制": return str(num)
    return value


def _resolve_path(data, path):
    for part in path.split("."):
        if data is None: return None
        if isinstance(data, dict): data = data.get(part)
        elif isinstance(data, (list, tuple)):
            try: data = data[int(part)]
            except (ValueError, IndexError): return None
        else: return None
    return data


_STRUCT_FMT = {
    "uint8": ("B", 1), "int8": ("b", 1),
    "uint16": ("H", 2), "int16": ("h", 2),
    "uint32": ("I", 4), "int32": ("i", 4),
    "float32": ("f", 4),
}


class DataBinding:
    """Wire the hub (serial, TCP and MQTT links) to bound widgets and command senders."""
    def __init__(self, ui, hub):
        self.ui = ui
        self.hub = hub
        self._connections = SignalConnections(ui)
        ui._comm_hub = hub
        # Reads what the Modbus bindings and chart curves show; the link cards, in document
        # order, hand it their settings and show its status.
        self.modbus_poller = ModbusPoller(hub, self.modbus_needs, ui)
        for w in ui.widgets.values():
            if hasattr(w, "set_serial_handler"):
                w.set_serial_handler(hub)  # connection cards pick their own link
            if isinstance(w, RealtimeLineChart):
                w._serial_connections.clear()
                w._serial_connections.connect(hub.dataReceived, w.on_parsed)
                w._serial_connections.connect(hub.rawReceived, w.on_raw)
                w._serial_connections.connect(hub.disconnected, w.reset_stream)
        for widget_id in ['serial']:
            ui.widgets[widget_id].set_modbus_poller(self.modbus_poller)
        self._connections.connect(self.hub.dataReceived, self._on_data)
        self.modbus_poller.start()  # reads once a link that parses Modbus can send

    def _on_data(self, data: dict):
        try:
            if 'temperature' in data and data['temperature'] is not None:
                value = data['temperature']
                w = self.ui.widgets.get('temperature')
                if w:
                    w.set_value(str(value))

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'pressure' in data and data['pressure'] is not None:
                value = data['pressure']
                w = self.ui.widgets.get('pressure')
                if w:
                    w.set_value(str(value))

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'pressure' in data and data['pressure'] is not None:
                value = data['pressure']
                w = self.ui.widgets.get('pressure_ring')
                if w:
                    w.set_value(binding_integer(value))

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'running' in data and data['running'] is not None:
                value = data['running']
                w = self.ui.widgets.get('running')
                if w:
                    w.set_on(binding_led(value, '1', '0'))

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'setpoint' in data and data['setpoint'] is not None:
                value = data['setpoint']
                w = self.ui.widgets.get('setpoint_slider')
                if w:
                    value = binding_integer(value)
                    with QSignalBlocker(w):
                        w.setValue(value)
                    # Fluent normally moves its handle in the blocked valueChanged signal.
                    w._adjustHandlePos()

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'setpoint' in data and data['setpoint'] is not None:
                value = data['setpoint']
                w = self.ui.widgets.get('setpoint_spin')
                if w:
                    value = binding_integer(value)
                    with QSignalBlocker(w):
                        w.setValue(value)

        except (TypeError, ValueError, OverflowError, struct.error):
            pass
        try:
            if 'running' in data and data['running'] is not None:
                value = data['running']
                w = self.ui.widgets.get('run_switch')
                if w:
                    value = binding_boolean(value)
                    with QSignalBlocker(w._switch):
                        w._switch.setChecked(value)

        except (TypeError, ValueError, OverflowError, struct.error):
            pass

    # (widget id, slave, table, address, count, period) of each Modbus binding
    _MODBUS_NEEDS = []

    def modbus_needs(self):
        """Bindings count while their widget is on screen; chart curves always."""
        needs = []
        for widget_id, *need in self._MODBUS_NEEDS:
            w = self.ui.widgets.get(widget_id)
            needs.append((widget_id, *need, w is not None and w.isVisible()))
        for widget_id, w in self.ui.widgets.items():
            curves = getattr(w, "modbus_needs", None)  # charts read their own curves
            if callable(curves):
                needs.extend((widget_id, *need, True) for need in curves())
        return needs
