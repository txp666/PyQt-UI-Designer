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
    CheckBox, TextEdit, isDarkTheme,
)

from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.widget_registry import registry

try:
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


# ---------------------------------------------------------------------------
# Serial Config Card
# ---------------------------------------------------------------------------

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

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 12, 16, 12)
        self._root.setSpacing(10)

        # ---- title row ----
        self._title_w = self._make_row()
        tl = self._title_w.layout()
        self._title = StrongBodyLabel("串口配置")
        self._status = CaptionLabel("未连接")
        self._status.setStyleSheet("color: #888;")
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
        self._sl_status.setStyleSheet("color: #888;")
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

        from app.common.signal_bus import signalBus
        signalBus.serialConnected.connect(self._on_serial_connected)
        signalBus.serialDisconnected.connect(self._on_serial_disconnected)
        signalBus.serialError.connect(self._on_serial_error)

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
        self._sl_conn.setEnabled(self._connect_btn.isEnabled())
        self._sl_disconn.setEnabled(self._disconnect_btn.isEnabled())
        self._sl_status.setText(self._status.text())
        self._sl_status.setStyleSheet(self._status.styleSheet())

    def _sync_from_sl(self):
        idx = self._sl_port.currentIndex()
        if 0 <= idx < self._port_combo.count():
            self._port_combo.setCurrentIndex(idx)
        self._baud_combo.setCurrentIndex(self._sl_baud.currentIndex())

    # ---- connect / disconnect ----

    def _on_connect(self):
        from app.core.serial_manager import serialManager
        port = self.port
        baud = self.baudrate
        if not port:
            return

        flow_map = {"无": "none", "RTS/CTS": "rtscts", "XON/XOFF": "xonxoff", "DTR/DSR": "dsrdtr"}
        parity_map = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"}

        for btn in (self._connect_btn, self._sl_conn):
            btn.setEnabled(False)
        self._set_status("连接中...", "#FF9800")

        ok = serialManager.connect(
            port, baud,
            databits=int(self._databits_combo.currentText()),
            parity=parity_map.get(self._parity_combo.currentText(), "N"),
            stopbits=float(self._stopbits_combo.currentText()),
            flowcontrol=flow_map.get(self._flow_combo.currentText(), "none"),
        )
        if not ok:
            for btn in (self._connect_btn, self._sl_conn):
                btn.setEnabled(True)
            self._set_status("连接失败", "#F44336")

    def _on_disconnect(self):
        from app.core.serial_manager import serialManager
        serialManager.disconnect()

    def _on_serial_connected(self, port_name: str):
        self.set_connected(True)

    def _on_serial_disconnected(self):
        self.set_connected(False)

    def _on_serial_error(self, msg: str):
        self._set_status("错误", "#F44336")
        self._status.setToolTip(msg)
        self._sl_status.setToolTip(msg)

    def _set_status(self, text: str, color: str):
        css = f"color: {color};"
        self._status.setText(text); self._status.setStyleSheet(css)
        self._sl_status.setText(text); self._sl_status.setStyleSheet(css)

    # ---- ports / state ----

    def refresh_ports(self):
        from app.core.serial_manager import _list_all_ports
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
                  self._stopbits_combo, self._flow_combo):
            w.setEnabled(editable)
        if connected:
            self._set_status("● 已连接", "#4CAF50")
        else:
            self._set_status("未连接", "#888")

    # ---- property setters ----

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


# ---------------------------------------------------------------------------
# Data Send Card
# ---------------------------------------------------------------------------

