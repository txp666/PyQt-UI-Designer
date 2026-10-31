"""Modbus card shared by the designer preview and exported applications.

It sends one request from its fields, or polls in one of two ways (轮询方式, ``pollMode``):

- 自动: the card reads what the project's Modbus bindings and chart curves show. Before each
  request it gathers what the widgets on screen read, merges neighbouring addresses into read
  blocks (modbus_master.plan_blocks) and sends the block that is due first; a block is due
  again one period after it went out: the shortest 采集周期 (``mbPeriod``) of its bindings, or
  the card's 轮询ms (500 when that is 0).
- 轮询表: each round sends the reads in its poll table (or the request in its fields) one at a
  time, as the card always did.

Requests go out over every connected link, as RTU, Modbus TCP or Modbus ASCII to match that
link's parser. A link that parses Modbus queues them in its ModbusMaster, which sends one
request at a time and pairs each reply with it, so a slow or silent device shows up as a
timeout instead of piling requests up on the bus, and a control's write goes out between two
reads. When no connected link parses Modbus, no reply can be recognised: then each poll tick
of a poll table sends the next request without waiting, as the card always did. With
``autoStart`` the card starts polling when a link that parses Modbus connects.
"""
import time
from functools import partial

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, ComboBox, LineEdit, PrimaryPushButton, PushButton,
    StrongBodyLabel,
)

from .command_runtime import MODBUS_FUNCTIONS, MODBUS_ORDERS, modbus_request
from .modbus_master import MODBUS_PARSERS, modbus_dispatch, modbus_problem, plan_blocks
from .signal_lifetime import SignalConnections

POLL_MODES = ("自动", "轮询表")
AUTO_PERIOD = 500  # what 轮询ms 0 stands for in 自动 polling
DUE_EARLY = 10     # ms: a block this close to due goes now, rather than a whole tick late


def modbus_sent_status(frames):
    """Status text for frames just sent: the first frame, and how many links got one."""
    text = f"已发送: {frames[0].hex(' ').upper()}"
    if len(frames) > 1:
        text += f"（{len(frames)} 条链路）"
    return text


def modbus_poll_table(text):
    """The reads in a poll table, one per line (or separated by ;) as 从站,功能码,地址,数量."""
    requests = []
    entries = [line.strip() for line in str(text).replace(";", "\n").splitlines()]
    for number, entry in enumerate((line for line in entries if line and not line.startswith("#")), 1):
        try:
            fields = [int(field) for field in entry.replace("，", ",").split(",")]
        except ValueError:
            fields = []
        if len(fields) != 4 or fields[1] not in (1, 2, 3, 4):
            raise ValueError(f"轮询表第 {number} 条应为 从站,功能码(1–4),地址,数量")
        try:
            requests.append(modbus_request(*fields))
        except ValueError as exc:  # the line is well formed; say what is wrong with its values
            raise ValueError(f"轮询表第 {number} 条：{exc}") from None
    return requests


def modbus_card_properties(props):
    """A card's properties with what a file from before 自动 polling leaves out: a card without a
    ``pollMode`` polls its table (or the request in its fields) as it did, from when 轮询 is pressed.
    A card the designer places now has both keys: 自动, and starting once a link connects."""
    props = dict(props)
    if "pollMode" not in props:
        props["pollMode"] = "轮询表"
        props["autoStart"] = False
    return props


def _modbus_block_tip(blocks):
    return "\n".join(f"从站 {slave} · 功能码 {fc} · 地址 {start}–{start + count - 1} · 周期 {period} ms"
                     for slave, fc, start, count, period in blocks)


def _relay(slot, request, result):
    if slot:  # emptied when the card is destroyed; a master may still answer its last request
        slot[0](request, result)


def _forget(slot, *_):
    slot.clear()


def _can_send(link):
    """Connected, and with someone to send to (a TCP server needs a client)."""
    return getattr(link, "can_send", link.is_connected)


class _CardRequest:
    """One request of the card's, sent over every connected link: done once the master of every
    link that queued it has answered, with the first success, else the first failure."""
    __slots__ = ("kind", "block", "waiting", "done", "success", "failure")

    def __init__(self, kind, block=None):
        self.kind, self.block, self.waiting, self.done = kind, block, 0, False
        self.success = self.failure = None


