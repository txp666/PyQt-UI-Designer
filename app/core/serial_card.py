# coding: utf-8
"""Composite card widgets: SerialConfigCard, DataSendCard, DataRecvCard, LogBox, ProgressRing."""
from PyQt5.QtCore import Qt, QTimer
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

from .serial_runtime import _list_all_ports
from .signal_lifetime import SignalConnections

class SerialConfigCard(CardWidget):
    """Serial port configuration card with three display modes:
    完整 (full), 简洁 (simple: port+baud+buttons), 单行 (single-line toolbar).
    Buttons are wired to SerialManager so the card works in preview mode."""

    _BAUDS = ["9600", "19200", "38400", "57600", "115200",
              "230400", "460800", "921600"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._display_mode = "完整"
        self._connected = False
        self._handler = None
        self._serial_connections = SignalConnections(self)
        self._theme_connections = SignalConnections(self)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 12, 16, 12)
        self._root.setSpacing(10)

        # ---- title row ----
        self._title_w = self._make_row()
        tl = self._title_w.layout()
        self._title = StrongBodyLabel("串口配置")
        self._status = CaptionLabel("未连接")
        self._status.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        tl.addWidget(self._title); tl.addStretch(); tl.addWidget(self._status)
        self._root.addWidget(self._title_w)

        LW = 48

        # ---- port row ----
        self._port_w = self._make_row()
        pl = self._port_w.layout()
        self._port_label = BodyLabel("端口"); self._port_label.setFixedWidth(LW)
        self._port_combo = ComboBox(); self._port_combo.setMinimumWidth(120)
        self._port_combo.setPlaceholderText("选择串口")
        self._search_btn = ToolButton(FIF.SEARCH)
        self._search_btn.setToolTip("搜索串口")
        self._search_btn.clicked.connect(self.refresh_ports)
        pl.addWidget(self._port_label); pl.addWidget(self._port_combo, 1)
        pl.addWidget(self._search_btn)
        self._root.addWidget(self._port_w)

        # ---- baud row ----
        self._baud_w = self._make_row()
        bl = self._baud_w.layout()
        self._baud_label = BodyLabel("波特率"); self._baud_label.setFixedWidth(LW)
        self._baud_combo = ComboBox()
        self._baud_combo.addItems(self._BAUDS); self._baud_combo.setCurrentIndex(4)
        bl.addWidget(self._baud_label); bl.addWidget(self._baud_combo, 1)
        self._root.addWidget(self._baud_w)

        # ---- params row (databits / parity / stopbits) ----
        self._params_w = self._make_row(spacing=6)
        pal = self._params_w.layout()
        first = True
        for lbl_text, cb_items, attr, idx in [
            ("数据位", ["5", "6", "7", "8"], "_databits_combo", 3),
            ("校验",   ["None", "Even", "Odd", "Mark", "Space"], "_parity_combo", 0),
            ("停止位", ["1", "1.5", "2"], "_stopbits_combo", 0),
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
        self._flow_label = BodyLabel("流控"); self._flow_label.setFixedWidth(LW)
        self._flow_combo = ComboBox()
        self._flow_combo.addItems(["无", "RTS/CTS", "XON/XOFF", "DTR/DSR"])
        fl.addWidget(self._flow_label); fl.addWidget(self._flow_combo, 1)
        self._root.addWidget(self._flow_w)

        self._parser_w = self._make_row()
        self._parser_w.layout().addWidget(BodyLabel("解析模式"))
        self._parser_combo = ComboBox()
        self._parser_combo.addItems(["项目设置", "line", "hex", "modbus"])
        self._parser_w.layout().addWidget(self._parser_combo, 1)
        self._root.addWidget(self._parser_w)

        # ---- button row ----
        self._btn_w = self._make_row()
        btl = self._btn_w.layout()
        self._connect_btn = PrimaryPushButton(FIF.CONNECT, "连接")
        self._disconnect_btn = PushButton(FIF.CLOSE, "断开")
        self._disconnect_btn.setEnabled(False)
        self._connect_btn.clicked.connect(self._on_connect)
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        btl.addWidget(self._connect_btn, 1); btl.addWidget(self._disconnect_btn, 1)
        self._root.addWidget(self._btn_w)

        # ---- single-line row (hidden by default) ----
        self._sl_w = QWidget()
        sl = QHBoxLayout(self._sl_w)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)

        H = 33
        self._sl_port = ComboBox(); self._sl_port.setPlaceholderText("串口")
        self._sl_port.setMinimumWidth(90); self._sl_port.setFixedHeight(H)
        self._sl_baud = ComboBox(); self._sl_baud.addItems(self._BAUDS)
        self._sl_baud.setCurrentIndex(4)
        self._sl_baud.setFixedWidth(90); self._sl_baud.setFixedHeight(H)
        self._sl_search = ToolButton(FIF.SEARCH)
        self._sl_search.clicked.connect(self.refresh_ports)
        self._sl_search.setFixedSize(H, H)
        self._sl_conn = PrimaryPushButton("连接")
        self._sl_conn.setFixedSize(56, H)
        self._sl_disconn = PushButton("断开")
        self._sl_disconn.setFixedSize(56, H)
        self._sl_disconn.setEnabled(False)
        self._sl_conn.clicked.connect(self._on_connect)
        self._sl_disconn.clicked.connect(self._on_disconnect)
        self._sl_status = CaptionLabel("未连接")
        self._sl_status.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        self._sl_status.setAlignment(Qt.AlignCenter)
        self._sl_status.setFixedHeight(H)

        for w, stretch in [(self._sl_port, 2), (self._sl_baud, 0),
                           (self._sl_search, 0), (self._sl_conn, 0),
                           (self._sl_disconn, 0), (self._sl_status, 0)]:
            sl.addWidget(w, stretch, Qt.AlignVCenter)

        self._sl_w.setFixedHeight(H)
        self._root.addWidget(self._sl_w)
        self._sl_w.hide()

        self._root.addStretch(1)

        self.refresh_ports()
        self._theme_connections.connect(qconfig.themeChangedFinished, self.update)

    def set_serial_handler(self, handler):
        if handler is self._handler:
            return
        self._serial_connections.clear()
        self._handler = handler
        if handler is not None:
            self._serial_connections.connect(handler.connected, self._on_serial_connected)
            self._serial_connections.connect(handler.disconnected, self._on_serial_disconnected)
            self._serial_connections.connect(handler.error, self._on_serial_error)
            self.set_connected(handler.is_connected)

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
        if self._display_mode == "完整":
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
        is_sl = mode == "单行"
        compact = mode != "完整"
        self.setAttribute(Qt.WA_TranslucentBackground, compact)
        self.setAutoFillBackground(not compact)
        self._title_w.setVisible(not is_sl)
        self._port_w.setVisible(not is_sl)
        self._baud_w.setVisible(not is_sl)
        self._params_w.setVisible(mode == "完整")
        self._flow_w.setVisible(mode == "完整")
        self._parser_w.setVisible(mode == "完整")
        self._btn_w.setVisible(not is_sl)
        self._sl_w.setVisible(is_sl)
        if is_sl:
            self._root.setContentsMargins(8, 6, 8, 6)
            self._root.setSpacing(0)
            self._sync_to_sl()
        else:
            self._root.setContentsMargins(16, 12, 16, 12)
            self._root.setSpacing(10)
            self._sync_from_sl()
        self.update()
        self.adjustSize()
        self.updateGeometry()

    def _sync_to_sl(self):
        self._sl_port.clear()
        for i in range(self._port_combo.count()):
            self._sl_port.addItem(self._port_combo.itemText(i), self._port_combo.itemData(i))
        self._sl_port.setCurrentIndex(self._port_combo.currentIndex())
        self._sl_baud.setCurrentIndex(self._baud_combo.currentIndex())
        # A disabled preview parent also makes isEnabled() false. Preserve
        # connection state instead of making that inherited state permanent.
        self._sl_conn.setEnabled(not self._connected)
        self._sl_disconn.setEnabled(self._connected)
        self._sl_status.setText(self._status.text())
        self._sl_status.setTextColor(self._status.lightColor, self._status.darkColor)

    def _sync_from_sl(self):
        idx = self._sl_port.currentIndex()
        if 0 <= idx < self._port_combo.count():
            self._port_combo.setCurrentIndex(idx)
        self._baud_combo.setCurrentIndex(self._sl_baud.currentIndex())

    # ---- connect / disconnect ----

    def _on_connect(self):
        port = self.port
        baud = self.baudrate
        if not port:
            return

        flow_map = {"无": "none", "RTS/CTS": "rtscts", "XON/XOFF": "xonxoff", "DTR/DSR": "dsrdtr"}
        parity_map = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"}

        for btn in (self._connect_btn, self._sl_conn):
            btn.setEnabled(False)
        self._set_status("连接中...", "#FF9800")

        if self._handler is None:
            return
        ok = self._handler.connect(
            port, baud,
            databits=int(self._databits_combo.currentText()),
            parity=parity_map.get(self._parity_combo.currentText(), "N"),
            stopbits=float(self._stopbits_combo.currentText()),
            flowcontrol=flow_map.get(self._flow_combo.currentText(), "none"),
            parser_type=None if self._parser_combo.currentText() == "项目设置" else self._parser_combo.currentText(),
        )
        if not ok:
            for btn in (self._connect_btn, self._sl_conn):
                btn.setEnabled(True)
            self._set_status("连接失败", "#F44336")

    def _on_disconnect(self):
        if self._handler is not None:
            self._handler.disconnect()

    def _on_serial_connected(self, port_name: str):
        self.set_connected(True)

    def _on_serial_disconnected(self):
        self.set_connected(False)

    def _on_serial_error(self, msg: str):
        self._set_status("错误", "#F44336")
        self._status.setToolTip(msg)
        self._sl_status.setToolTip(msg)

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

    # ---- ports / state ----

    def refresh_ports(self):
        ports = _list_all_ports()
        for combo in (self._port_combo, self._sl_port):
            combo.clear()
            for p in ports:
                combo.addItem(f"{p['port']}  {p['description']}")
            if combo.count() == 0:
                combo.addItem("无可用串口")

    def set_connected(self, connected: bool):
        self._connected = connected
        editable = not connected
        for btn in (self._connect_btn, self._sl_conn):
            btn.setEnabled(editable)
        for btn in (self._disconnect_btn, self._sl_disconn):
            btn.setEnabled(connected)
        for w in (self._port_combo, self._sl_port, self._baud_combo, self._sl_baud,
                  self._search_btn, self._sl_search,
                  self._databits_combo, self._parity_combo,
                  self._stopbits_combo, self._flow_combo, self._parser_combo):
            w.setEnabled(editable)
        if connected:
            self._set_status("● 已连接", "#4CAF50")
        else:
            self._set_status("未连接", "#888")

    # ---- property setters ----

    def set_default_parser(self, value):
        self._parser_combo.setCurrentText(value)

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
        idx = self._flow_combo.findText(v)
        if idx >= 0: self._flow_combo.setCurrentIndex(idx)

    @property
    def port(self):
        c = self._sl_port if self._display_mode == "单行" else self._port_combo
        text = c.currentText()
        if not text or text == "无可用串口":
            return ""
        return text.split()[0]

    @property
    def baudrate(self):
        c = self._sl_baud if self._display_mode == "单行" else self._baud_combo
        return int(c.currentText())