class DataSendCard(CardWidget):
    """Card with text input + send button for manual serial data sending.
    Auto-wired to SerialManager. Supports HEX mode via checkbox."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self._title = StrongBodyLabel("数据发送")
        layout.addWidget(self._title)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._input = LineEdit()
        self._input.setPlaceholderText("输入要发送的数据...")
        self._send_btn = PrimaryPushButton(FIF.SEND, "发送")
        self._send_btn.clicked.connect(self._do_send)
        self._input.returnPressed.connect(self._do_send)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send_btn)
        layout.addLayout(input_row)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(8)
        self._hex_check = CheckBox("HEX模式")
        self._hex_check.setChecked(False)
        self._newline_combo = ComboBox()
        self._newline_combo.addItems(["无", "\\r\\n", "\\n", "\\r"])
        self._newline_combo.setCurrentIndex(1)
        self._newline_combo.setFixedWidth(80)
        opt_row.addWidget(self._hex_check)
        opt_row.addStretch()
        opt_row.addWidget(BodyLabel("换行符"))
        opt_row.addWidget(self._newline_combo)
        layout.addLayout(opt_row)

    def _do_send(self):
        text = self._input.text().strip()
        if not text:
            self._flash_tip("请输入数据")
            return
        from app.core.serial_manager import serialManager
        if not serialManager.is_connected:
            self._flash_tip("串口未连接")
            return

        newline_map = {"无": "", "\\r\\n": "\r\n", "\\n": "\n", "\\r": "\r"}
        suffix = newline_map.get(self._newline_combo.currentText(), "\r\n")

        if self._hex_check.isChecked():
            hex_str = text.replace(" ", "")
            if len(hex_str) % 2 != 0:
                hex_str = "0" + hex_str
            try:
                raw = bytes.fromhex(hex_str)
            except ValueError:
                self._flash_tip("HEX格式错误")
                return
            serialManager.send(raw)
        else:
            serialManager.send_text(text + suffix)
        self._input.selectAll()

    def _flash_tip(self, msg: str):
        """Briefly show a warning tip on the send button, then restore."""
        original = self._send_btn.text()
        self._send_btn.setText(msg)
        self._send_btn.setEnabled(False)
        QTimer.singleShot(1200, lambda: (
            self._send_btn.setText(original),
            self._send_btn.setEnabled(True),
        ))

    def set_title(self, t): self._title.setText(t)
    def set_placeholder(self, t): self._input.setPlaceholderText(t)


# ---------------------------------------------------------------------------
# Data Receive Card
# ---------------------------------------------------------------------------

class DataRecvCard(CardWidget):
    """Card showing received serial data with raw/parsed toggle.
    Auto-wired to signalBus."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        self._title = StrongBodyLabel("数据接收")
        self._counter = CaptionLabel("0 条")
        self._counter.setStyleSheet("color: #888;")
        title_row.addWidget(self._title)
        title_row.addStretch()
        title_row.addWidget(self._counter)
        layout.addLayout(title_row)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(8)
        self._hex_check = CheckBox("HEX显示")
        self._hex_check.setChecked(False)
        self._autoscroll_check = CheckBox("自动滚动")
        self._autoscroll_check.setChecked(True)
        self._clear_btn = PushButton("清空")
        self._clear_btn.setFixedWidth(60)
        self._clear_btn.clicked.connect(self._clear)
        opt_row.addWidget(self._hex_check)
        opt_row.addWidget(self._autoscroll_check)
        opt_row.addStretch()
        opt_row.addWidget(self._clear_btn)
        layout.addLayout(opt_row)

        self._output = TextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 12px; "
            "background: #1e1e2e; color: #cdd6f4; border-radius: 4px; padding: 4px;"
        )
        layout.addWidget(self._output, 1)

        self._count = 0
        self._max_lines = 1000

        from app.common.signal_bus import signalBus
        signalBus.serialRawReceived.connect(self._on_raw_recv)
        signalBus.serialDataSent.connect(self._on_sent)
        signalBus.serialConnected.connect(
            lambda port: self._append_sys(f"已连接: {port}"))
        signalBus.serialDisconnected.connect(
            lambda: self._append_sys("已断开"))

    def _on_raw_recv(self, data: bytes):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if self._hex_check.isChecked():
            text = " ".join(f"{b:02X}" for b in data)
        else:
            text = data.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                return
        self._output.append(
            f'<span style="color:#666">[{ts}]</span> '
            f'<span style="color:#a6e3a1">&lt;&lt; {text}</span>')
        self._count += 1
        self._counter.setText(f"{self._count} 条")
        self._trim()
        self._scroll()

    def _on_sent(self, data: bytes):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if self._hex_check.isChecked():
            text = " ".join(f"{b:02X}" for b in data)
        else:
            text = data.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                return
        self._output.append(
            f'<span style="color:#666">[{ts}]</span> '
            f'<span style="color:#f9e2af">&gt;&gt; {text}</span>')
        self._trim()
        self._scroll()

    def _scroll(self):
        if self._autoscroll_check.isChecked():
            sb = self._output.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _append_sys(self, msg: str):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._output.append(
            f'<span style="color:#74c7ec">[{ts}] --- {msg} ---</span>')

    def _clear(self):
        self._output.clear()
        self._count = 0
        self._counter.setText("0 条")

    def _trim(self):
        doc = self._output.document()
        while doc.blockCount() > self._max_lines:
            cursor = self._output.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def set_title(self, t): self._title.setText(t)
    def set_max_lines(self, n): self._max_lines = max(50, n)


