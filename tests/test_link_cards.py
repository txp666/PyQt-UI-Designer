"""The TCP and MQTT cards must drive real links identically in preview and export."""
import textwrap
import unittest

from tests import test_preview_export_parity as parity


def control(name, kind, properties, row=0):
    data = parity.control(name, kind, properties, row)
    data["geometry"].update(x=10, y=10 + row * 460, w=520, h=440)
    return data


_FAKE_PAHO = r'''
import threading
from types import SimpleNamespace

class FakeClient:
    instances = []
    def __init__(self, *args, client_id="", userdata=None, **kwargs):
        self.client_id, self.userdata = client_id, userdata
        self.calls, self.subscriptions, self.published = [], [], []
        self.loop_running = False
        FakeClient.instances.append(self)
    def username_pw_set(self, username, password): self.calls.append(("auth", username, password))
    def tls_set(self): self.calls.append(("tls",))
    def connect_async(self, host, port, keepalive): self.calls.append(("connect", host, port))
    def loop_start(self): self.loop_running = True
    def loop_stop(self): self.loop_running = False
    def disconnect(self): self.calls.append(("disconnect",))
    def subscribe(self, topic, qos): self.subscriptions.append((topic, qos)); return (0, 1)
    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain)); return SimpleNamespace(rc=0)
    def fire(self, name, *args):
        thread = threading.Thread(target=getattr(self, name), args=(self, self.userdata) + args)
        thread.start(); thread.join()

class ReasonCode:
    def __init__(self, value, name): self.value, self.name = value, name
    def __str__(self): return self.name

FakePaho = SimpleNamespace(CallbackAPIVersion=SimpleNamespace(VERSION2="v2"), Client=FakeClient,
                           error_string=lambda code: f"error {code}")
'''


