"""MQTT configuration card shared by the designer preview and exported applications."""
from PyQt5.QtWidgets import QLineEdit
from qfluentwidgets import CaptionLabel, CheckBox, ComboBox, LineEdit, SpinBox

from .link_card import LinkConfigCard


class MqttConfigCard(LinkConfigCard):
    LINK = "mqtt"
    TITLE = "MQTT 配置"
    PROPERTY_SETTERS = (
        ("title", "set_title", "MQTT 配置"),
        ("displayMode", "set_display_mode", "完整"),
        ("defaultHost", "set_default_host", "127.0.0.1"),
        ("defaultPort", "set_default_port", 1883),
        ("defaultClientId", "set_default_client_id", ""),
        ("defaultUsername", "set_default_username", ""),
        ("defaultPassword", "set_default_password", ""),
        ("defaultSubscribe", "set_default_subscribe", "device/data"),
        ("defaultPublish", "set_default_publish", "device/cmd"),
        ("defaultQos", "set_default_qos", "0"),
        ("defaultTls", "set_default_tls", False),
        ("defaultParser", "set_default_parser", "项目设置"),
    )

    def _build_rows(self):
        self._host_edit = LineEdit()
        self._host_edit.setText("127.0.0.1")
        self._host_edit.setPlaceholderText("broker 地址")
        self._port_spin = SpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(1883)
        self.add_row("服务器", (self._host_edit, 3), (self._port_spin, 1))
        self._client_id_edit = LineEdit()
        self._client_id_edit.setPlaceholderText("留空自动生成")
        self.add_row("客户端ID", self._client_id_edit, full_only=True)
        self._username_edit = LineEdit()
        self._username_edit.setPlaceholderText("可选")
        self._password_edit = LineEdit()
        self._password_edit.setPlaceholderText("可选")
        self._password_edit.setEchoMode(QLineEdit.Password)
        self.add_row("用户名", (self._username_edit, 1), (CaptionLabel("密码"), 0),
                     (self._password_edit, 1), full_only=True)
        self._subscribe_edit = LineEdit()
        self._subscribe_edit.setText("device/data")
        self._subscribe_edit.setPlaceholderText("多个主题用逗号分隔，支持 + 和 #")
        self.add_row("订阅主题", self._subscribe_edit)
        self._publish_edit = LineEdit()
        self._publish_edit.setText("device/cmd")
        self._publish_edit.setPlaceholderText("命令发往的主题")
        self.add_row("发布主题", self._publish_edit)
        self._qos_combo = ComboBox()
        self._qos_combo.addItems(["0", "1", "2"])
        self._tls_check = CheckBox("TLS")
        self.add_row("QoS", (self._qos_combo, 1), (self._tls_check, 0), full_only=True)
        self._parser_combo = ComboBox()
        self._parser_combo.addItems(self.PARSERS)
        self.add_row("解析模式", self._parser_combo, full_only=True)
        self._editors = [self._host_edit, self._port_spin, self._client_id_edit,
                         self._username_edit, self._password_edit, self._subscribe_edit,
                         self._publish_edit, self._qos_combo, self._tls_check,
                         self._parser_combo]

    def _connect_link(self, handler):
        return handler.connect(
            self.host, self.port, client_id=self._client_id_edit.text(),
            username=self._username_edit.text(), password=self._password_edit.text(),
            subscribe=self._subscribe_edit.text(), publish=self._publish_edit.text(),
            qos=self.qos, tls=self._tls_check.isChecked(), parser_type=self.parser_type)

    # ---- fields ----

    @property
    def host(self):
        return self._host_edit.text().strip()

    @property
    def port(self):
        return self._port_spin.value()

    @property
    def qos(self):
        return int(self._qos_combo.currentText())

    def set_default_host(self, value):
        self._host_edit.setText(str(value))

    def set_default_port(self, value):
        self._port_spin.setValue(int(value))

    def set_default_client_id(self, value):
        self._client_id_edit.setText(str(value))

    def set_default_username(self, value):
        self._username_edit.setText(str(value))

    def set_default_password(self, value):
        self._password_edit.setText(str(value))

    def set_default_subscribe(self, value):
        self._subscribe_edit.setText(str(value))

    def set_default_publish(self, value):
        self._publish_edit.setText(str(value))

    def set_default_qos(self, value):
        index = self._qos_combo.findText(str(value))
        if index >= 0:
            self._qos_combo.setCurrentIndex(index)

    def set_default_tls(self, value):
        self._tls_check.setChecked(bool(value))
