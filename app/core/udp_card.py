"""UDP configuration card shared by the designer preview and exported applications."""
from qfluentwidgets import LineEdit, SpinBox

from .link_card import LinkConfigCard
from .link_polling import SLAVE_PROPERTY_SETTERS, ModbusSlaveSettings
from .udp_runtime import UdpHandler
from .i18n import tr, N_


class UdpConfigCard(ModbusSlaveSettings, LinkConfigCard):
    LINK_CLASS = UdpHandler
    TITLE = N_("UDP 配置")
    PROPERTY_SETTERS = (
        ("title", "set_title", "UDP 配置"),  # i18n: value
        ("displayMode", "set_display_mode", "完整"),  # i18n: value
        ("defaultLocalPort", "set_default_local_port", 0),
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
        self._local_port_spin = SpinBox()
        self._local_port_spin.setRange(0, 65535)
        self._local_port_spin.setSpecialValueText(tr("自动"))  # 0: the system picks a free port
        self._local_port_spin.setValue(0)
        self.add_row(tr("本地端口"), self._local_port_spin)
        self._host_edit = LineEdit()
        self._host_edit.setText("127.0.0.1")
        self._host_edit.setPlaceholderText(tr("留空则回复最后发送方"))
        self._port_spin = SpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(8080)
        self.add_row(tr("远程"), (self._host_edit, 3), (self._port_spin, 1))
        self._parser_combo = self._parser_box()
        self.add_row(tr("解析模式"), self._parser_combo, full_only=True)
        self._editors = [self._local_port_spin, self._host_edit, self._port_spin, self._parser_combo]

    def _connect_link(self, handler):
        return handler.connect(self.local_port, self.host, self.port, parser_type=self.parser_type,
                               parser_config=self.parser_config, slave=self.slave_device)

    def _attach_extra(self, handler):
        self._serial_connections.connect(handler.canSendChanged, self._on_can_send_changed)

    def _on_can_send_changed(self, _can_send):
        if self._connected:
            self._show_connected()

    def _connected_text(self):
        return "● " + tr("监听中 :%1", getattr(self._handler, "local_port", self.local_port))

    # ---- fields ----

    @property
    def local_port(self):
        return self._local_port_spin.value()

    @property
    def host(self):
        return self._host_edit.text().strip()

    @property
    def port(self):
        return self._port_spin.value()

    def set_default_local_port(self, value):
        self._local_port_spin.setValue(int(value))

    def set_default_host(self, value):
        self._host_edit.setText(str(value))

    def set_default_port(self, value):
        self._port_spin.setValue(int(value))