class LinkCardTests(unittest.TestCase):
    run_both = parity.PreviewExportParityTests.run_both

    def test_tcp_card_preserves_configuration_and_drives_a_real_connection(self):
        self.run_both([
            control("tcp", "TcpConfigCard", {
                "title": "网关链路", "displayMode": "简洁", "defaultMode": "服务端",
                "defaultHost": "0.0.0.0", "defaultPort": 9000, "defaultParser": "line",
            }),
            control("recv", "DataRecvCard", {"maxLines": 100}, 1),
            parity.control("read", "PushButton", {"text": "读取", "command": "READ"}, 16),
        ], r'''
            import time
            from PyQt5.QtNetwork import QHostAddress, QTcpServer
            from PyQt5.QtWidgets import QLabel
            def wait_for(predicate, what):
                deadline = time.monotonic() + 5
                while not predicate() and time.monotonic() < deadline:
                    QTest.qWait(10)
                assert predicate(), f"Timed out waiting for {what}"
            card = widgets["tcp"]
            assert "网关链路" in [label.text() for label in card.findChildren(QLabel)]
            assert card.mode == "服务端" and card.host == "0.0.0.0" and card.port == 9000
            assert card._parser_combo.currentText() == "line"
            assert not card._parser_combo.isVisibleTo(card), "简洁 hides the parser row"
            card.set_display_mode("完整")
            assert card._parser_combo.isVisibleTo(card)
            assert card._connect_btn.isEnabled() and not card._disconnect_btn.isEnabled()
            link = card._handler
            assert type(link).__name__ == "TcpHandler" and not link.is_active

            # Act as the device: a server the card's client mode connects to.
            device = QTcpServer()
            assert device.listen(QHostAddress(QHostAddress.LocalHost), 0)
            device_port = device.serverPort()
            card._mode_combo.setCurrentText("客户端")
            card._host_edit.setText("127.0.0.1")
            card._port_spin.setValue(device_port)
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            assert "连接中" in card._status.text(), card._status.text()
            wait_for(lambda: device.hasPendingConnections() and link.is_connected, "the connection")
            peer = device.nextPendingConnection()
            assert card._status.text() == "● 已连接", card._status.text()
            assert not card._connect_btn.isEnabled() and card._disconnect_btn.isEnabled()
            assert not card._host_edit.isEnabled()
            recv = getattr(widgets["recv"], "_output", None) or widgets["recv"]._text
            assert f"已连接: TCP 127.0.0.1:{device_port}" in recv.toPlainText()

            # Commands go out over every connected link: the serial port and TCP.
            QTest.mouseClick(widgets["read"], Qt.LeftButton)
            check_payloads([b"READ\r\n"])
            wait_for(lambda: peer.bytesAvailable() >= 6, "the command over TCP")
            assert bytes(peer.readAll()) == b"READ\r\n"
            peer.write(b"temp=25.5\n"); peer.flush()
            wait_for(lambda: "temp=25.5" in recv.toPlainText(), "device data")

            # The device closes: the card reports it and returns to idle.
            peer.disconnectFromHost()
            wait_for(lambda: not link.is_active, "the close")
            assert card._status.text() == "TCP 连接已被对方关闭", card._status.text()
            assert card._connect_btn.isEnabled() and card._host_edit.isEnabled()
            assert "已断开" in recv.toPlainText()

            # Server mode: the card listens and counts clients.
            device.close()
            card._mode_combo.setCurrentText("服务端")
            card._host_edit.setText("127.0.0.1")
            card._port_spin.setValue(device_port)
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            assert link.is_connected, card._status.text()
            assert card._status.text() == "● 监听中 · 0 客户端", card._status.text()
            from PyQt5.QtNetwork import QTcpSocket
            probe = QTcpSocket()
            probe.connectToHost("127.0.0.1", link.port)
            wait_for(lambda: link.peer_count == 1, "the probe client")
            assert card._status.text() == "● 监听中 · 1 客户端", card._status.text()
            QTest.mouseClick(card._disconnect_btn, Qt.LeftButton)
            assert not link.is_active and card._status.text() == "未连接"
            probe.abort()

            # A refused connection ends with the error in the status.
            card._mode_combo.setCurrentText("客户端")
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            wait_for(lambda: not link.is_active, "the refusal")
            assert card._status.text().startswith("TCP 连接"), card._status.text()
            assert card._connect_btn.isEnabled()
            check_payloads([b"READ\r\n"])
        ''')

    def test_mqtt_card_preserves_configuration_and_publishes_commands(self):
        self.run_both([
            control("mqtt", "MqttConfigCard", {
                "title": "云平台", "displayMode": "简洁", "defaultHost": "broker.local",
                "defaultPort": 8883, "defaultClientId": "panel-1", "defaultUsername": "user",
                "defaultPassword": "secret", "defaultSubscribe": "home/+/state",
                "defaultPublish": "home/cmd", "defaultQos": "1", "defaultTls": True,
                "defaultParser": "line",
            }),
            control("recv", "DataRecvCard", {"maxLines": 100}, 1),
            parity.control("read", "PushButton", {"text": "读取", "command": "READ",
                                                  "commandNewline": "无"}, 16),
        ], textwrap.indent(_FAKE_PAHO, " " * 12) + r'''
            import time
            from PyQt5.QtWidgets import QLabel, QLineEdit
            def wait_for(predicate, what):
                deadline = time.monotonic() + 5
                while not predicate() and time.monotonic() < deadline:
                    QTest.qWait(10)
                assert predicate(), f"Timed out waiting for {what}"
            card = widgets["mqtt"]
            assert "云平台" in [label.text() for label in card.findChildren(QLabel)]
            assert card.host == "broker.local" and card.port == 8883 and card.qos == 1
            assert card._client_id_edit.text() == "panel-1"
            assert card._username_edit.text() == "user"
            assert card._password_edit.text() == "secret"
            assert card._password_edit.echoMode() == QLineEdit.Password
            assert card._subscribe_edit.text() == "home/+/state"
            assert card._publish_edit.text() == "home/cmd"
            assert card._tls_check.isChecked()
            assert card._parser_combo.currentText() == "line"
            for hidden in (card._client_id_edit, card._username_edit, card._qos_combo, card._parser_combo):
                assert not hidden.isVisibleTo(card), "简洁 hides advanced rows"
            assert card._subscribe_edit.isVisibleTo(card) and card._publish_edit.isVisibleTo(card)
            card.set_display_mode("完整")
            assert card._qos_combo.isVisibleTo(card)
            link = card._handler
            assert type(link).__name__ == "MqttHandler" and not link.is_active
            sys.modules[type(link).__module__].mqtt = FakePaho

            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            client = FakeClient.instances[-1]
            assert client.client_id == "panel-1"
            assert client.calls == [("auth", "user", "secret"), ("tls",), ("connect", "broker.local", 8883)], client.calls
            assert "连接中" in card._status.text(), card._status.text()
            client.fire("on_connect", {}, ReasonCode(0, "Success"), None)
            wait_for(lambda: link.is_connected, "the CONNACK")
            assert client.subscriptions == [("home/+/state", 1)]
            assert card._status.text() == "● 已连接", card._status.text()
            assert not card._host_edit.isEnabled() and card._disconnect_btn.isEnabled()
            recv = getattr(widgets["recv"], "_output", None) or widgets["recv"]._text
            assert "已连接: MQTT broker.local:8883" in recv.toPlainText()

            QTest.mouseClick(widgets["read"], Qt.LeftButton)
            check_payloads([b"READ"])
            assert client.published == [("home/cmd", b"READ", 1, False)], client.published
            client.fire("on_message", SimpleNamespace(topic="home/1/state", payload=b"temp=25.5"))
            wait_for(lambda: "temp=25.5" in recv.toPlainText(), "device data")

            client.fire("on_connect", {}, ReasonCode(5, "Not authorized"), None)
            wait_for(lambda: not link.is_active, "the rejected session")
            assert card._status.text() == "MQTT 连接失败: Not authorized", card._status.text()
            assert card._connect_btn.isEnabled() and card._host_edit.isEnabled()
            assert not client.loop_running
            check_payloads([b"READ"])
        ''')


if __name__ == "__main__":
    unittest.main()
