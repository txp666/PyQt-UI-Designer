"""Modbus card shared by the designer preview and exported applications.

It sends one request from its fields, or polls: each round sends the reads in its poll
table (or the request in its fields) one at a time, waiting for each reply or for the
timeout, so a slow or silent device shows up as a timeout instead of piling requests up
on the bus. Requests go out over every connected link, as RTU or Modbus TCP to match
that link's parser. When no connected link parses Modbus, no reply can be recognised:
then each poll tick sends the next request without waiting, as the card always did.
"""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, ComboBox, LineEdit, PrimaryPushButton, PushButton,
    StrongBodyLabel,
)

from .command_runtime import MODBUS_FUNCTIONS, MODBUS_ORDERS, modbus_request, send_modbus_command
from .signal_lifetime import SignalConnections

MODBUS_EXCEPTIONS = {
    1: "非法功能码", 2: "非法数据地址", 3: "非法数据值", 4: "从站设备故障",
    5: "已确认，处理中", 6: "从站忙", 10: "网关路径不可用", 11: "网关目标设备无响应",
}


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


def modbus_problem(data):
    """Why a reply is not a success, or None: the exception code a device answered with."""
    code = data.get("error")
    if code is None:
        return None
    return f"异常 {code:02X} {MODBUS_EXCEPTIONS.get(code, '')}".rstrip()


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
        ("pollList", "set_poll_list", ""),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._handler = None
        self._serial_connections = SignalConnections(self)
        self._data_type, self._reg_order = "uint16", MODBUS_ORDERS[0]
        self._timeout = 1000
        self._poll_list = ""
        self._table = []       # the reads each poll round sends; empty: the request in the fields
        self._round = []       # requests still to send in this round
        self._round_size = 0
        self._round_problems = []
        self._waiting = None   # (slave, fc, address) of the request awaiting its reply
        self._next = 0         # the request a poll tick sends when nothing waits for replies
        self._polling = False
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_tick)
        self._reply_timer = QTimer(self)
        self._reply_timer.setSingleShot(True)
        self._reply_timer.timeout.connect(self._on_no_reply)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)
        LW = 56

        title_row = QHBoxLayout()
        self._title = StrongBodyLabel("Modbus 配置")
        self._status = CaptionLabel("就绪")
        self._status.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        # A long status takes only the room the title leaves; the tooltip has all of it.
        self._status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title_row.addWidget(self._title)
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
        """Follow a hub (or a single link): its connection state and every reply it parses."""
        if handler is self._handler:
            return
        self._serial_connections.clear()
        self._stop_poll()
        self._handler = handler
        if handler is not None:
            self._serial_connections.connect(handler.connected, self._on_connected)
            self._serial_connections.connect(handler.disconnected, self._on_disconnected)
            self._serial_connections.connect(handler.dataReceived, self._on_data)

    def _set_status(self, text):
        self._status.setText(text)
        self._status.setToolTip(text)

    def _on_connected(self, port):
        self._set_status(f"已连接: {port}")

    def _on_disconnected(self):
        self._stop_poll()
        self._set_status("未连接")

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
        return any(getattr(link, "parser_type", "") in ("modbus", "modbus_tcp", "modbus_ascii")
                   for link in self._links())

    def _send(self, request):
        """Send one request and wait for its reply; the frames links accepted, or [] after reporting why."""
        if self._handler is None or not self._handler.is_connected:
            self._set_status("未连接")
            return []
        try:
            frames = send_modbus_command(self._handler, *request, self._data_type, self._reg_order)
        except ValueError as exc:
            self._stop_poll()
            self._set_status(str(exc))
            return []
        if not frames:
            self._stop_poll()
            self._set_status("发送失败，请检查连接")
            return []
        if self._expects_replies():
            self._waiting = (int(request[0]), request[1], int(request[2]))
            self._reply_timer.start(self._timeout)
        return frames

    def _on_send_clicked(self):
        frames = self._send(self._field_request())
        if frames:
            self._set_status(modbus_sent_status(frames))

    # -- replies ----------------------------------------------------------------

    def _answers(self, data):
        slave, fc, address = self._waiting
        if data.get("slave") != slave or data.get("fc") not in (fc, fc | 0x80):
            return False
        where = data.get("start", data.get("address"))  # reads name their start, writes echo it
        if where is None:  # only an exception to a write has no address; a read without one answers another
            return data.get("fc", 0) >= 0x80
        return where == address

    def _on_data(self, data):
        if self._waiting is None or not self._answers(data):
            return
        self._reply_timer.stop()
        self._waiting = None
        self._replied(modbus_problem(data))

    def _on_no_reply(self):
        self._waiting = None
        self._replied("无响应")

    def _replied(self, problem):
        if not self._polling:
            if problem is None:
                self._set_status("设备已响应")
            elif problem == "无响应":
                self._set_status(f"无响应（{self._timeout} ms 超时）")
            else:
                self._set_status(f"设备返回{problem}")
            return
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

    # -- polling ----------------------------------------------------------------

    def _poll_tick(self):
        if self._waiting is not None:
            return  # the last request is still waiting for its reply
        if not self._expects_replies():  # nothing to wait for: one request per tick, in turn
            requests = self._table or [self._field_request()]
            self._next %= len(requests)
            frames = self._send(requests[self._next])
            self._next += 1
            if frames:
                self._set_status(modbus_sent_status(frames))
            return
        self._round = list(self._table) or [self._field_request()]
        self._round_size = len(self._round)
        self._round_problems = []
        self._send_next()

    def _send_next(self):
        self._send(self._round.pop(0))

    def _int_val(self, edit, default=0):
        try:
            return int(edit.text().strip())
        except (ValueError, AttributeError):
            return default

    def _toggle_poll(self):
        if self._polling:
            self._stop_poll()
            return
        interval = self._int_val(self._poll_edit, 0)
        if not 1 <= interval <= 60000:
            self._set_status("轮询间隔应为 1–60000 ms")
            return
        try:
            self._table = modbus_poll_table(self._poll_list)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self._reply_timer.stop()
        self._waiting = None
        self._next = 0
        self._poll_timer.start(interval)
        self._polling = True
        self._poll_btn.setText("停止")
        self._send_btn.setEnabled(False)
        if self._table:
            self._set_status(f"轮询中 · {len(self._table)} 条")
        self._poll_tick()  # the first round goes out right away

    def _stop_poll(self):
        self._poll_timer.stop()
        self._reply_timer.stop()
        self._waiting = None
        self._round = []
        self._polling = False
        self._poll_btn.setText("轮询")
        self._send_btn.setEnabled(True)

    # -- properties ---------------------------------------------------------------

    def set_title(self, t): self._title.setText(t)
    def set_default_slave(self, v): self._slave_edit.setText(str(int(v)))
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