# ---------------------------------------------------------------------------
# Log Display Box
# ---------------------------------------------------------------------------

class LogDisplayBox(QFrame):
    """Scrolling log text display with dark terminal look.
    Auto-wired to signalBus for serial events and data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            "QTextEdit { font-family: Consolas, 'Courier New', monospace; "
            "font-size: 11px; background: #1a1a2e; color: #a8d8ea; "
            "border: 1px solid #333; border-radius: 6px; padding: 6px; }"
        )
        layout.addWidget(self._output)
        self._max_lines = 500

        from app.common.signal_bus import signalBus
        signalBus.serialConnected.connect(
            lambda port: self.append_log(f"串口已连接: {port}", "ok"))
        signalBus.serialDisconnected.connect(
            lambda: self.append_log("串口已断开", "warn"))
        signalBus.serialError.connect(
            lambda msg: self.append_log(f"错误: {msg}", "error"))
        signalBus.serialDataReceived.connect(self._on_parsed_data)

    def _on_parsed_data(self, data: dict):
        parts = [f"{k}={v}" for k, v in data.items()]
        self.append_log(", ".join(parts))

    def append_log(self, text: str, level: str = "info"):
        color_map = {"info": "#a8d8ea", "warn": "#FFD54F", "error": "#EF5350", "ok": "#81C784"}
        color = color_map.get(level, "#a8d8ea")
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._output.append(f'<span style="color:#666">[{ts}]</span> '
                            f'<span style="color:{color}">{text}</span>')
        self._trim()

    def set_max_lines(self, n): self._max_lines = max(50, n)
    def clear_log(self): self._output.clear()

    def _trim(self):
        doc = self._output.document()
        while doc.blockCount() > self._max_lines:
            cursor = self._output.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()


# ---------------------------------------------------------------------------
# Progress Ring Display
# ---------------------------------------------------------------------------

class ProgressRingDisplay(QWidget):
    """Circular progress indicator with value label."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(4)

        self._ring = ProgressRing()
        self._ring.setRange(0, 100)
        self._ring.setValue(0)
        self._ring.setFixedSize(80, 80)
        self._ring.setTextVisible(True)

        self._label = CaptionLabel("进度")
        self._label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self._ring, 0, Qt.AlignCenter)
        layout.addWidget(self._label)

    def set_value(self, v): self._ring.setValue(int(v))
    def set_maximum(self, v): self._ring.setMaximum(int(v))
    def set_label(self, t): self._label.setText(t)
    def set_ring_size(self, s): self._ring.setFixedSize(s, s)


# ---------------------------------------------------------------------------
# Modbus Config Card
# ---------------------------------------------------------------------------

