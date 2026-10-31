"""Modbus master queue, one per link, shared by the designer and standalone exports.

Every Modbus request a link carries goes through its master: a control's command, the
Modbus poller's reads. The master puts one request on the wire, waits for the reply that
answers it or for its timeout, then sends the next one, so a reply is never taken for the
answer to another request. Writes go ahead of the reads waiting in the queue (behind
earlier writes), so polling never holds up a button for more than the read already on the
wire. A reply answers the request in flight when its slave and function code match (an
exception, fc | 0x80, too) and so does the address it names: the start a read reply is
named by (Modbus requests) or the address a write reply echoes.

Also the block planner of the Modbus poller (modbus_poller): what bound widgets and chart
curves read, merged into as few reads as the gap and length limits allow.
"""
from PyQt5.QtCore import QObject, QTimer

from .protocol_parser import build_modbus_ascii_frame, build_modbus_frame, build_modbus_tcp_frame

# The link parsers that read Modbus replies; requests on other links are sent and not answered.
MODBUS_PARSERS = ("modbus", "modbus_tcp", "modbus_ascii")
MODBUS_EXCEPTIONS = {
    1: "非法功能码", 2: "非法数据地址", 3: "非法数据值", 4: "从站设备故障",
    5: "已确认，处理中", 6: "从站忙", 10: "网关路径不可用", 11: "网关目标设备无响应",
}


def modbus_problem(data):
    """Why a reply is not a success, or None: the exception code a device answered with."""
    code = data.get("error")
    if code is None:
        return None
    return f"异常 {code:02X} {MODBUS_EXCEPTIONS.get(code, '')}".rstrip()


_transaction = [0]


def next_modbus_transaction():
    """Successive MBAP transaction identifiers, wrapping at 16 bits."""
    _transaction[0] = (_transaction[0] + 1) & 0xFFFF
    return _transaction[0]


def modbus_frame(request, transaction=None, ascii_frame=False):
    """A validated request (command_runtime.modbus_request) as an RTU frame, as a Modbus TCP ADU
    given its transaction id, or as a Modbus ASCII frame."""
    slave, func, address, value = request
    registers, value = (value, 0) if func == 0x10 else ((), value)
    if transaction is not None:
        return build_modbus_tcp_frame(slave, func, address, value, value, transaction, registers)
    if ascii_frame:
        return build_modbus_ascii_frame(slave, func, address, value, value, registers)
    return build_modbus_frame(slave, func, address, value, value, registers)


def link_frame(link, request):
    """The request framed the way a link parses: MBAP for modbus_tcp, ASCII for modbus_ascii, else RTU."""
    parser_type = getattr(link, "parser_type", "")
    if parser_type == "modbus_tcp":
        return modbus_frame(request, next_modbus_transaction())
    return modbus_frame(request, ascii_frame=parser_type == "modbus_ascii")


def modbus_dispatch(hub, request, timeout_ms=1000, priority="write", on_done=None, owner=None,
                    modbus_only=False):
    """Send a validated request over every connected link of a hub (or over one link).

    A connected link that parses Modbus queues it in its master, which calls ``on_done``
    once with the outcome; any other link gets the frame at once and no answer is awaited
    (with ``modbus_only``, it gets nothing). Returns ``(frame, master)`` for each link that
    took it; ``master`` is None for a link written directly.
    """
    links = getattr(hub, "connected_links", None)
    if links is None:  # a single link rather than a hub
        links = [hub] if hub.is_connected else []
    accepted = []
    for link in links:
        master = getattr(link, "modbus_master", None)
        if master is not None and getattr(link, "parser_type", "") in MODBUS_PARSERS:
            frame = master.enqueue(request, timeout_ms, priority, on_done, owner=owner)
            if frame is not None:
                accepted.append((frame, master))
        elif not modbus_only:
            frame = link_frame(link, request)
            if link.send(frame):
                accepted.append((frame, None))
    return accepted


class ModbusResult:
    """What became of one request: ``ok``, the parsed reply (``message``, empty without one) and
    ``problem``: the exception, or why there is no reply; empty on success."""
    __slots__ = ("ok", "message", "problem")

    def __init__(self, ok, message, problem):
        self.ok, self.message, self.problem = ok, message, problem

    def __repr__(self):
        return f"ModbusResult({self.ok!r}, {self.message!r}, {self.problem!r})"


class _Queued:
    __slots__ = ("request", "frame", "timeout", "on_done", "write", "owner")

    def __init__(self, request, frame, timeout, on_done, write, owner):
        self.request, self.frame, self.timeout = request, frame, timeout
        self.on_done, self.write, self.owner = on_done, write, owner


