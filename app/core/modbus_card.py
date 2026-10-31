"""Modbus card shared by the designer preview and exported applications.

The card is an optional panel of the running application's Modbus poller
(modbus_poller.ModbusPoller), which reads what the Modbus bindings and chart curves show
whether or not the project has a card. The first card in document order hands the poller its
parameters: 默认从站 (``defaultSlave``) for the bindings that filter no slave, the 轮询ms field
for what has no 采集周期 of its own (0: 500 ms; an edit counts at once) and the reply timeout
(``timeout``). Every card shows the poller's status, with the planned blocks in its tooltip,
and its 停止 / 轮询 button pauses and resumes the one poller.

发送 sends one request from the fields over every connected link, as RTU, Modbus TCP or Modbus
ASCII to match that link's parser. A link that parses Modbus queues it in its ModbusMaster
ahead of the polling reads and pairs the reply with it. While the poller reads blocks the
result comes as a 2 s notification and the status line keeps the polling state; while it is
paused or has nothing to read the status line shows the result. Fields that make no request
(参数无效, the reason as a notification) and a request no link takes (发送失败，请检查连接)
show on the status line either way.
"""
from functools import partial

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, ComboBox, InfoBar, LineEdit, PrimaryPushButton, PushButton,
    StrongBodyLabel,
)

from .command_runtime import MODBUS_FUNCTIONS, MODBUS_ORDERS, modbus_request
from .modbus_master import modbus_dispatch
from .signal_lifetime import SignalConnections

SEND_FAILED = "发送失败，请检查连接"
INVALID = "参数无效"  # a field 发送 cannot turn into a request


def modbus_sent_status(frames):
    """Status text for frames just sent: the first frame, and how many links got one."""
    text = f"已发送: {frames[0].hex(' ').upper()}"
    if len(frames) > 1:
        text += f"（{len(frames)} 条链路）"
    return text


def _relay(slot, request, result):
    if slot:  # emptied when the card is destroyed; a master may still answer its last request
        slot[0](request, result)


def _forget(slot, *_):
    slot.clear()


class _CardRequest:
    """The request 发送 sent over every connected link: done once the master of every link that
    queued it has answered, with the first success, else the first failure."""
    __slots__ = ("waiting", "success", "failure")

    def __init__(self):
        self.waiting = 0
        self.success = self.failure = None


