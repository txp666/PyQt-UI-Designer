# coding: utf-8
"""Composite card widgets: SerialConfigCard, DataSendCard, DataRecvCard, LogBox, ProgressRing."""
from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QSizePolicy, QFrame, QTextEdit,
)
from qfluentwidgets import (
    CardWidget, StrongBodyLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ComboBox, LineEdit, SpinBox,
    ProgressRing, FluentIcon as FIF, ToolButton,
    CheckBox, TextEdit, isDarkTheme, qconfig,
)

from .link_polling import (CARD_PARSERS, FULL_MODE, ONE_LINE_MODE, SLAVE_PROPERTY_SETTERS, ModbusSlaveSettings,
                           add_value_items, fluent_tooltip, select_value, status_label)
from .serial_runtime import SerialHandler, _list_all_ports
from .signal_lifetime import SignalConnections
from .i18n import tr

class SerialConfigCard(ModbusSlaveSettings, CardWidget):
    """Serial port configuration card with three display modes (link_polling.FULL_MODE and the others):
    full, simple (port and baud) and one line (a toolbar row).
    One button connects or disconnects the card's own serial link, at the end of the last row shown,
    so the card works in preview mode. The card is never shorter than its rows: its minimum
    height is what the rows of its display mode need. Like every link card it hands the Modbus
    poller its settings and shows the poller's status while its link parses Modbus; in the slave role
    it answers as a Modbus slave instead (link_polling.ModbusSlaveSettings)."""

    LINK_CLASS = SerialHandler
    _BAUDS = ["9600", "19200", "38400", "57600", "115200",
              "230400", "460800", "921600"]
    _FLOWS = {"无": "none", "RTS/CTS": "rtscts", "XON/XOFF": "xonxoff", "DTR/DSR": "dsrdtr"}  # i18n: value
    PROPERTY_SETTERS = (
        ("title", "set_title", "串口配置"),  # i18n: value
        ("displayMode", "set_display_mode", "完整"),  # i18n: value
        ("defaultBaud", "set_default_baud", "115200"),
        ("defaultDatabits", "set_default_databits", "8"),
        ("defaultParity", "set_default_parity", "None"),
        ("defaultStopbits", "set_default_stopbits", "1"),
        ("defaultFlow", "set_default_flow", "无"),  # i18n: value
        ("defaultParser", "set_default_parser", "项目设置"),  # i18n: value
        ("modbusRole", "set_modbus_role", "主站"),  # i18n: value
        ("modbusPeriod", "set_modbus_period", 500),
        ("modbusTimeout", "set_modbus_timeout", 1000),
        ("modbusSlave", "set_modbus_slave", 1),
        *SLAVE_PROPERTY_SETTERS,
        ("parserConfig", "set_parser_config", {}),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._display_mode = FULL_MODE
        self._parser_config = {}
        self._connected = False
        self._handler = None
        self._poll_tip = False  # the status tooltip is the Modbus poller's
        self._serial_connections = SignalConnections(self)
        self._theme_connections = SignalConnections(self)
        self._init_modbus()

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 12, 16, 12)
        self._root.setSpacing(10)

        # ---- title row ----
        self._title_w = self._make_row()
        tl = self._title_w.layout()
        self._title = StrongBodyLabel(tr("串口配置"))
        self._status = status_label(tr("未连接"))
        self._status.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        tl.addWidget(self._title); tl.addWidget(self._status, 1)
        self._root.addWidget(self._title_w)

        LW = 48

        # ---- port row ----
        self._port_w = self._make_row()
        pl = self._port_w.layout()
        self._port_label = BodyLabel(tr("端口")); self._port_label.setFixedWidth(LW)
        self._port_combo = ComboBox(); self._port_combo.setMinimumWidth(120)
        self._port_combo.setPlaceholderText(tr("选择串口"))
        self._search_btn = fluent_tooltip(ToolButton(FIF.SEARCH), tr("搜索串口"))
        self._search_btn.clicked.connect(self.refresh_ports)
        pl.addWidget(self._port_label); pl.addWidget(self._port_combo, 1)
        pl.addWidget(self._search_btn)
        self._root.addWidget(self._port_w)

        # ---- baud row ----
        self._baud_w = self._make_row()
        bl = self._baud_w.layout()
        self._baud_label = BodyLabel(tr("波特率")); self._baud_label.setFixedWidth(LW)
        self._baud_combo = ComboBox()
        self._baud_combo.addItems(self._BAUDS); self._baud_combo.setCurrentIndex(4)
        bl.addWidget(self._baud_label); bl.addWidget(self._baud_combo, 1)
        self._root.addWidget(self._baud_w)

        # ---- params row (databits / parity / stopbits) ----
        self._params_w = self._make_row(spacing=6)
        pal = self._params_w.layout()
        first = True
        for lbl_text, cb_items, attr, idx in [
            (tr("数据位"), ["5", "6", "7", "8"], "_databits_combo", 3),
            (tr("校验"),   ["None", "Even", "Odd", "Mark", "Space"], "_parity_combo", 0),
            (tr("停止位"), ["1", "1.5", "2"], "_stopbits_combo", 0),
        ]:
            lbl = CaptionLabel(lbl_text)
            if first:
                lbl.setFixedWidth(LW)
                first = False
            cb = ComboBox(); cb.addItems(cb_items); cb.setCurrentIndex(idx)
            setattr(self, attr, cb)
            pal.addWidget(lbl); pal.addWidget(cb, 1)
        self._root.addWidget(self._params_w)

        # ---- flow row ----
        self._flow_w = self._make_row()
        fl = self._flow_w.layout()
        self._flow_label = BodyLabel(tr("流控制")); self._flow_label.setFixedWidth(LW)
        self._flow_combo = ComboBox()
        add_value_items(self._flow_combo, self._FLOWS)
        fl.addWidget(self._flow_label); fl.addWidget(self._flow_combo, 1)
        self._root.addWidget(self._flow_w)

        self._parser_w = self._make_row()
        self._parser_w.layout().addWidget(BodyLabel(tr("解析模式")))
        self._parser_combo = ComboBox()
        add_value_items(self._parser_combo, CARD_PARSERS)
        self._parser_w.layout().addWidget(self._parser_combo, 1)
        self._root.addWidget(self._parser_w)

        # ---- the connect / disconnect button, at the end of the last row shown ----
        self._connect_btn = self._toggle_button()
        self._connect_btn.clicked.connect(self._on_toggle)

        # ---- single-line row (hidden by default) ----
        self._sl_w = QWidget()
        sl = QHBoxLayout(self._sl_w)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)

        H = 33
        self._sl_port = ComboBox(); self._sl_port.setPlaceholderText(tr("串口"))
        self._sl_port.setMinimumWidth(90); self._sl_port.setFixedHeight(H)
        self._sl_baud = ComboBox(); self._sl_baud.addItems(self._BAUDS)
        self._sl_baud.setCurrentIndex(4)
        self._sl_baud.setFixedWidth(90); self._sl_baud.setFixedHeight(H)
        self._sl_search = fluent_tooltip(ToolButton(FIF.SEARCH), tr("搜索串口"))
        self._sl_search.clicked.connect(self.refresh_ports)
        self._sl_search.setFixedSize(H, H)
        self._sl_conn = self._toggle_button()
        self._sl_conn.setFixedHeight(H)
        self._sl_conn.clicked.connect(self._on_toggle)
        self._sl_status = fluent_tooltip(CaptionLabel(tr("未连接")))
        self._sl_status.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        # Left: a status that has to shrink (the poller's, see _show_connected) keeps its start.
        self._sl_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._sl_status.setFixedHeight(H)

        for w, stretch in [(self._sl_port, 2), (self._sl_baud, 0),
                           (self._sl_search, 0), (self._sl_conn, 0), (self._sl_status, 0)]:
            sl.addWidget(w, stretch, Qt.AlignVCenter)

        self._sl_w.setFixedHeight(H)
        self._root.addWidget(self._sl_w)
        self._sl_w.hide()

        self._root.addStretch(1)
        self._place_button()

        self.refresh_ports()
        self._theme_connections.connect(qconfig.themeChangedFinished, self.update)

    def _attach_link(self, link):
        """Follow the card's new link (link_polling.ModbusLinkSettings.set_serial_handler)."""
        self._serial_connections.connect(link.connected, self._on_serial_connected)
        self._serial_connections.connect(link.disconnected, self._on_serial_disconnected)
        self._serial_connections.connect(link.error, self._on_serial_error)
        self.set_connected(link.is_connected)

    @staticmethod
    def _toggle_button():
        """Connect / disconnect in one button, as wide as the widest of connect / disconnect / cancel, so its
        row stays put."""
        button = PrimaryPushButton(tr("连接"))
        width = 0
        for text in (tr("连接"), tr("断开"), tr("取消")):
            button.setText(text)
            width = max(width, button.sizeHint().width())
        button.setText(tr("连接"))
        button.setFixedWidth(width)
        return button

    def _shown_rows(self):
        if self._display_mode == ONE_LINE_MODE:
            return [self._sl_w]
        rows = [self._title_w, self._port_w, self._baud_w]
        if self._display_mode == FULL_MODE:
            rows += [self._params_w, self._flow_w, self._parser_w]
        return rows

    def _place_button(self):
        """The button goes at the right end of the last field row shown (the one-line row has its own)."""
        if self._display_mode != ONE_LINE_MODE:
            row = self._shown_rows()[-1]
            button = self._connect_btn
            if button.parentWidget() is not row:
                if button.parentWidget() is not None and button.parentWidget().layout() is not None:
                    button.parentWidget().layout().removeWidget(button)
                row.layout().addWidget(button)
                button.setVisible(True)
        self.setMinimumHeight(self.content_height())

    def content_height(self):
        """What the shown rows need, with the margins and the spacing between them."""
        rows = self._shown_rows()
        margins = self._root.contentsMargins()
        return (margins.top() + margins.bottom() + sum(row.sizeHint().height() for row in rows)
                + self._root.spacing() * (len(rows) - 1))

    def minimumSizeHint(self):
        return QSize(super().minimumSizeHint().width(), self.content_height())

    @staticmethod
    def _make_row(spacing=8):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(spacing)
        return w

    # ---- compact paint ----

    def _content_height(self):
        m = self._root.contentsMargins()
        h = m.top() + m.bottom()
        for i in range(self._root.count()):
            w = self._root.itemAt(i).widget()
            if w and not w.isHidden():
                h += w.sizeHint().height() + self._root.spacing()
        return max(h, 30)

    def paintEvent(self, event):
        if self._display_mode == FULL_MODE:
            super().paintEvent(event)
            return
        ch = self._content_height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if isDarkTheme():
            painter.setBrush(QColor(44, 44, 44))
            painter.setPen(QColor(55, 55, 55))
        else:
            painter.setBrush(QColor(255, 255, 255, 230))
            painter.setPen(QColor(220, 220, 220))
        painter.drawRoundedRect(0, 0, self.width(), ch, 6, 6)
        painter.end()

    # ---- mode switching ----

    def set_display_mode(self, mode: str):
        self._display_mode = mode
        is_sl = mode == ONE_LINE_MODE
        compact = mode != FULL_MODE
        self.setAttribute(Qt.WA_TranslucentBackground, compact)
        self.setAutoFillBackground(not compact)
        self._title_w.setVisible(not is_sl)
        self._port_w.setVisible(not is_sl)
        self._baud_w.setVisible(not is_sl)
        self._params_w.setVisible(mode == FULL_MODE)
        self._flow_w.setVisible(mode == FULL_MODE)
        self._parser_w.setVisible(mode == FULL_MODE)
        self._sl_w.setVisible(is_sl)
        if is_sl:
            self._root.setContentsMargins(8, 6, 8, 6)
            self._root.setSpacing(0)
            self._sync_to_sl()
        else:
            self._root.setContentsMargins(16, 12, 16, 12)
            self._root.setSpacing(10)
            self._sync_from_sl()
        self._place_button()
        self.update()
        self.adjustSize()
        self.updateGeometry()

    def _sync_to_sl(self):
        self._sl_port.clear()
        for i in range(self._port_combo.count()):
            self._sl_port.addItem(self._port_combo.itemText(i), self._port_combo.itemData(i))
        self._sl_port.setCurrentIndex(self._port_combo.currentIndex())
        self._sl_baud.setCurrentIndex(self._baud_combo.currentIndex())
        # A disabled preview parent also makes isEnabled() false: take the state, not that.
        self._sl_conn.setEnabled(True)
        self._sl_conn.setText(self._connect_btn.text())
        self._sl_status.setText(self._status.text())
        self._sl_status.setTextColor(self._status.lightColor, self._status.darkColor)

    def _sync_from_sl(self):
        idx = self._sl_port.currentIndex()
        if 0 <= idx < self._port_combo.count():
            self._port_combo.setCurrentIndex(idx)
        self._baud_combo.setCurrentIndex(self._sl_baud.currentIndex())

    # ---- connect / disconnect ----

    def _on_toggle(self):
        if self._connected:
            self._on_disconnect()
        else:
            self._on_connect()

    def _on_connect(self):
        port = self.port
        baud = self.baudrate
        if not port or self._handler is None:  # no link off a hub (the designer canvas)
            return

        parity_map = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"}

        for btn in (self._connect_btn, self._sl_conn):
            btn.setEnabled(False)
        self._set_status(tr("连接中..."), "#FF9800")

        ok = self._handler.connect(
            port, baud,
            databits=int(self._databits_combo.currentText()),
            parity=parity_map.get(self._parity_combo.currentText(), "N"),
            stopbits=float(self._stopbits_combo.currentText()),
            flowcontrol=self._FLOWS.get(self._flow_combo.currentData(), "none"),
            parser_type=self.parser_type, parser_config=self.parser_config, slave=self.slave_device,
        )
        if not ok:
            for btn in (self._connect_btn, self._sl_conn):
                btn.setEnabled(True)
            self._set_status(tr("连接失败"), "#F44336")

    def _on_disconnect(self):
        if self._handler is not None:
            self._handler.disconnect()

    def _on_serial_connected(self, port_name: str):
        self.set_connected(True)

    def _on_serial_disconnected(self):
        self.set_connected(False)

    def _on_serial_error(self, msg: str):
        self._set_status(tr("错误"), "#F44336")
        self._status.setToolTip(msg)
        self._sl_status.setToolTip(msg)
        self._poll_tip = False

    def _set_status(self, text: str, color: str):
        colors = {
            "#888": ("#606060", "#b0b0b0"),
            "#4CAF50": ("#237b27", "#81c784"),
            "#F44336": ("#c62828", "#ff8a80"),
            "#FF9800": ("#8a4b00", "#ffb74d"),
        }
        light, dark = colors.get(color, (color, color))
        for label in (self._status, self._sl_status):
            label.setText(text)
            label.setTextColor(QColor(light), QColor(dark))
        self._sl_status.setMinimumWidth(0)  # as wide as its text

    # ---- ports / state ----

    def refresh_ports(self):
        ports = _list_all_ports()
        for combo in (self._port_combo, self._sl_port):
            combo.clear()
            for p in ports:
                combo.addItem(f"{p['port']}  {p['description']}")
            if combo.count() == 0:
                combo.addItem(tr("无可用串口"))

    def set_connected(self, connected: bool):
        self._connected = connected
        editable = not connected
        for btn in (self._connect_btn, self._sl_conn):
            btn.setEnabled(True)
            btn.setText(tr("断开") if connected else tr("连接"))
        for w in (self._port_combo, self._sl_port, self._baud_combo, self._sl_baud,
                  self._search_btn, self._sl_search,
                  self._databits_combo, self._parity_combo,
                  self._stopbits_combo, self._flow_combo, self._parser_combo):
            w.setEnabled(editable)
        if connected:
            self._show_connected()
        else:
            self._set_status(tr("未连接"), "#888")
            self._show_poll_tip(None)

    def _show_connected(self):
        """The connection, and the Modbus poller's status while the link parses Modbus, on the status
        line and in the one-line row alike. The row has little room: there the poller's part may shrink
        away, cut at its end, but never the connection, so the button stays in sight."""
        connection = "● " + tr("已连接")
        text, tip = self._with_poll_status(connection)
        self._set_status(text, "#4CAF50")
        if tip is not None:
            self._sl_status.setMinimumWidth(self._sl_status.fontMetrics().horizontalAdvance(connection))
        self._show_poll_tip(tip)

    def _show_poll_tip(self, tip):
        """The poller's tooltip, or none once it is no longer shown; the card's own (an error's) stays."""
        if tip is not None or self._poll_tip:
            for label in (self._status, self._sl_status):
                label.setToolTip(tip or "")
        self._poll_tip = tip is not None

    # ---- property setters ----

    def set_default_parser(self, value):
        select_value(self._parser_combo, value)

    def set_parser_config(self, value):
        self._parser_config = dict(value) if isinstance(value, dict) else {}

    @property
    def parser_type(self):
        """None selects the project's parser settings."""
        mode = self._parser_combo.currentData()
        return None if mode == CARD_PARSERS[0] else mode

    @property
    def parser_config(self):
        """The card's own frame format, or None for the link's rule: the project's settings
        when the card uses the project's mode, the defaults otherwise."""
        if self.parser_type is None or not self._parser_config:
            return None
        return dict(self._parser_config)

    def set_title(self, t): self._title.setText(t)

    def set_default_baud(self, baud: str):
        for cb in (self._baud_combo, self._sl_baud):
            idx = cb.findText(baud)
            if idx >= 0: cb.setCurrentIndex(idx)

    def set_default_databits(self, v: str):
        idx = self._databits_combo.findText(v)
        if idx >= 0: self._databits_combo.setCurrentIndex(idx)

    def set_default_parity(self, v: str):
        idx = self._parity_combo.findText(v)
        if idx >= 0: self._parity_combo.setCurrentIndex(idx)

    def set_default_stopbits(self, v: str):
        idx = self._stopbits_combo.findText(v)
        if idx >= 0: self._stopbits_combo.setCurrentIndex(idx)

    def set_default_flow(self, v: str):
        select_value(self._flow_combo, v)

    @property
    def port(self):
        c = self._sl_port if self._display_mode == ONE_LINE_MODE else self._port_combo
        text = c.currentText()
        if not text or text == tr("无可用串口"):
            return ""
        return text.split()[0]

    @property
    def baudrate(self):
        c = self._sl_baud if self._display_mode == ONE_LINE_MODE else self._baud_combo
        return int(c.currentText())