class ModbusMaster(QObject):
    """The Modbus request queue of one link (a TCP server's peers share one: a reply from any
    of them answers)."""

    def __init__(self, link):
        super().__init__(link)
        self._link = link
        self._queue = []      # writes first, then reads, each in the order they came
        self._current = None  # the request on the wire
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        link.dataReceived.connect(self._on_data)
        link.disconnected.connect(self.cancel_all)

    def busy(self):
        """A request is on the wire, waiting for its reply."""
        return self._current is not None

    def pending(self):
        """Requests waiting for the one on the wire."""
        return len(self._queue)

    def enqueue(self, request, timeout_ms=1000, priority="read", on_done=None, owner=None):
        """Queue a request; the frame it goes out as, or None when it was not taken.

        ``priority`` ``"write"`` puts it ahead of the waiting reads, ``"read"`` at the end.
        ``on_done(result)`` is called once, with the reply, the exception or the timeout. A
        link that is down, or refuses a request that would go out at once, does not take it,
        and ``on_done`` is not called.
        """
        if not self._link.is_connected:
            return None
        entry = _Queued(request, link_frame(self._link, request), max(1, int(timeout_ms)),
                        on_done, priority == "write", owner)
        if self._current is None and not self._queue:
            return entry.frame if self._start(entry) else None
        if entry.write:
            self._queue.insert(sum(1 for queued in self._queue if queued.write), entry)
        else:
            self._queue.append(entry)
        return entry.frame

    def withdraw(self, owner):
        """Drop the queued requests of ``owner`` that have not gone out yet, without calling back."""
        self._queue = [entry for entry in self._queue if entry.owner is not owner]

    def cancel_all(self):
        """The link is gone: every request, on the wire or queued, ends as timed out."""
        entries = ([self._current] if self._current is not None else []) + self._queue
        self._current, self._queue = None, []
        self._timer.stop()
        for entry in entries:
            self._call(entry, ModbusResult(False, {}, f"无响应（{entry.timeout} ms 超时）"))

    # -- the wire ---------------------------------------------------------------

    def _start(self, entry):
        if not self._link.send(entry.frame):  # the link reports why through its error signal
            return False
        self._current = entry
        self._timer.start(entry.timeout)
        return True

    def _pump(self):
        while self._current is None and self._queue:
            entry = self._queue.pop(0)
            if not self._start(entry):
                self._call(entry, ModbusResult(False, {}, "发送失败"))

    @staticmethod
    def _call(entry, result):
        if entry.on_done is not None:
            entry.on_done(result)

    def _finish(self, result):
        entry, self._current = self._current, None
        self._timer.stop()
        # The caller hears first, so a read it queues in reply still goes behind a waiting write.
        self._call(entry, result)
        self._pump()

    def _on_timeout(self):
        if self._current is not None:
            self._finish(ModbusResult(False, {}, f"无响应（{self._current.timeout} ms 超时）"))

    def _answers(self, data):
        slave, fc, address = self._current.request[:3]
        reply = data.get("fc")
        if data.get("slave") != slave or reply not in (fc, fc | 0x80):
            return False
        if reply == fc and fc in (1, 2, 3, 4):
            # A read reply names its start when it holds what was asked; one without it
            # (another count of registers or coils) answers some other read.
            return data.get("start") == address
        where = data.get("start", data.get("address"))  # write replies echo the address
        return where is None or where == address

    def _on_data(self, data):
        if self._current is None or not self._answers(data):
            return  # not the answer; the bindings still get it
        problem = modbus_problem(data)
        self._finish(ModbusResult(problem is None, data, "" if problem is None else f"设备返回{problem}"))


# -- the polling plan -------------------------------------------------------------

FUNCTION_OF_TABLE = {"hr": 3, "ir": 4, "co": 1, "di": 2}
MAX_GAP = {3: 8, 4: 8, 1: 64, 2: 64}       # unused registers / bits a block may read across
MAX_LEN = {3: 120, 4: 120, 1: 1000, 2: 1000}  # registers / bits one block reads at most


def plan_blocks(needs, default_period):
    """Read blocks covering what is needed: ``[slave, fc, start, count, period]`` in (slave, fc, start) order.

    A need is a mapping of ``slave``, ``table`` (hr / ir / co / di), ``address``, ``count``
    (registers, or bits for coils and discrete inputs) and ``period`` in ms (0: the default).
    Needs of one slave and table, sorted by address, join the open block while the gap to it
    stays within MAX_GAP and the block within MAX_LEN; a block is read as often as its most
    frequent need. tests/data/poll_plan_vectors.json holds the cases both repositories check.
    """
    groups = {}
    for need in needs:
        fc = FUNCTION_OF_TABLE[need["table"]]
        period = need.get("period", 0) or default_period
        groups.setdefault((need["slave"], fc), []).append((need["address"], need["count"], period))
    blocks = []
    for (slave, fc), items in sorted(groups.items()):
        items.sort()
        start = end = period = None
        for address, count, need_period in items:
            need_end = address + count
            if start is not None and address <= end + MAX_GAP[fc] and need_end - start <= MAX_LEN[fc]:
                end = max(end, need_end)
                period = min(period, need_period)
            else:
                if start is not None:
                    blocks.append([slave, fc, start, end - start, period])
                start, end, period = address, need_end, need_period
        if start is not None:
            blocks.append([slave, fc, start, end - start, period])
    blocks.sort(key=lambda block: (block[0], block[1], block[2]))
    return blocks
