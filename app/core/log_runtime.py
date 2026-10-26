"""Log box shared by the designer preview and exported applications."""
from datetime import datetime
from html import escape

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import TextEdit, setCustomStyleSheet

from .signal_lifetime import SignalConnections

LOG_STYLE = ("QTextEdit { font-family: Menlo, Consolas, 'Courier New', monospace; font-size: 11px; "
             "background: #1a1a2e; color: #a8d8ea; border: 1px solid #333; border-radius: 6px; padding: 6px; }")
LOG_COLORS = {"info": "#a8d8ea", "warn": "#FFD54F", "error": "#EF5350", "ok": "#81C784"}


def terminal_scroll_bar(edit):
    """Recolour Fluent's overlay scroll bar for a dark terminal in both themes. Its light-theme default, a
    black handle over a white groove, disappears on the dark text and glares when hovered."""
    bar = edit.scrollDelegate.vScrollBar
    handle, arrow, groove = QColor(168, 216, 234, 110), QColor(168, 216, 234, 160), QColor(36, 36, 60, 235)
    bar.setHandleColor(handle, handle)
    bar.setArrowColor(arrow, arrow)
    bar.setGrooveColor(groove, groove)


class LogDisplayBox(QWidget):
    """Scrolling, time-stamped log in a dark terminal look: every parsed frame, and the connect,
    disconnect and error events of every link (serial, TCP, MQTT)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._output = TextEdit()
        self._output.setReadOnly(True)
        setCustomStyleSheet(self._output, LOG_STYLE, LOG_STYLE)  # the terminal keeps its colours in both themes
        terminal_scroll_bar(self._output)
        self._text = self._output
        layout.addWidget(self._output)
        self._max_lines = 500
        self._handler = None
        self._serial_connections = SignalConnections(self)

    def set_serial_handler(self, handler):
        if handler is self._handler:
            return
        self._serial_connections.clear()
        self._handler = handler
        if handler is not None:
            self._serial_connections.connect(handler.connected, self._on_connected)
            self._serial_connections.connect(handler.disconnected, self._on_disconnected)
            self._serial_connections.connect(handler.error, self._on_serial_error)
            self._serial_connections.connect(handler.dataReceived, self._on_parsed_data)

    def _on_connected(self, port):
        self.append_log(f"已连接: {port}", "ok")

    def _on_disconnected(self):
        self.append_log("已断开", "warn")

    def _on_serial_error(self, message):
        self.append_log(f"错误: {message}", "error")

    def _on_parsed_data(self, data):
        self.append_log(", ".join(f"{key}={value}" for key, value in data.items()))

    def append_log(self, text, level="info"):
        color = LOG_COLORS.get(level, LOG_COLORS["info"])
        stamp = datetime.now().strftime("%H:%M:%S")
        body = escape(str(text)).replace("\n", "<br>")
        self._output.append(f'<span style="color:#9399b2">[{stamp}]</span> <span style="color:{color}">{body}</span>')
        self._trim()

    def set_max_lines(self, n):
        self._max_lines = max(50, n)
        self._trim()

    def clear_log(self):
        self._output.clear()

    def _trim(self):
        doc = self._output.document()
        while doc.blockCount() > self._max_lines:
            cursor = self._output.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
