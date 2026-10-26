"""Shared frame of the TCP and MQTT configuration cards.

The frame provides the title and status row, labelled option rows, the connect and
disconnect buttons, and the link signal wiring. A subclass adds its option rows and
tells its link how to connect. Cards work in the designer preview and, from the same
source, in exported applications.
"""
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
from qfluentwidgets import (
    CardWidget, StrongBodyLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, FluentIcon as FIF, qconfig,
)

from .signal_lifetime import SignalConnections

STATUS_COLORS = {
    "idle": ("#606060", "#b0b0b0"),
    "ok": ("#237b27", "#81c784"),
    "error": ("#c62828", "#ff8a80"),
    "busy": ("#8a4b00", "#ffb74d"),
}


class LinkConfigCard(CardWidget):
    LINK = ""  # name of this card's link on a CommHub
    TITLE = "连接配置"
    LABEL_WIDTH = 56
    PARSERS = ["项目设置", "line", "hex", "modbus", "modbus_tcp"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._display_mode = "完整"
        self._connected = False
        self._failed = False
        self._handler = None
        self._editors = []
        self._full_only = []
        self._serial_connections = SignalConnections(self)
        self._theme_connections = SignalConnections(self)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 12, 16, 12)
        self._root.setSpacing(10)

        self._title_w = self._make_row()
        self._title = StrongBodyLabel(self.TITLE)
        self._status = CaptionLabel("未连接")
        self._title_w.layout().addWidget(self._title)
        self._title_w.layout().addStretch()
        self._title_w.layout().addWidget(self._status)
        self._root.addWidget(self._title_w)

        self._build_rows()

        self._btn_w = self._make_row()
        self._connect_btn = PrimaryPushButton(FIF.CONNECT, "连接")
        self._disconnect_btn = PushButton(FIF.CLOSE, "断开")
        self._disconnect_btn.setEnabled(False)
        self._connect_btn.clicked.connect(self._on_connect)
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        self._btn_w.layout().addWidget(self._connect_btn, 1)
        self._btn_w.layout().addWidget(self._disconnect_btn, 1)
        self._root.addWidget(self._btn_w)
        self._root.addStretch(1)

        self._set_status("未连接", "idle")
        self._theme_connections.connect(qconfig.themeChangedFinished, self.update)

    # ---- layout helpers ----

    @staticmethod
    def _make_row(spacing=8):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        return row

    def add_row(self, label, *items, full_only=False):
        """Add a labelled row; an item is a widget or a (widget, stretch) pair."""
        row = self._make_row()
        caption = BodyLabel(label)
        caption.setFixedWidth(self.LABEL_WIDTH)
        row.layout().addWidget(caption)
        for item in items:
            widget, stretch = item if isinstance(item, tuple) else (item, 1)
            row.layout().addWidget(widget, stretch)
        self._root.addWidget(row)
        if full_only:
            self._full_only.append(row)
        return row

    def _build_rows(self):
        raise NotImplementedError

    def _connect_link(self, handler):
        """Start the link from the card's current fields; return the handler's result."""
        raise NotImplementedError

    def _attach_extra(self, handler):
        """Subscribe to link signals beyond connected/disconnected/error."""

    def _connected_text(self):
        return "● 已连接"

    # ---- link wiring ----

    def set_serial_handler(self, handler):
        """Attach this card's link; a CommHub is resolved to the link named by LINK."""
        if self.LINK:
            handler = getattr(handler, self.LINK, handler)
        if handler is self._handler:
            return
        self._serial_connections.clear()
        self._handler = handler
        if handler is not None:
            self._serial_connections.connect(handler.connected, self._on_link_connected)
            self._serial_connections.connect(handler.disconnected, self._on_link_disconnected)
            self._serial_connections.connect(handler.error, self._on_link_error)
            self._attach_extra(handler)
            self.set_connected(handler.is_connected)

    def _on_connect(self):
        if self._handler is None:
            return
        self._failed = False
        self._connect_btn.setEnabled(False)
        self._set_status("连接中...", "busy")
        ok = self._connect_link(self._handler)
        if not ok:
            self._connect_btn.setEnabled(True)
            if not self._failed:
                self._set_status("连接失败", "error")

    def _on_disconnect(self):
        if self._handler is None:
            return
        self._handler.disconnect()
        if not getattr(self._handler, "is_active", self._handler.is_connected):
            self.set_connected(False)

    def _on_link_connected(self, _description):
        self.set_connected(True)

    def _on_link_disconnected(self):
        self.set_connected(False)

    def _on_link_error(self, message):
        self._failed = True
        brief = message if len(message) <= 40 else message[:39] + "…"
        self._set_status(brief, "error")
        self._status.setToolTip(message)

    def set_connected(self, connected):
        self._connected = connected
        self._connect_btn.setEnabled(not connected)
        self._disconnect_btn.setEnabled(connected)
        for editor in self._editors:
            editor.setEnabled(not connected)
        if connected:
            self._failed = False
            self._set_status(self._connected_text(), "ok")
        elif not self._failed:
            self._set_status("未连接", "idle")

    def _set_status(self, text, kind):
        light, dark = STATUS_COLORS[kind]
        self._status.setText(text)
        self._status.setTextColor(QColor(light), QColor(dark))
        if kind != "error":
            self._status.setToolTip("")

    # ---- property setters ----

    def set_title(self, title):
        self._title.setText(title)

    def set_display_mode(self, mode):
        self._display_mode = mode
        for row in self._full_only:
            row.setVisible(mode == "完整")
        self.adjustSize()
        self.updateGeometry()

    def set_default_parser(self, value):
        index = self._parser_combo.findText(str(value))
        if index >= 0:
            self._parser_combo.setCurrentIndex(index)

    @property
    def parser_type(self):
        """None selects the project's parser settings."""
        text = self._parser_combo.currentText()
        return None if text == "项目设置" else text
