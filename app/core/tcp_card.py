"""TCP configuration card shared by the designer preview and exported applications."""
from qfluentwidgets import ComboBox, LineEdit, SpinBox

from .link_card import LinkConfigCard


class TcpConfigCard(LinkConfigCard):
    LINK = "tcp"
    TITLE = "TCP 配置"
    MODES = ["客户端", "服务端"]
    PROPERTY_SETTERS = (
        ("title", "set_title", "TCP 配置"),
        ("displayMode", "set_display_mode", "完整"),
        ("defaultMode", "set_default_mode", "客户端"),
        ("defaultHost", "set_default_host", "127.0.0.1"),
        ("defaultPort", "set_default_port", 8080),
        ("defaultParser", "set_default_parser", "项目设置"),
        ("modbusPeriod", "set_modbus_period", 500),
        ("modbusTimeout", "set_modbus_timeout", 1000),
        ("modbusSlave", "set_modbus_slave", 1),
        ("parserConfig", "set_parser_config", {}),
    )

    def _build_rows(self):
        self._peers = 0
        self._mode_combo = ComboBox()
        self._mode_combo.addItems(self.MODES)
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        self.add_row("模式", self._mode_combo)
        self._host_edit = LineEdit()
        self._host_edit.setText("127.0.0.1")
        self.add_row("地址", self._host_edit)
        self._port_spin = SpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(8080)
        self.add_row("端口", self._port_spin)
        self._parser_combo = ComboBox()
        self._parser_combo.addItems(self.PARSERS)
        self.add_row("解析模式", self._parser_combo, full_only=True)
        self._editors = [self._mode_combo, self._host_edit, self._port_spin, self._parser_combo]
        self._on_mode_changed(self._mode_combo.currentText())

    def _on_mode_changed(self, mode):
        self._host_edit.setPlaceholderText(
            "0.0.0.0 表示所有网卡" if mode == "服务端" else "设备 IP 或主机名")

    def _connect_link(self, handler):
        return handler.connect(self.host, self.port, mode=self.mode, parser_type=self.parser_type,
                               parser_config=self.parser_config)

    def _attach_extra(self, handler):
        self._serial_connections.connect(handler.peersChanged, self._on_peers_changed)

    def _on_peers_changed(self, count):
        self._peers = count
        if self._connected:
            self._show_connected()

    def _connected_text(self):
        # The link may have been started outside the card; report what it is doing.
        mode = getattr(self._handler, "mode", None) or self.mode
        if mode == "服务端":
            return f"● 监听中 · {self._peers} 客户端"
        return "● 已连接"

    # ---- fields ----

    @property
    def mode(self):
        return self._mode_combo.currentText()

    @property
    def host(self):
        return self._host_edit.text().strip()

    @property
    def port(self):
        return self._port_spin.value()

    def set_default_mode(self, value):
        index = self._mode_combo.findText(str(value))
        if index >= 0:
            self._mode_combo.setCurrentIndex(index)

    def set_default_host(self, value):
        self._host_edit.setText(str(value))

    def set_default_port(self, value):
        self._port_spin.setValue(int(value))