class ModbusConfigCard(CardWidget):
    """Modbus configuration card with read/write controls, polling and reply status."""

    FUNCTIONS = list(MODBUS_FUNCTIONS)
    PROPERTY_SETTERS = (
        ("title", "set_title", "Modbus 配置"),
        ("defaultSlave", "set_default_slave", 1),
        ("defaultFunc", "set_default_fc", "03 读保持寄存器"),
        ("defaultAddr", "set_default_addr", 0),
        ("defaultValue", "set_default_value", "1"),
        ("defaultPoll", "set_default_poll", 0),
        ("mbDataType", "set_data_type", "uint16"),
        ("mbRegOrder", "set_reg_order", MODBUS_ORDERS[0]),
        ("timeout", "set_timeout", 1000),
        ("pollMode", "set_poll_mode", POLL_MODES[0]),
        ("autoStart", "set_auto_start", True),
        ("pollList", "set_poll_list", ""),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._handler = None
        self._serial_connections = SignalConnections(self)
        self._data_type, self._reg_order = "uint16", MODBUS_ORDERS[0]
        self._timeout = 1000
        self._poll_mode = POLL_MODES[0]
        self._auto_start = True
        self._default_slave = 1  # the slave of bindings that filter none, in 自动 polling
        self._needs = None     # what the bindings and curves read; the running application sets it
        self._poll_list = ""
        self._request = None   # the card's request awaiting its reply (_CardRequest)
        self._reply_slot = [self._on_request_done]
        self.destroyed.connect(partial(_forget, self._reply_slot))
        self._polling = False
        self._period = AUTO_PERIOD  # the 轮询ms this polling started with
        # 轮询表
        self._table = []       # the reads each poll round sends; empty: the request in the fields
        self._round = []       # requests still to send in this round
        self._round_size = 0
        self._round_problems = []
        self._next = 0         # the request a poll tick sends when nothing waits for replies
        # 自动
        self._blocks = []      # the read blocks planned last: [slave, fc, start, count, period]
        self._due = {}         # block -> when it is due next (ms, _now)
        self._results = {}     # block index -> problem (None: answered) in this round
        self._auto_status = None  # how the last round went
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(6)
        LW = 56

        title_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(0)
        self._title = StrongBodyLabel("Modbus 配置")
        self._mode_hint = CaptionLabel("轮询方式：自动")
        self._mode_hint.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        title_column.addWidget(self._title)
        title_column.addWidget(self._mode_hint)
        self._status = CaptionLabel("就绪")
        self._status.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        # A long status takes only the room the title leaves; the tooltip has all of it.
        self._status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title_row.addLayout(title_column)
        title_row.addWidget(self._status, 1)
        root.addLayout(title_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        def add_field(label, editor, row, column):
            label = label if isinstance(label, BodyLabel) else BodyLabel(label)
            label.setFixedWidth(LW)
            grid.addWidget(label, row, column)
            grid.addWidget(editor, row, column + 1)

        self._slave_edit = LineEdit(); self._slave_edit.setText("1")
        self._slave_edit.setPlaceholderText("1")
        add_field("从站", self._slave_edit, 0, 0)
        self._fc_combo = ComboBox()
        self._fc_combo.addItems(self.FUNCTIONS)
        self._fc_combo.setCurrentIndex(2)
        self._fc_combo.currentTextChanged.connect(self._on_fc_changed)
        add_field("功能码", self._fc_combo, 0, 2)
        self._addr_edit = LineEdit(); self._addr_edit.setText("0")
        self._addr_edit.setPlaceholderText("0")
        add_field("地址", self._addr_edit, 1, 0)
        self._val_label = BodyLabel("数量")
        self._val_edit = LineEdit(); self._val_edit.setText("1")
        self._val_edit.setPlaceholderText("1")
        add_field(self._val_label, self._val_edit, 1, 2)
        self._poll_edit = LineEdit(); self._poll_edit.setText("0")
        self._poll_edit.setPlaceholderText("0=不轮询")
        add_field("轮询ms", self._poll_edit, 2, 0)

        btn_row = QHBoxLayout()
        self._send_btn = PrimaryPushButton("发送")
        self._send_btn.clicked.connect(self._on_send_clicked)
        self._poll_btn = PushButton("轮询")
        self._poll_btn.clicked.connect(self._toggle_poll)
        btn_row.addWidget(self._send_btn, 1)
        btn_row.addWidget(self._poll_btn, 1)
        grid.addLayout(btn_row, 2, 2, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        root.addLayout(grid)

    # -- link -------------------------------------------------------------------

    def set_serial_handler(self, handler):
        """Follow a hub (or a single link): its connection state, and every link that connects."""
        if handler is self._handler:
            return
        self._serial_connections.clear()
        self._stop_poll()
        self._handler = handler
        if handler is not None:
            self._serial_connections.connect(handler.connected, self._on_connected)
            self._serial_connections.connect(handler.disconnected, self._on_disconnected)
            for link in getattr(handler, "links", None) or (handler,):
                self._serial_connections.connect(link.connected, partial(self._on_link_connected, link))
            self._maybe_auto_start()

    def set_modbus_needs(self, needs):
        """The running preview or exported application hands the card what its bindings and curves
        read (data_binding modbus_needs). A card on the design canvas has none and never polls by itself."""
        self._needs = needs
        self._maybe_auto_start()

    def _set_status(self, text, tip=None):
        self._status.setText(text)
        self._status.setToolTip(text if tip is None else tip)

    def _on_connected(self, port):
        self._set_status(f"已连接: {port}")

    def _on_link_connected(self, link, _description):
        self._maybe_auto_start(link)

    def _on_disconnected(self):
        self._stop_poll()
        self._set_status("未连接")

    def _maybe_auto_start(self, link=None):
        if self._polling or not self._auto_start or self._needs is None or self._handler is None:
            return
        if self._poll_mode == "轮询表" and self._int_val(self._poll_edit, 0) == 0:
            return  # 0 means no polling for a poll table
        links = self._links() if link is None else [link]
        if any(_can_send(link) and getattr(link, "parser_type", "") in MODBUS_PARSERS for link in links):
            self._start_poll()

    # -- sending ----------------------------------------------------------------

    def _on_fc_changed(self, text):
        fc = MODBUS_FUNCTIONS.get(text, 0x03)
        self._val_label.setText("写入值" if fc in (0x05, 0x06, 0x10) else "数量")

    def _field_request(self):
        fc = MODBUS_FUNCTIONS.get(self._fc_combo.currentText(), 0x03)
        return self._slave_edit.text(), fc, self._addr_edit.text(), self._val_edit.text()

    def _links(self):
        links = getattr(self._handler, "connected_links", None)
        return [self._handler] if links is None else links

    def _expects_replies(self):
        """Whether a connected link parses Modbus, so replies to the requests sent can be recognised."""
        return any(getattr(link, "parser_type", "") in MODBUS_PARSERS for link in self._links())

    def _masters(self):
        """The Modbus masters of the connected links that parse Modbus."""
        if self._handler is None:
            return []
        return [link.modbus_master for link in self._links()
                if link.is_connected and getattr(link, "parser_type", "") in MODBUS_PARSERS
                and getattr(link, "modbus_master", None) is not None]

    def _send(self, request, priority, kind, block=None):
        """Send one request over every connected link; the frames links took, or [] after reporting why.

        Links that parse Modbus queue it in their masters, and the card waits for its reply. A
        block of 自动 polling goes to those links only.
        """
        if self._handler is None or not self._handler.is_connected:
            self._set_status("未连接")
            return []
        try:
            validated = modbus_request(*request, self._data_type, self._reg_order)
        except ValueError as exc:
            self._stop_poll()
            self._set_status(str(exc))
            return []
        sent = _CardRequest(kind, block)
        accepted = modbus_dispatch(self._handler, validated, self._timeout, priority,
                                   partial(_relay, self._reply_slot, sent), owner=self,
                                   modbus_only=kind == "block")
        if not accepted:
            self._stop_poll()
            self._set_status("发送失败，请检查连接")
            return []
        sent.waiting = sum(1 for _frame, master in accepted if master is not None)
        if sent.waiting:
            self._request = sent
        return [frame for frame, _master in accepted]

    def _on_send_clicked(self):
        frames = self._send(self._field_request(), "write", "manual")
        if frames:
            self._set_status(modbus_sent_status(frames))

    # -- replies ----------------------------------------------------------------

    def _on_request_done(self, request, result):
        if request is not self._request or request.done:
            return  # superseded, or the card stopped polling
        if result.ok:
            request.success = request.success or result
        else:
            request.failure = request.failure or result
        request.waiting -= 1
        if request.waiting > 0:
            return  # another link has it still
        request.done = True
        self._request = None
        result = request.success or request.failure
        if request.kind == "manual":
            self._set_status("设备已响应" if result.ok else result.problem)
            return
        if not self._polling:
            return
        if result.ok:
            problem = None
        elif result.message:
            problem = modbus_problem(result.message)
        else:
            problem = "无响应" if result.problem.startswith("无响应") else result.problem
        if request.kind == "block":
            self._block_done(request.block, problem)
        else:
            self._replied(problem)

    def _replied(self, problem):
        """A request of a poll table round is done."""
        if problem is not None:
            self._round_problems.append((self._round_size - len(self._round), problem))
        if self._round:
            self._send_next()
            return
        good = self._round_size - len(self._round_problems)
        if not self._round_problems:
            self._set_status(f"轮询正常 · {good}/{self._round_size}")
        else:
            number, problem = self._round_problems[0]
            where = f"第 {number} 条" if self._round_size > 1 else ""
            self._set_status(f"{where}{problem} · {good}/{self._round_size}")

    def _block_done(self, sent, problem):
        """A block's read is done; a round ends once every block of the plan has been read."""
        index, block = sent
        if index < len(self._blocks) and self._blocks[index] == block:
            if self._results.get(index) is None:  # a block that failed once in a round stays failed
                self._results[index] = problem
            if len(self._results) == len(self._blocks):
                failed = [i for i in range(len(self._blocks)) if self._results[i] is not None]
                if not failed:
                    self._auto_status = f"自动 · {len(self._blocks)} 块 · 正常"
                else:
                    number, problem = failed[0], self._results[failed[0]]
                    slave, fc, start = self._blocks[number][:3]
                    if problem == "无响应":
                        self._auto_status = (f"自动 · 第 {number + 1} 块无响应"
                                             f"（从站 {slave} 功能码 {fc} 地址 {start}）")
                    else:
                        self._auto_status = f"自动 · 第 {number + 1} 块{problem}"
                self._results = {}
        self._auto_tick()

    # -- polling ----------------------------------------------------------------

    def _poll_tick(self):
        if not self._polling:
            return
        if self._poll_mode == "自动":
            self._auto_tick()
            return
        if self._request is not None:
            return  # the last request is still waiting for its reply
        if not self._expects_replies():  # nothing to wait for: one request per tick, in turn
            requests = self._table or [self._field_request()]
            self._next %= len(requests)
            frames = self._send(requests[self._next], "read", "table")
            self._next += 1
            if frames:
                self._set_status(modbus_sent_status(frames))
            return
        self._round = list(self._table) or [self._field_request()]
        self._round_size = len(self._round)
        self._round_problems = []
        self._send_next()

    def _send_next(self):
        self._send(self._round.pop(0), "read", "table")

    @staticmethod
    def _now():
        return int(time.monotonic() * 1000)

    def _auto_period(self):
        """The 轮询ms field: the period of what has none of its own (0: 500 ms)."""
        period = self._int_val(self._poll_edit, -1)
        if period == 0:
            return AUTO_PERIOD
        return period if 1 <= period <= 60000 else self._period

    def _plan(self):
        """The read blocks for what the bindings on screen and the chart curves read."""
        needs = []
        for _widget, slave, table, address, count, period, visible in (self._needs() if self._needs else ()):
            slave = slave if slave > 0 else self._default_slave
            if visible and 1 <= slave <= 247 and 0 <= address <= 65535:
                needs.append({"slave": slave, "table": table, "address": address,
                              "count": count, "period": max(0, period)})
        return plan_blocks(needs, self._auto_period())

    def _auto_tick(self):
        """Plan again, then send the block due first if every master is free."""
        if not self._polling or self._poll_mode != "自动":
            return
        masters = self._masters()
        if not masters:  # nothing to read with: a link that comes back starts afresh
            self._blocks, self._due, self._results, self._auto_status = [], {}, {}, None
            self._set_status("自动 · 等待连接")
            return
        blocks = self._plan()
        if blocks != self._blocks:  # a new plan: its blocks start their round afresh
            self._blocks = blocks
            self._due = {tuple(block): self._due.get(tuple(block), 0) for block in blocks}
            self._results, self._auto_status = {}, None
            interval = min([block[4] for block in blocks] + [self._auto_period()])
            if self._poll_timer.interval() != interval:
                self._poll_timer.start(interval)
        tip = _modbus_block_tip(blocks) or None
        if not blocks:
            self._set_status("自动 · 没有 Modbus 绑定")
            return
        self._set_status(self._auto_status or f"自动 · {len(blocks)} 块 · 轮询中", tip)
        if self._request is not None or any(master.busy() for master in masters):
            return
        now = self._now()
        due, index = min((self._due[tuple(block)], index) for index, block in enumerate(blocks))
        if due > now + DUE_EARLY:
            return
        block = blocks[index]
        self._due[tuple(block)] = now + block[4]
        self._send(block[:4], "read", "block", (index, block))

    def _int_val(self, edit, default=0):
        try:
            return int(edit.text().strip())
        except (ValueError, AttributeError):
            return default

    def _toggle_poll(self):
        if self._polling:
            self._stop_poll()
            return
        self._start_poll()

    def _start_poll(self):
        interval = self._int_val(self._poll_edit, 0)
        if self._poll_mode == "自动" and interval == 0:
            interval = AUTO_PERIOD
        if not 1 <= interval <= 60000:
            self._set_status("轮询间隔应为 1–60000 ms")
            return
        if self._poll_mode == "轮询表":
            try:
                self._table = modbus_poll_table(self._poll_list)
            except ValueError as exc:
                self._set_status(str(exc))
                return
        self._request = None
        self._next = 0
        self._period = interval
        self._blocks, self._due, self._results, self._auto_status = None, {}, {}, None
        # 自动 periods are each block's own; a coarse timer would let them drift by 5 %.
        self._poll_timer.setTimerType(Qt.PreciseTimer if self._poll_mode == "自动" else Qt.CoarseTimer)
        self._poll_timer.start(interval)
        self._polling = True
        self._poll_btn.setText("停止")
        self._send_btn.setEnabled(False)
        if self._poll_mode == "自动":
            self._auto_tick()  # the first block goes out right away
            return
        if self._table:
            self._set_status(f"轮询中 · {len(self._table)} 条")
        self._poll_tick()  # the first round goes out right away

    def _stop_poll(self):
        self._poll_timer.stop()
        self._request = None
        self._round = []
        self._blocks, self._results, self._auto_status = [], {}, None
        if self._handler is not None:  # the reads not sent yet; one on the wire still gets its reply
            for link in getattr(self._handler, "links", None) or (self._handler,):
                master = getattr(link, "modbus_master", None)
                if master is not None:
                    master.withdraw(self)
        self._polling = False
        self._poll_btn.setText("轮询")
        self._send_btn.setEnabled(True)

    # -- properties ---------------------------------------------------------------

    def set_title(self, t): self._title.setText(t)
    def set_default_slave(self, v):
        self._default_slave = int(v)
        self._slave_edit.setText(str(int(v)))
    def set_default_fc(self, v):
        idx = self._fc_combo.findText(v)
        if idx >= 0:
            self._fc_combo.setCurrentIndex(idx)
    def set_default_addr(self, v): self._addr_edit.setText(str(int(v)))
    def set_default_value(self, v): self._val_edit.setText(str(v))  # older projects hold an int
    def set_default_poll(self, v): self._poll_edit.setText(str(int(v)))
    def set_data_type(self, v): self._data_type = v
    def set_reg_order(self, v): self._reg_order = v
    def set_timeout(self, v): self._timeout = max(10, int(v))
    def set_poll_list(self, v): self._poll_list = str(v)
    def set_auto_start(self, v): self._auto_start = bool(v)

    def set_poll_mode(self, v):
        mode = v if v in POLL_MODES else POLL_MODES[0]
        if mode != self._poll_mode and self._polling:
            self._stop_poll()
        self._poll_mode = mode
        self._mode_hint.setText(f"轮询方式：{mode}")
