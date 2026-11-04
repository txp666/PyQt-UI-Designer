"""TCP configuration card shared by the designer preview and exported applications."""
from qfluentwidgets import ComboBox, LineEdit, SpinBox

from .link_card import LinkConfigCard
from .link_polling import SLAVE_PROPERTY_SETTERS, ModbusSlaveSettings, add_value_items, select_value
from .tcp_runtime import CLIENT, SERVER, TcpHandler
from .i18n import tr, N_


class TcpConfigCard(ModbusSlaveSettings, LinkConfigCard):
    LINK_CLASS = TcpHandler
    TITLE = N_("TCP 配置")
    MODES = [CLIENT, SERVER]
    PROPERTY_SETTERS = (
        ("title", "set_title", "TCP 配置"),  # i18n: value
        ("displayMode", "set_display_mode", "完整"),  # i18n: value
        ("defaultMode", "set_default_mode", "客户端"),  # i18n: value
        ("defaultHost", "set_default_host", "127.0.0.1"),
        ("defaultPort", "set_default_port", 8080),
        ("defaultParser", "set_default_parser", "项目设置"),  # i18n: value
        ("modbusRole", "set_modbus_role", "主站"),  # i18n: value
        ("modbusPeriod", "set_modbus_period", 500),
        ("modbusTimeout", "set_modbus_timeout", 1000),
        ("modbusSlave", "set_modbus_slave", 1),
        *SLAVE_PROPERTY_SETTERS,
        ("parserConfig", "set_parser_config", {}),
    )

    def _build_rows(self):
        self._peers = 0
        self._mode_combo = ComboBox()
        add_value_items(self._mode_combo, self.MODES)
        self._mode_combo.currentIndexChanged.connect(lambda _index: self._on_mode_changed(self.mode))
        self.add_row(tr("模式"), self._mode_combo)
        self._host_edit = LineEdit()
        self._host_edit.setText("127.0.0.1")
        self.add_row(tr("地址"), self._host_edit)
        self._port_spin = SpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(8080)
        self.add_row(tr("端口"), self._port_spin)
        self._parser_combo = self._parser_box()
        self.add_row(tr("解析模式"), self._parser_combo, full_only=True)
        self._editors = [self._mode_combo, self._host_edit, self._port_spin, self._parser_combo]
        self._on_mode_changed(self.mode)

    def _on_mode_changed(self, mode):
        self._host_edit.setPlaceholderText(
            tr("0.0.0.0 表示所有网卡") if mode == SERVER else tr("设备 IP 或主机名"))

    def _connect_link(self, handler):
        return handler.connect(self.host, self.port, mode=self.mode, parser_type=self.parser_type,
                               parser_config=self.parser_config, slave=self.slave_device)

    def _attach_extra(self, handler):
        self._serial_connections.connect(handler.peersChanged, self._on_peers_changed)

    def _on_peers_changed(self, count):
        self._peers = count
        if self._connected:
            self._show_connected()

    def _connected_text(self):
        # The link may have been started outside the card; report what it is doing.
        mode = getattr(self._handler, "mode", None) or self.mode
        if mode == SERVER:
            return "● " + tr("监听中 · %1 客户端", self._peers)
        return "● " + tr("已连接")

    # ---- fields ----

    @property
    def mode(self):
        return self._mode_combo.currentData()

    @property
    def host(self):
        return self._host_edit.text().strip()

    @property
    def port(self):
        return self._port_spin.value()

    def set_default_mode(self, value):
        select_value(self._mode_combo, str(value))

    def set_default_host(self, value):
        self._host_edit.setText(str(value))

    def set_default_port(self, value):
        self._port_spin.setValue(int(value))
