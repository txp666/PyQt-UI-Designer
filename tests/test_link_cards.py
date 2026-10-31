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
    def tls_set_context(self, context): self.calls.append(("tls", type(context).__module__.split(".")[0]))
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
            button = card._connect_btn  # one button: 连接, 取消 while connecting, 断开
            assert button.isEnabled() and button.text() == "连接"
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
            assert not card._host_edit.isEnabled()
            assert button.isEnabled() and button.text() == "取消", "取消 cancels a pending connection"
            wait_for(lambda: device.hasPendingConnections() and link.is_connected, "the connection")
            peer = device.nextPendingConnection()
            assert card._status.text() == "● 已连接", card._status.text()
            assert button.isEnabled() and button.text() == "断开"
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
            assert button.text() == "连接" and card._host_edit.isEnabled()
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
            QTest.mouseClick(button, Qt.LeftButton)
            assert not link.is_active and card._status.text() == "未连接"
            probe.abort()

            # A refused connection ends with the error in the status.
            card._mode_combo.setCurrentText("客户端")
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            wait_for(lambda: not link.is_active, "the refusal")
            assert card._status.text().startswith("TCP 连接"), card._status.text()
            assert button.isEnabled() and button.text() == "连接"
            check_payloads([b"READ\r\n"])
        ''')

    def test_tcp_card_shows_the_poller_status_and_modbus_commands_go_out_as_mbap(self):
        self.run_both([
            control("tcp", "TcpConfigCard", {"defaultParser": "modbus_tcp", "modbusPeriod": 60000}),
            parity.control("value", "NumericDisplay", {"title": "温度"}, 16) | {
                "binding": {"parseMode": "Modbus", "mbRegIndex": 0, "mbDataType": "uint16"}},
            parity.control("write", "PushButton", {
                "text": "写入", "commandMode": "Modbus", "mbSlave": 1, "mbFunc": "06 写单寄存器",
                "mbAddress": 0, "mbValue": 2}, 17),
        ], r"""
            import time
            from PyQt5.QtNetwork import QHostAddress, QTcpServer, QTcpSocket
            def wait_for(predicate, what):
                deadline = time.monotonic() + 5
                while not predicate() and time.monotonic() < deadline:
                    QTest.qWait(10)
                assert predicate(), f"Timed out waiting for {what}"
            export = os.environ["APPLICATION_MODE"] == "export"
            if not export:  # the preview harness runs no bindings; the poller reads what they show
                from app.core.data_binding import bindingEngine
                bindingEngine.load_bindings_from_project(project.widgets)
            card = widgets["tcp"]
            link = card._handler
            assert card._parser_combo.currentText() == "modbus_tcp"
            device = QTcpServer()
            assert device.listen(QHostAddress(QHostAddress.LocalHost), 0)
            device_port = device.serverPort()
            card._host_edit.setText("127.0.0.1")
            card._port_spin.setValue(device_port)
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            wait_for(lambda: device.hasPendingConnections() and link.is_connected, "the link")
            peer = device.nextPendingConnection()
            assert link.parser_type == "modbus_tcp"

            # Connected, the poller reads the bound register at once, framed as MBAP; the card shows it.
            wait_for(lambda: peer.bytesAvailable() >= 12, "the poller's read")
            request = bytes(peer.readAll())
            assert request[2:] == bytes.fromhex("000000060103 0000 0001".replace(" ", "")), request.hex()
            block = "从站 1 · 功能码 3 · 地址 0–0 · 周期 60000 ms"
            assert (card._status.text(), card._status.toolTip()) == ("● 已连接 · 1 块 · 轮询中", block), \
                card._status.text()
            received = []
            link.dataReceived.connect(received.append)
            peer.write(request[:2] + bytes.fromhex("00000005 010302 0019".replace(" ", "")))
            peer.flush()
            wait_for(lambda: received, "the response")
            assert received == [{"slave": 1, "fc": 3, "reg0": 25, "start": 0, "hr0": 25}], received
            assert (card._status.text(), card._status.toolTip()) == ("● 已连接 · 1 块 · 正常", block), \
                card._status.text()
            if export:
                assert widgets["value"]._value.text() == "25", widgets["value"]._value.text()

            # A Modbus-mode button: the serial port (line parser) gets RTU, the Modbus TCP link MBAP.
            QTest.mouseClick(widgets["write"], Qt.LeftButton)
            check_payloads([bytes.fromhex("010600000002080b")])
            wait_for(lambda: peer.bytesAvailable() >= 12, "the MBAP write")
            write = bytes(peer.readAll())
            assert write[2:] == bytes.fromhex("000000060106 0000 0002".replace(" ", "")), write.hex()
            peer.write(write)  # the device echoes the write
            peer.flush()
            wait_for(lambda: not link.modbus_master.busy(), "the echo")
            assert card._status.text() == "● 已连接 · 1 块 · 正常", card._status.text()
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)  # 断开
            assert not link.is_active
            assert (card._status.text(), card._status.toolTip()) == ("未连接", ""), card._status.text()

            # A server waits for a client first (等待连接 is not shown), then reads from it.
            device.close()
            card._mode_combo.setCurrentText("服务端")
            card._port_spin.setValue(device_port)
            widgets["value"].hide()  # out of sight: nothing to read
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            assert link.is_connected, card._status.text()
            assert (card._status.text(), card._status.toolTip()) == ("● 监听中 · 0 客户端", ""), card._status.text()
            probe = QTcpSocket()
            probe.connectToHost("127.0.0.1", link.port)
            wait_for(lambda: link.peer_count == 1, "the client")
            nothing = "● 监听中 · 1 客户端 · 没有 Modbus 绑定"
            assert (card._status.text(), card._status.toolTip()) == (nothing, nothing), card._status.text()
            # Back in sight, and a shorter period, which counts at once: the register is read now.
            widgets["value"].show()
            card.set_modbus_period(100)
            assert card._status.text() == "● 监听中 · 1 客户端 · 1 块 · 轮询中", card._status.text()
            assert card._status.toolTip() == "从站 1 · 功能码 3 · 地址 0–0 · 周期 100 ms", card._status.toolTip()
            wait_for(lambda: probe.bytesAvailable() >= 12, "the read from the client")
            assert bytes(probe.readAll())[7:] == bytes.fromhex("0300000001"), "an FC03 read of register 0"
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            assert not link.is_active and card._status.text() == "未连接"
            probe.abort()
        """)

    def test_the_first_card_whose_link_is_connected_and_parses_modbus_sets_up_the_poller(self):
        self.run_both([
            control("tcp", "TcpConfigCard", {"defaultParser": "modbus_tcp", "modbusPeriod": 200,
                                             "modbusTimeout": 300, "modbusSlave": 4}),
            control("serial", "SerialConfigCard", {"defaultParser": "modbus", "modbusPeriod": 700,
                                                   "modbusTimeout": 800, "modbusSlave": 9}, 1),
        ], r"""
            import time
            from PyQt5.QtNetwork import QHostAddress, QTcpServer
            def wait_for(predicate, what):
                deadline = time.monotonic() + 5
                while not predicate() and time.monotonic() < deadline:
                    QTest.qWait(10)
                assert predicate(), f"Timed out waiting for {what}"
            if os.environ["APPLICATION_MODE"] == "export":
                from data_binding import ModbusPoller
            else:
                from app.core.modbus_poller import ModbusPoller
            poller, = window.findChildren(ModbusPoller)
            def settings():
                return poller.default_period, poller.timeout, poller.default_slave
            card, link = widgets["tcp"], widgets["tcp"]._handler
            assert settings() == (500, 1000, 1), settings()  # no link parses Modbus yet
            serial.configure({"parser": "modbus"})
            serial.connected.emit("PLC")
            # The TCP card comes first in the document, but its link is not connected.
            assert settings() == (700, 800, 9), settings()
            assert widgets["serial"]._status.text() == "● 已连接 · 没有 Modbus 绑定", widgets["serial"]._status.text()
            device = QTcpServer()
            assert device.listen(QHostAddress(QHostAddress.LocalHost), 0)
            device_port = device.serverPort()
            card._host_edit.setText("127.0.0.1")
            card._port_spin.setValue(device_port)
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            wait_for(lambda: device.hasPendingConnections() and settings() == (200, 300, 4), "the TCP card's settings")
            peer = device.nextPendingConnection()
            assert card._status.text() == "● 已连接 · 没有 Modbus 绑定", card._status.text()
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)  # 断开: the serial card's again
            assert settings() == (700, 800, 9), settings()
            serial.disconnect()
            assert settings() == (500, 1000, 1), settings()
            # A server that listens counts as connected before any device connects; with nothing to
            # send to, the poller waits, which the card does not show.
            device.close()
            card._mode_combo.setCurrentText("服务端")
            card._port_spin.setValue(device_port)
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            assert link.is_connected and settings() == (200, 300, 4), settings()
            assert poller.status() == "等待连接", poller.status()
            assert (card._status.text(), card._status.toolTip()) == ("● 监听中 · 0 客户端", ""), card._status.text()
            card.set_modbus_slave(300)  # out of range: 247 at most, and it counts at once
            assert settings() == (200, 300, 247), settings()
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            assert settings() == (500, 1000, 1), settings()
        """)

    def test_modbus_commands_go_out_as_ascii_frames_and_wait_for_replies_over_a_modbus_ascii_link(self):
        self.run_both([
            control("tcp", "TcpConfigCard", {"defaultParser": "modbus_ascii"}),
            parity.control("read", "PushButton", {
                "text": "读取", "commandMode": "Modbus", "mbSlave": 1, "mbFunc": "03 读保持寄存器",
                "mbAddress": 100, "mbValue": 2}, 16),
        ], r"""
            import time
            from PyQt5.QtNetwork import QHostAddress, QTcpServer
            def wait_for(predicate, what):
                deadline = time.monotonic() + 5
                while not predicate() and time.monotonic() < deadline:
                    QTest.qWait(10)
                assert predicate(), f"Timed out waiting for {what}"
            card = widgets["tcp"]
            assert card._parser_combo.currentText() == "modbus_ascii"
            device = QTcpServer()
            assert device.listen(QHostAddress(QHostAddress.LocalHost), 0)
            card._host_edit.setText("127.0.0.1")
            card._port_spin.setValue(device.serverPort())
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            wait_for(lambda: device.hasPendingConnections() and card._handler.is_connected, "the link")
            peer = device.nextPendingConnection()
            assert card._handler.parser_type == "modbus_ascii"
            nothing = "● 已连接 · 没有 Modbus 绑定"
            assert (card._status.text(), card._status.toolTip()) == (nothing, nothing), card._status.text()

            # The Modbus ASCII link gets ':', uppercase hex, the LRC and CR LF; its master waits for the reply.
            QTest.mouseClick(widgets["read"], Qt.LeftButton)
            request = b":01030064000296\r\n"  # LRC 96: -(01+03+00+64+00+02)
            wait_for(lambda: peer.bytesAvailable() >= len(request), "the ASCII request")
            assert bytes(peer.readAll()) == request
            master = card._handler.modbus_master
            assert master.busy() and master._timer.isActive()
            received = []
            card._handler.dataReceived.connect(received.append)
            peer.write(b":01030400190001DE\r\n")
            peer.flush()
            wait_for(lambda: received, "the response")
            assert received == [{"slave": 1, "fc": 3, "reg0": 25, "reg1": 1,
                                 "start": 100, "hr100": 25, "hr101": 1}], received
            assert not master.busy()
            # No reply: the master gives up once the timeout has passed, which the test decides.
            QTest.mouseClick(widgets["read"], Qt.LeftButton)
            assert master.busy()
            master._timer.timeout.emit()
            assert not master.busy()
            assert card._status.text() == nothing, card._status.text()
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)  # 断开
        """)

    def test_tcp_card_parses_hex_frames_with_its_own_frame_format(self):
        frame_format = {"header": "AA55", "footer": "", "lengthOffset": 2, "checksum": "和校验",
                        "fields": [["cmd", 1, 1, "uint8"], ["temp", 2, 2, "int16", "小端(LE)"]]}
        self.run_both([
            control("tcp", "TcpConfigCard", {"defaultParser": "hex", "parserConfig": frame_format}),
            parity.control("cmd", "Label", {"text": "-"}, 16) | {
                "binding": {"parseMode": "键值匹配", "key": "cmd"}},
            # The link publishes whole frames, so the binding counts from the header's first byte.
            parity.control("temp", "Label", {"text": "-"}, 17) | {
                "binding": {"parseMode": "HEX字节提取", "byteOffset": 4, "dataType": "int16",
                            "byteOrder": "小端(LE)"}},
        ], r'''
            import time
            from PyQt5.QtNetwork import QHostAddress, QTcpServer
            def wait_for(predicate, what):
                deadline = time.monotonic() + 5
                while not predicate() and time.monotonic() < deadline:
                    QTest.qWait(10)
                assert predicate(), f"Timed out waiting for {what}"
            card = widgets["tcp"]
            assert card.parser_config["lengthOffset"] == 2, card.parser_config
            device = QTcpServer()
            assert device.listen(QHostAddress(QHostAddress.LocalHost), 0)
            card._host_edit.setText("127.0.0.1")
            card._port_spin.setValue(device.serverPort())
            raw, received = [], []
            card._handler.rawReceived.connect(raw.append)
            card._handler.dataReceived.connect(received.append)
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            wait_for(lambda: device.hasPendingConnections() and card._handler.is_connected, "the link")
            peer = device.nextPendingConnection()
            frames = [bytes.fromhex("aa550401f6ff3c35"), bytes.fromhex("aa5504021000283d")]
            wire = bytes.fromhex("1234") + frames[0] + frames[0][:-1] + b"\x30" + frames[1]
            peer.write(wire[:6]); peer.flush()
            QTest.qWait(30)
            peer.write(wire[6:]); peer.flush()
            wait_for(lambda: len(received) == 2, "two frames")
            assert raw == frames, raw
            assert received == [{"cmd": 1, "temp": -10}, {"cmd": 2, "temp": 16}], received
            if os.environ["APPLICATION_MODE"] == "export":  # the preview harness runs no bindings
                assert widgets["cmd"].text() == "2", widgets["cmd"].text()
                assert widgets["temp"].text() == "16", widgets["temp"].text()
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)  # 断开
            check_payloads([])
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
            assert client.calls == [("auth", "user", "secret"), ("tls", "truststore"), ("connect", "broker.local", 8883)], client.calls
            assert "连接中" in card._status.text(), card._status.text()
            assert card._connect_btn.isEnabled() and card._connect_btn.text() == "取消"
            # 取消 cancels the attempt and stops paho's network loop.
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            assert not link.is_active and not client.loop_running
            assert card._status.text() == "未连接" and card._connect_btn.text() == "连接"
            QTest.mouseClick(card._connect_btn, Qt.LeftButton)
            client = FakeClient.instances[-1]
            client.fire("on_connect", {}, ReasonCode(0, "Success"), None)
            wait_for(lambda: link.is_connected, "the CONNACK")
            assert client.subscriptions == [("home/+/state", 1)]
            assert card._status.text() == "● 已连接", card._status.text()
            assert not card._host_edit.isEnabled() and card._connect_btn.text() == "断开"
            recv = getattr(widgets["recv"], "_output", None) or widgets["recv"]._text
            assert "已连接: MQTT broker.local:8883" in recv.toPlainText()

            QTest.mouseClick(widgets["read"], Qt.LeftButton)
            check_payloads([b"READ"])
            assert client.published == [("home/cmd", b"READ", 1, False)], client.published
            client.fire("on_message", SimpleNamespace(topic="home/1/state", payload=b"temp=25.5"))
            wait_for(lambda: "temp=25.5" in recv.toPlainText(), "device data")

            # The broker goes away: the card shows the retry and 取消 stays available.
            client.fire("on_disconnect", {}, ReasonCode(128, "Unspecified error"), None)
            wait_for(lambda: not link.is_connected, "the loss")
            assert link.is_active and card._status.text() == "重连中...", card._status.text()
            assert card._connect_btn.isEnabled() and card._connect_btn.text() == "取消"
            assert not card._host_edit.isEnabled()
            client.fire("on_connect", {}, ReasonCode(0, "Success"), None)
            wait_for(lambda: link.is_connected, "the reconnection")
            assert card._status.text() == "● 已连接", card._status.text()

            client.fire("on_connect", {}, ReasonCode(135, "Not authorized"), None)
            wait_for(lambda: not link.is_active, "the rejected session")
            assert card._status.text() == "MQTT 连接失败: 未授权，请检查用户名和密码", card._status.text()
            assert card._connect_btn.text() == "连接" and card._host_edit.isEnabled()
            assert not client.loop_running
            check_payloads([b"READ"])
        ''')


if __name__ == "__main__":
    unittest.main()
