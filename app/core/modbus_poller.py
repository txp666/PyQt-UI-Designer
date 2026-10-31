"""The Modbus poller of a running application, shared by the designer preview and exports.

Each running project has one poller, with or without a Modbus card on screen. As soon as a
link that parses Modbus can send (a TCP server needs a client), it reads what the project's
Modbus bindings and chart curves show: before each request it gathers what the widgets on
screen read, merges neighbouring addresses into read blocks (modbus_master.plan_blocks) and
sends the block that is due first; a block is due again one period after it went out: the
shortest 采集周期 (``mbPeriod``) of its bindings, or the default period. Reads go only to the
links that parse Modbus, through their ModbusMaster, one request on the wire at a time, so a
control's write goes out between two reads.

Without a Modbus card the period is 500 ms, a read waits 1000 ms for its reply and bindings
that filter no slave read slave 1. The first Modbus card in document order sets these from its
own (modbus_card); every card shows the status the poller reports and pauses or resumes it.
"""
import time
from functools import partial

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal

from .modbus_master import MODBUS_PARSERS, modbus_problem, plan_blocks
from .signal_lifetime import SignalConnections

DEFAULT_PERIOD = 500    # ms: how often what sets no 采集周期 of its own is read
DEFAULT_TIMEOUT = 1000  # ms a read waits for its reply
DEFAULT_SLAVE = 1       # the slave of bindings that filter none (mbSlaveFilter 0 or less)
DUE_EARLY = 10          # ms: a block this close to due goes now, rather than a whole tick late


def modbus_block_tip(blocks):
    """The tooltip of the status: one line per block."""
    return "\n".join(f"从站 {slave} · 功能码 {fc} · 地址 {start}–{start + count - 1} · 周期 {period} ms"
                     for slave, fc, start, count, period in blocks)


def _relay(slot, read, result):
    if slot:  # emptied when the poller is destroyed; a master may still answer its last read
        slot[0](read, result)


def _forget(slot, *_):
    slot.clear()


def _can_send(link):
    """Connected, and with someone to send to (a TCP server needs a client)."""
    return getattr(link, "can_send", link.is_connected)


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
    the bindings and curves read, as data_binding's ``modbus_needs`` lists it. The runtime calls
    ``start()`` once its widgets and bindings are up and ``stop()`` when it goes away.
    """

    statusChanged = pyqtSignal(str, str)  # the status, and its tooltip
    pausedChanged = pyqtSignal(bool)

    def __init__(self, hub, needs=None, parent=None):
        super().__init__(parent)
        self._hub = hub
        self._needs = needs
        self._period, self._timeout, self._slave = DEFAULT_PERIOD, DEFAULT_TIMEOUT, DEFAULT_SLAVE
        self._panels = []       # the cards showing this poller, in document order
        self._active = False    # between start() and stop()
        self._paused = False
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

    # -- what the runtime and the cards call --------------------------------------

    def set_needs(self, needs):
        """What the bindings and curves read: a callable returning (widget_id, slave, table,
        address, count, period, visible) tuples."""
        self._needs = needs

    def add_panel(self, panel):
        """A Modbus card shows this poller; True when it is the first, whose parameters count."""
        self._panels.append(panel)
        return self._panels[0] is panel

    def set_default_period(self, ms):
        """The period of what has no 采集周期 of its own; 0 or less stands for 500 ms. A change counts
        at once: the blocks whose period changes are new blocks, read right away."""
        ms = int(ms)
        self._settings_changed(period=ms if ms > 0 else DEFAULT_PERIOD)

    def set_timeout(self, ms):
        """How long each read waits for its reply, from the next read on."""
        self._settings_changed(timeout=max(1, int(ms)))

    def set_default_slave(self, slave):
        """The slave of the bindings and curves that filter none."""
        self._settings_changed(slave=int(slave))

    def _settings_changed(self, period=None, timeout=None, slave=None):
        before = (self._period, self._timeout, self._slave)
        self._period = self._period if period is None else period
        self._timeout = self._timeout if timeout is None else timeout
        self._slave = self._slave if slave is None else slave
        if (self._period, self._timeout, self._slave) != before:
            self._tick()  # the plan, the timer and the timeout follow at once

    @property
    def default_period(self):
        return self._period

    @property
    def timeout(self):
        return self._timeout

    @property
    def default_slave(self):
        return self._slave

    @property
    def paused(self):
        return self._paused

    def polling(self):
        """Reading blocks: running, not paused, with something to read over a link."""
        return self._active and not self._paused and bool(self._blocks)

    def status(self):
        return self._status[0]

    def tooltip(self):
        return self._status[1]

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
        if not self._paused:
            self._timer.start(self._period)  # it looks for a link that can send, too
            self._tick()

    def stop(self):
        """The runtime goes away: no more reads; those not sent yet are withdrawn."""
        self._active = False
        self._link_connections.clear()
        self._timer.stop()
        self._withdraw()

    def pause(self):
        """停止 on a Modbus card: no more reads until resume(); those not sent yet are withdrawn."""
        if self._paused:
            return
        self._paused = True
        self._timer.stop()
        self._withdraw()
        self._blocks, self._due, self._results, self._round_status = [], {}, {}, None
        self._set_status("已暂停")
        self.pausedChanged.emit(True)

    def resume(self):
        """轮询 on a Modbus card: plan afresh and read every block at once."""
        if not self._paused:
            return
        self._paused = False
        self._blocks, self._due, self._results, self._round_status = [], {}, {}, None
        self.pausedChanged.emit(False)
        if self._active:
            self._timer.start(self._period)
            self._tick()

    # -- polling ------------------------------------------------------------------

    @staticmethod
    def _now():
        return int(time.monotonic() * 1000)

    def _links(self):
        return list(getattr(self._hub, "links", None) or (self._hub,))

    def _masters(self):
        """The Modbus masters of the links that parse Modbus and can send."""
        return [link.modbus_master for link in self._links()
                if link.is_connected and _can_send(link)
                and getattr(link, "parser_type", "") in MODBUS_PARSERS
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
        """Plan again, then send the block due first if every master is free."""
        if not self._active or self._paused:
            return
        masters = self._masters()
        if not masters:  # nothing to read with: a link that comes back starts afresh
            self._blocks, self._due, self._results, self._round_status = [], {}, {}, None
            self._set_status("等待连接")
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
            return  # a read, a write or a card's request is on the wire
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
            return  # paused or stopped since it went out
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