class ModbusConfigCard(CardWidget):
    """Modbus card: the poller's parameters, status and pause button, and a manual request."""

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
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._handler = None
        self._poller = None
        self._leads = False  # the first card of its poller: its parameters count
        self._poller_connections = SignalConnections(self)
        self._data_type, self._reg_order = "uint16", MODBUS_ORDERS[0]
        self._timeout = 1000
        self._default_slave = 1
        self._manual = None    # the request 发送 sent, awaiting its reply (_CardRequest)
        self._reply_slot = [self._on_request_done]
        self.destroyed.connect(partial(_forget, self._reply_slot))

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
        self._poll_edit.setPlaceholderText("默认 500")
        self._poll_edit.textChanged.connect(self._push_period)
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

    # -- link and poller ------------------------------------------------------------

    def set_serial_handler(self, handler):
        """The hub (or a single link) 发送 sends over."""
        self._handler = handler

    def set_modbus_poller(self, poller):
        """Show a running application's Modbus poller: its status, and the button that pauses and
        resumes it. The first card a poller gets hands it the card's parameters."""
        if poller is self._poller:
            return
        self._poller_connections.clear()
        self._poller, self._leads = poller, False
        if poller is None:
            return
        self._poller_connections.connect(poller.statusChanged, self._set_status)
        self._poller_connections.connect(poller.pausedChanged, self._show_paused)
        self._leads = poller.add_panel(self)
        if self._leads:
            poller.set_default_slave(self._default_slave)
            poller.set_timeout(self._timeout)
            self._push_period()
        if poller.status():  # none before the runtime starts it
            self._set_status(poller.status(), poller.tooltip())
        self._show_paused(poller.paused)

    def _push_period(self, *_):
        """The 轮询ms field is the poller's default period from each keystroke on: 500 ms while it
        holds no number above 0."""
        if not self._leads:
            return
        try:
            period = int(self._poll_edit.text())
        except ValueError:
            period = 0
        self._poller.set_default_period(period if 0 < period < 2 ** 31 else 0)

    def _set_status(self, text, tip=None):
        self._status.setText(text)
        self._status.setToolTip(text if tip is None else tip)

    def _show_paused(self, paused):
        self._poll_btn.setText("轮询" if paused else "停止")

    def _toggle_poll(self):
        if self._poller is None:
            return
        if self._poller.paused:
            self._poller.resume()
        else:
            self._poller.pause()

    def _polling(self):
        """The poller reads blocks: results come as notifications, the status line is its own."""
        return self._poller is not None and self._poller.polling()

    # -- sending ----------------------------------------------------------------

    def _on_fc_changed(self, text):
        fc = MODBUS_FUNCTIONS.get(text, 0x03)
        self._val_label.setText("写入值" if fc in (0x05, 0x06, 0x10) else "数量")

    def _field_request(self):
        fc = MODBUS_FUNCTIONS.get(self._fc_combo.currentText(), 0x03)
        return self._slave_edit.text(), fc, self._addr_edit.text(), self._val_edit.text()

    def _on_send_clicked(self):
        """发送: one request from the fields over every connected link, queued ahead of the
        poller's reads on the links that parse Modbus."""
        try:
            request = modbus_request(*self._field_request(), self._data_type, self._reg_order)
        except ValueError as exc:  # what is wrong comes as a notification
            InfoBar.error(title="Modbus", content=str(exc), duration=2000, parent=self.window())
            self._set_status(INVALID)
            return
        accepted = []
        sent = _CardRequest()
        if self._handler is not None and self._handler.is_connected:
            accepted = modbus_dispatch(self._handler, request, self._timeout, "write",
                                       partial(_relay, self._reply_slot, sent))
        if not accepted:
            self._set_status(SEND_FAILED)
            return
        sent.waiting = sum(1 for _frame, master in accepted if master is not None)
        self._manual = sent if sent.waiting else None  # a reply is awaited where a link parses Modbus
        if not self._polling():
            self._set_status(modbus_sent_status([frame for frame, _master in accepted]))

    def _on_request_done(self, request, result):
        if request is not self._manual:
            return  # superseded by a later 发送
        if result.ok:
            request.success = request.success or result
        else:
            request.failure = request.failure or result
        request.waiting -= 1
        if request.waiting > 0:
            return  # another link has it still
        self._manual = None
        result = request.success or request.failure
        text = "设备已响应" if result.ok else result.problem
        if not self._polling():  # the status line is the poller's while it reads blocks
            self._set_status(text)
            return
        show = InfoBar.info if result.ok else InfoBar.warning
        show(title="Modbus", content=text, duration=2000, parent=self.window())

    # -- properties ---------------------------------------------------------------

    def set_title(self, t): self._title.setText(t)
    def set_default_fc(self, v):
        idx = self._fc_combo.findText(v)
        if idx >= 0:
            self._fc_combo.setCurrentIndex(idx)
    def set_default_addr(self, v): self._addr_edit.setText(str(int(v)))
    def set_default_value(self, v): self._val_edit.setText(str(v))  # older projects hold an int
    def set_default_poll(self, v): self._poll_edit.setText(str(int(v)))
    def set_data_type(self, v): self._data_type = v
    def set_reg_order(self, v): self._reg_order = v

    def set_default_slave(self, v):
        self._default_slave = int(v)
        self._slave_edit.setText(str(int(v)))
        if self._leads:
            self._poller.set_default_slave(self._default_slave)

    def set_timeout(self, v):
        self._timeout = max(10, int(v))
        if self._leads:
            self._poller.set_timeout(self._timeout)