class ModbusConfigCard(CardWidget):
    """Modbus RTU configuration card with read/write controls and response display.
    Auto-wired to SerialManager."""

    _FC_MAP = {
        "01 读线圈": 0x01, "02 读离散输入": 0x02,
        "03 读保持寄存器": 0x03, "04 读输入寄存器": 0x04,
        "05 写单线圈": 0x05, "06 写单寄存器": 0x06,
    }
    _FC_LIST = list(_FC_MAP.keys())

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._do_send)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        LW = 56

        # title
        title_row = QHBoxLayout()
        self._title = StrongBodyLabel("Modbus 配置")
        self._status = CaptionLabel("就绪")
        self._status.setStyleSheet("color: #888;")
        title_row.addWidget(self._title)
        title_row.addStretch()
        title_row.addWidget(self._status)
        root.addLayout(title_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        lbl_slave = BodyLabel("从站"); lbl_slave.setFixedWidth(LW)
        self._slave_edit = LineEdit(); self._slave_edit.setText("1")
        self._slave_edit.setPlaceholderText("1")
        grid.addWidget(lbl_slave, 0, 0)
        grid.addWidget(self._slave_edit, 0, 1)

        lbl_fc = BodyLabel("功能码"); lbl_fc.setFixedWidth(LW)
        self._fc_combo = ComboBox()
        self._fc_combo.addItems(self._FC_LIST)
        self._fc_combo.setCurrentIndex(2)
        self._fc_combo.currentTextChanged.connect(self._on_fc_changed)
        grid.addWidget(lbl_fc, 0, 2)
        grid.addWidget(self._fc_combo, 0, 3)

        lbl_addr = BodyLabel("地址"); lbl_addr.setFixedWidth(LW)
        self._addr_edit = LineEdit(); self._addr_edit.setText("0")
        self._addr_edit.setPlaceholderText("0")
        grid.addWidget(lbl_addr, 1, 0)
        grid.addWidget(self._addr_edit, 1, 1)

        self._val_label = BodyLabel("数量"); self._val_label.setFixedWidth(LW)
        self._val_edit = LineEdit(); self._val_edit.setText("1")
        self._val_edit.setPlaceholderText("1")
        grid.addWidget(self._val_label, 1, 2)
        grid.addWidget(self._val_edit, 1, 3)

        lbl_poll = BodyLabel("轮询ms"); lbl_poll.setFixedWidth(LW)
        self._poll_edit = LineEdit(); self._poll_edit.setText("0")
        self._poll_edit.setPlaceholderText("0=不轮询")
        grid.addWidget(lbl_poll, 2, 0)
        grid.addWidget(self._poll_edit, 2, 1)

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

        self._polling = False

        from app.common.signal_bus import signalBus
        signalBus.serialConnected.connect(
            lambda p: self._status.setText(f"已连接: {p}"))
        signalBus.serialDisconnected.connect(
            lambda: (self._stop_poll(), self._status.setText("未连接")))

    def _on_fc_changed(self, text: str):
        fc = self._FC_MAP.get(text, 0x03)
        if fc in (0x05, 0x06):
            self._val_label.setText("写入值")
        else:
            self._val_label.setText("数量")

    def _on_send_clicked(self):
        self._do_send()

    def _int_val(self, edit, default=0):
        try:
            return int(edit.text().strip())
        except (ValueError, AttributeError):
            return default

    def _do_send(self):
        from app.core.serial_manager import serialManager
        from app.core.protocol_parser import build_modbus_frame
        if not serialManager.is_connected:
            self._status.setText("串口未连接")
            return
        slave = self._int_val(self._slave_edit, 1)
        fc = self._FC_MAP.get(self._fc_combo.currentText(), 0x03)
        addr = self._int_val(self._addr_edit, 0)
        val = self._int_val(self._val_edit, 1)
        frame = build_modbus_frame(slave, fc, addr, val, val)
        serialManager.send(frame)
        self._status.setText(f"已发送: {frame.hex(' ').upper()}")

    def _toggle_poll(self):
        if self._polling:
            self._stop_poll()
        else:
            interval = self._int_val(self._poll_edit, 0)
            if interval <= 0:
                return
            self._poll_timer.start(interval)
            self._polling = True
            self._poll_btn.setText("停止")
            self._send_btn.setEnabled(False)

    def _stop_poll(self):
        self._poll_timer.stop()
        self._polling = False
        self._poll_btn.setText("轮询")
        self._send_btn.setEnabled(True)

    def set_title(self, t): self._title.setText(t)
    def set_default_slave(self, v): self._slave_edit.setText(str(int(v)))
    def set_default_fc(self, v):
        idx = self._fc_combo.findText(v)
        if idx >= 0:
            self._fc_combo.setCurrentIndex(idx)
    def set_default_addr(self, v): self._addr_edit.setText(str(int(v)))
    def set_default_value(self, v): self._val_edit.setText(str(int(v)))
    def set_default_poll(self, v): self._poll_edit.setText(str(int(v)))


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

MODBUS_CONFIG_META = WidgetMeta(
    type_name="ModbusConfigCard",
    display_name="Modbus 配置卡片",
    category=WidgetCategory.COMPOSITE,
    icon="DEVELOPER_TOOLS",
    default_width=380, default_height=180,
    min_width=280, min_height=120,
    properties=[
        PropDef("title", "标题", PropType.STRING, "Modbus 配置"),
        PropDef("defaultSlave", "默认从站", PropType.INT, 1, min_val=1, max_val=247),
        PropDef("defaultFunc", "默认功能码", PropType.ENUM, "03 读保持寄存器",
                options=["01 读线圈", "02 读离散输入", "03 读保持寄存器",
                         "04 读输入寄存器", "05 写单线圈", "06 写单寄存器"]),
        PropDef("defaultAddr", "默认地址", PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("defaultValue", "默认值/数量", PropType.INT, 1, min_val=0, max_val=65535),
        PropDef("defaultPoll", "默认轮询(ms)", PropType.INT, 0, min_val=0, max_val=60000),
    ],
)

SERIAL_CONFIG_META = WidgetMeta(
    type_name="SerialConfigCard",
    display_name="串口配置卡片",
    category=WidgetCategory.COMPOSITE,
    icon="CONNECT",
    default_width=360, default_height=300,
    min_width=200, min_height=50,
    properties=[
        PropDef("title", "标题", PropType.STRING, "串口配置"),
        PropDef("displayMode", "显示模式", PropType.ENUM, "完整",
                options=["完整", "简洁", "单行"]),
        PropDef("defaultBaud", "默认波特率", PropType.ENUM, "115200",
                options=["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]),
        PropDef("defaultDatabits", "默认数据位", PropType.ENUM, "8",
                options=["5", "6", "7", "8"]),
        PropDef("defaultParity", "默认校验位", PropType.ENUM, "None",
                options=["None", "Even", "Odd", "Mark", "Space"]),
        PropDef("defaultStopbits", "默认停止位", PropType.ENUM, "1",
                options=["1", "1.5", "2"]),
        PropDef("defaultFlow", "默认流控制", PropType.ENUM, "无",
                options=["无", "RTS/CTS", "XON/XOFF", "DTR/DSR"]),
    ],
)

DATA_SEND_META = WidgetMeta(
    type_name="DataSendCard",
    display_name="数据发送卡片",
    category=WidgetCategory.COMPOSITE,
    icon="SEND",
    default_width=350, default_height=140,
    min_width=240, min_height=100,
    properties=[
        PropDef("title", "标题", PropType.STRING, "数据发送"),
        PropDef("placeholder", "提示文字", PropType.STRING, "输入要发送的数据..."),
    ],
)

DATA_RECV_META = WidgetMeta(
    type_name="DataRecvCard",
    display_name="数据接收卡片",
    category=WidgetCategory.COMPOSITE,
    icon="DOWNLOAD",
    default_width=350, default_height=250,
    min_width=240, min_height=120,
    properties=[
        PropDef("title", "标题", PropType.STRING, "数据接收"),
        PropDef("maxLines", "最大行数", PropType.INT, 1000, min_val=50, max_val=50000),
    ],
)

LOG_BOX_META = WidgetMeta(
    type_name="LogBox",
    display_name="日志显示框",
    category=WidgetCategory.COMPOSITE,
    icon="HISTORY",
    default_width=400, default_height=200,
    min_width=200, min_height=80,
    properties=[
        PropDef("maxLines", "最大行数", PropType.INT, 500, min_val=50, max_val=50000),
    ],
)

PROGRESS_RING_META = WidgetMeta(
    type_name="ProgressRingDisplay",
    display_name="进度环",
    category=WidgetCategory.COMPOSITE,
    icon="SPEED_MEDIUM",
    default_width=120, default_height=130,
    min_width=80, min_height=80,
    properties=[
        PropDef("label", "标签", PropType.STRING, "进度"),
        PropDef("value", "当前值", PropType.INT, 0, min_val=0, max_val=100, bindable=True),
        PropDef("maximum", "最大值", PropType.INT, 100, min_val=1, max_val=99999),
    ],
)

ALL_COMPOSITE = [
    SERIAL_CONFIG_META, MODBUS_CONFIG_META, DATA_SEND_META,
    DATA_RECV_META, LOG_BOX_META, PROGRESS_RING_META,
]


def register_composite_widgets():
    for meta in ALL_COMPOSITE:
        registry.register(meta)


def create_composite_widget(type_name: str, props: dict, parent=None) -> QWidget:
    if type_name == "SerialConfigCard":
        w = SerialConfigCard(parent)
        w.set_title(props.get("title", "串口配置"))
        w.set_display_mode(props.get("displayMode", "完整"))
        w.set_default_baud(props.get("defaultBaud", "115200"))
        w.set_default_databits(props.get("defaultDatabits", "8"))
        w.set_default_parity(props.get("defaultParity", "None"))
        w.set_default_stopbits(props.get("defaultStopbits", "1"))
        w.set_default_flow(props.get("defaultFlow", "无"))
        return w
    if type_name == "ModbusConfigCard":
        w = ModbusConfigCard(parent)
        w.set_title(props.get("title", "Modbus 配置"))
        w.set_default_slave(props.get("defaultSlave", 1))
        w.set_default_fc(props.get("defaultFunc", "03 读保持寄存器"))
        w.set_default_addr(props.get("defaultAddr", 0))
        w.set_default_value(props.get("defaultValue", 1))
        w.set_default_poll(props.get("defaultPoll", 0))
        return w
    if type_name == "DataSendCard":
        w = DataSendCard(parent)
        w.set_title(props.get("title", "数据发送"))
        w.set_placeholder(props.get("placeholder", "输入要发送的数据..."))
        return w
    if type_name == "DataRecvCard":
        w = DataRecvCard(parent)
        w.set_title(props.get("title", "数据接收"))
        w.set_max_lines(props.get("maxLines", 1000))
        return w
    if type_name == "LogBox":
        w = LogDisplayBox(parent)
        w.set_max_lines(props.get("maxLines", 500))
        return w
    if type_name == "ProgressRingDisplay":
        w = ProgressRingDisplay(parent)
        w.set_label(props.get("label", "进度"))
        w.set_maximum(props.get("maximum", 100))
        w.set_value(props.get("value", 0))
        return w
    return None


def apply_composite_property(widget, type_name: str, prop_name: str, value):
    if type_name == "SerialConfigCard":
        if prop_name == "title": widget.set_title(value)
        elif prop_name == "displayMode": widget.set_display_mode(value)
        elif prop_name == "defaultBaud": widget.set_default_baud(value)
        elif prop_name == "defaultDatabits": widget.set_default_databits(value)
        elif prop_name == "defaultParity": widget.set_default_parity(value)
        elif prop_name == "defaultStopbits": widget.set_default_stopbits(value)
        elif prop_name == "defaultFlow": widget.set_default_flow(value)
    elif type_name == "ModbusConfigCard":
        if prop_name == "title": widget.set_title(value)
        elif prop_name == "defaultSlave": widget.set_default_slave(value)
        elif prop_name == "defaultFunc": widget.set_default_fc(value)
        elif prop_name == "defaultAddr": widget.set_default_addr(value)
        elif prop_name == "defaultValue": widget.set_default_value(value)
        elif prop_name == "defaultPoll": widget.set_default_poll(value)
    elif type_name == "DataSendCard":
        if prop_name == "title": widget.set_title(value)
        elif prop_name == "placeholder": widget.set_placeholder(value)
    elif type_name == "DataRecvCard":
        if prop_name == "title": widget.set_title(value)
        elif prop_name == "maxLines": widget.set_max_lines(value)
    elif type_name == "LogBox":
        if prop_name == "maxLines": widget.set_max_lines(value)
    elif type_name == "ProgressRingDisplay":
        if prop_name == "label": widget.set_label(value)
        elif prop_name == "value": widget.set_value(value)
        elif prop_name == "maximum": widget.set_maximum(value)
