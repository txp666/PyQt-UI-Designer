"""The MQTT link must parse every message on the GUI thread and survive paho's callbacks."""
import os
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.core import mqtt_runtime
from app.core import protocol_parser as protocol
from app.core.code_generator import _gen_mqtt_handler
from app.core.mqtt_runtime import mqtt_topics


class FakeMessage:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload


class ReasonCode:
    """paho 2 passes objects with a numeric value and a readable name."""

    def __init__(self, value, name):
        self.value, self.name = value, name

    def __str__(self):
        return self.name


class FakeClient:
    instances = []

    def __init__(self, *args, client_id="", userdata=None, **kwargs):
        self.api = args[0] if args else None
        self.client_id, self.userdata = client_id, userdata
        self.calls, self.subscriptions, self.published = [], [], []
        self.loop_running = False
        FakeClient.instances.append(self)

    def username_pw_set(self, username, password):
        self.calls.append(("auth", username, password))

    def tls_set(self):
        self.calls.append(("tls",))

    def connect_async(self, host, port, keepalive):
        self.calls.append(("connect", host, port, keepalive))

    def loop_start(self):
        self.loop_running = True

    def loop_stop(self):
        self.loop_running = False

    def disconnect(self):
        self.calls.append(("disconnect",))

    def subscribe(self, topic, qos):
        self.subscriptions.append((topic, qos))
        return (0, len(self.subscriptions))

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return SimpleNamespace(rc=0)

    def fire(self, name, *args):
        """Run a callback on another thread, as paho's network loop does."""
        thread = threading.Thread(target=getattr(self, name), args=(self, self.userdata) + args)
        thread.start()
        thread.join()


class FakePaho2:
    CallbackAPIVersion = SimpleNamespace(VERSION2="v2")
    Client = FakeClient

    @staticmethod
    def error_string(code):
        return f"error {code}"


class FakePaho1:
    Client = FakeClient

    @staticmethod
    def connack_string(code):
        return f"connack {code}"

    @staticmethod
    def error_string(code):
        return f"error {code}"


class MqttLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        FakeClient.instances.clear()

    def runtimes(self, config=None, paho=FakePaho2):
        exported = {}
        with patch.dict(sys.modules, {"serial_handler": SimpleNamespace(
                create_parser=protocol.create_parser)}):
            exec(_gen_mqtt_handler(config or {}), exported)
        host = patch.object(mqtt_runtime, "mqtt", paho)
        host.start()
        self.addCleanup(host.stop)
        exported["mqtt"] = paho
        return vars(mqtt_runtime), exported

    def make(self, namespace, config=None):
        handler = namespace["MqttHandler"](config=config)

        def cleanup():
            handler.disconnect()
            handler.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

        self.addCleanup(cleanup)
        return handler

    @staticmethod
    def record(handler):
        events = []
        handler.connected.connect(lambda name: events.append(("connected", name)))
        handler.disconnected.connect(lambda: events.append(("disconnected",)))
        handler.error.connect(lambda message: events.append(("error", message)))
        handler.dataReceived.connect(lambda data: events.append(("data", data)))
        handler.rawReceived.connect(lambda data: events.append(("raw", data)))
        handler.dataSent.connect(lambda data: events.append(("sent", data)))
        return events

    def wait_for(self, predicate, what):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate(), f"Timed out waiting for {what}")

    @staticmethod
    def of(events, kind):
        return [event[1] for event in events if event[0] == kind]

    def connect(self, handler, **overrides):
        self.assertTrue(handler.connect(**overrides))
        client = FakeClient.instances[-1]
        self.assertTrue(handler.is_active and not handler.is_connected)
        client.fire("on_connect", {}, ReasonCode(0, "Success"), None)
        self.wait_for(lambda: handler.is_connected, "the CONNACK")
        return client

    def test_topic_lists_accept_separators_and_drop_duplicates(self):
        self.assertEqual(mqtt_topics("a/b, c/#;\n d/+ ,a/b, "), ["a/b", "c/#", "d/+"])
        self.assertEqual(mqtt_topics(["x", " y ", "x"]), ["x", "y"])
        self.assertEqual(mqtt_topics(None), [])

    def test_connect_subscribes_parses_each_message_as_a_frame_and_publishes(self):
        for namespace in self.runtimes():
            handler = self.make(namespace)
            events = self.record(handler)
            client = self.connect(handler, host=" broker.local ", port=8883, username="user",
                                  password="secret", subscribe="s/1, s/2", publish="cmd",
                                  qos=1, tls=True, client_id="panel")
            self.assertEqual(client.api, "v2")
            self.assertEqual(client.client_id, "panel")
            self.assertEqual(client.calls, [("auth", "user", "secret"), ("tls",),
                                            ("connect", "broker.local", 8883, 60)])
            self.assertEqual(client.subscriptions, [("s/1", 1), ("s/2", 1)])
            self.assertEqual(events, [("connected", "MQTT broker.local:8883")])

            client.fire("on_message", FakeMessage("s/1", b'{"temp": 25.5}'))
            client.fire("on_message", FakeMessage("s/2", b"42"))
            client.fire("on_message", FakeMessage("s/2", b"a=1,b=2"))
            self.wait_for(lambda: len(self.of(events, "data")) == 3, "three messages")
            self.assertEqual(self.of(events, "data"), [
                {"temp": 25.5}, {"ch0": 42, "s/2": 42}, {"a": 1, "b": 2}])
            self.assertEqual(self.of(events, "raw"), [b'{"temp": 25.5}', b"42", b"a=1,b=2"])

            self.assertTrue(handler.send(b"LED_ON\r\n"))
            self.assertEqual(client.published, [("cmd", b"LED_ON\r\n", 1, False)])
            self.assertEqual(self.of(events, "sent"), [b"LED_ON\r\n"])
            handler.disconnect()
            self.assertFalse(client.loop_running)
            self.assertEqual(client.calls[-1], ("disconnect",))
            self.assertEqual(events[-1], ("disconnected",))
            self.assertFalse(handler.send(b"x"))
            handler.disconnect()
            self.assertEqual(events.count(("disconnected",)), 1)

    def test_hex_frames_are_buffered_per_topic(self):
        config = {"parser": "hex", "parserConfig": {
            "header": "AA55", "footer": "55AA", "fields": [["v", 0, 2, "uint16"]]}}
        for namespace in self.runtimes(config):
            handler = self.make(namespace, config)
            events = self.record(handler)
            client = self.connect(handler, subscribe="dev/#")
            client.fire("on_message", FakeMessage("dev/1", bytes.fromhex("aa5500")))
            client.fire("on_message", FakeMessage("dev/2", bytes.fromhex("aa55000255aa")))
            client.fire("on_message", FakeMessage("dev/1", bytes.fromhex("0155aa")))
            self.wait_for(lambda: len(self.of(events, "data")) == 2, "both frames")
            self.assertEqual(self.of(events, "data"), [{"v": 2}, {"v": 1}])

    def test_connection_loss_keeps_reconnecting_and_stale_callbacks_are_ignored(self):
        for namespace in self.runtimes():
            handler = self.make(namespace)
            events = self.record(handler)
            client = self.connect(handler, subscribe="t")
            client.fire("on_disconnect", {}, ReasonCode(128, "Unspecified error"), None)
            self.wait_for(lambda: ("disconnected",) in events, "the loss")
            self.assertEqual(events[-2:], [("error", "MQTT 连接断开，正在重连"), ("disconnected",)])
            self.assertTrue(handler.is_active and not handler.is_connected)
            self.assertTrue(client.loop_running, "paho's loop keeps reconnecting")
            client.fire("on_message", FakeMessage("t", b"1"))
            client.fire("on_connect", {}, ReasonCode(0, "Success"), None)
            self.wait_for(lambda: handler.is_connected, "the reconnection")
            self.assertEqual(events[-1], ("connected", "MQTT 127.0.0.1:1883"))
            client.fire("on_disconnect", {}, ReasonCode(141, "Keep alive timeout"), None)
            self.wait_for(lambda: not handler.is_connected, "the keepalive loss")
            self.assertEqual(events[-2], ("error", "MQTT 连接断开，正在重连: Keep alive timeout"))
            client.fire("on_connect", {}, ReasonCode(0, "Success"), None)
            self.wait_for(lambda: handler.is_connected, "the second reconnection")
            self.assertEqual(client.subscriptions, [("t", 0)] * 3)
            self.assertEqual(self.of(events, "data"), [], "messages while down are dropped")

            handler.disconnect()
            count = len(events)
            client.fire("on_message", FakeMessage("t", b"late"))
            client.fire("on_connect", {}, ReasonCode(0, "Success"), None)
            client.fire("on_disconnect", {}, ReasonCode(0, "Normal"), None)
            QTest.qWait(100)
            self.assertEqual(events[count:], [])
            self.assertFalse(handler.is_active)

    def test_failed_connections_stop_the_network_loop(self):
        for namespace in self.runtimes():
            handler = self.make(namespace)
            events = self.record(handler)
            self.assertTrue(handler.connect(username="u"))
            refused = FakeClient.instances[-1]
            refused.fire("on_connect", {}, ReasonCode(135, "Not authorized"), None)
            self.wait_for(lambda: not handler.is_active, "the rejected connection")
            self.assertFalse(refused.loop_running)
            self.assertEqual(events, [("error", "MQTT 连接失败: 未授权，请检查用户名和密码"),
                                      ("disconnected",)])
            self.assertTrue(handler.connect())
            FakeClient.instances[-1].fire("on_connect", {}, ReasonCode(159, "Connection rate exceeded"), None)
            self.wait_for(lambda: not handler.is_active, "the rate-limited connection")
            self.assertEqual(events[-2], ("error", "MQTT 连接失败: Connection rate exceeded"))

            self.assertTrue(handler.connect(host="nowhere"))
            unreachable = FakeClient.instances[-1]
            unreachable.fire("on_connect_fail")
            self.wait_for(lambda: not handler.is_active, "the unreachable broker")
            self.assertFalse(unreachable.loop_running)
            self.assertEqual(events[-2:], [("error", "MQTT 连接失败: 无法连接到服务器"),
                                           ("disconnected",)])
            self.assertTrue(handler.connect(host="secure", tls=True))
            FakeClient.instances[-1].fire("on_connect_fail")
            self.wait_for(lambda: not handler.is_active, "the failed TLS connection")
            self.assertEqual(events[-2], ("error", "MQTT 连接失败: 无法连接到服务器"
                                                   "（已启用 TLS，请检查端口和服务器证书）"))

    def test_paho_1_signatures_and_missing_dependency(self):
        for namespace in self.runtimes(paho=FakePaho1):
            handler = self.make(namespace)
            events = self.record(handler)
            self.assertTrue(handler.connect(subscribe="t", publish="c"))
            client = FakeClient.instances[-1]
            self.assertIsNone(client.api)
            self.assertTrue(client.client_id.startswith("pyqt-ui-"))
            client.fire("on_connect", {}, 0)
            self.wait_for(lambda: handler.is_connected, "the v1 CONNACK")
            client.fire("on_message", FakeMessage("t", b"7"))
            self.wait_for(lambda: self.of(events, "data"), "the v1 message")
            self.assertEqual(self.of(events, "data"), [{"ch0": 7, "t": 7}])
            client.fire("on_disconnect", 7)
            self.wait_for(lambda: not handler.is_connected, "the v1 loss")
            self.assertEqual(events[-2], ("error", "MQTT 连接断开，正在重连"))
            client.fire("on_connect", {}, 0)
            self.wait_for(lambda: handler.is_connected, "the v1 reconnection")
            client.fire("on_disconnect", 16)
            self.wait_for(lambda: not handler.is_connected, "the second v1 loss")
            self.assertEqual(events[-2], ("error", "MQTT 连接断开，正在重连: error 16"))
            handler.disconnect()
            self.assertTrue(handler.connect(username="u"))
            FakeClient.instances[-1].fire("on_connect", {}, 4)
            self.wait_for(lambda: not handler.is_active, "the v1 refusal")
            self.assertEqual(events[-2], ("error", "MQTT 连接失败: 用户名或密码错误"))
            with patch.object(mqtt_runtime, "mqtt", None), patch.dict(namespace, {"mqtt": None}):
                self.assertFalse(handler.connect())
            self.assertEqual(events[-1], ("error", "paho-mqtt 未安装，请运行 pip install paho-mqtt"))

    def test_invalid_parameters_and_exported_defaults(self):
        project = {"baudRate": 9600, "parser": "modbus", "parserConfig": {"fields": ["t"]}}
        for namespace in self.runtimes(project):
            FakeClient.instances.clear()
            handler = self.make(namespace)
            events = self.record(handler)
            for arguments in (
                dict(host=""), dict(port=0), dict(port=70000), dict(qos=3),
                dict(parser_type="hex", parser_config={"header": ""}),
            ):
                with self.subTest(**arguments):
                    self.assertFalse(handler.connect(**arguments))
                    self.assertFalse(handler.is_active)
                    self.assertTrue(events[-1][1].startswith("MQTT 参数无效"), events[-1])
            self.assertEqual(len(events), 5)
            self.assertEqual(FakeClient.instances, [])
            exported = namespace["MqttHandler"].DEFAULT_CONFIG
            if exported:
                self.assertEqual(exported, {"parser": "modbus", "parserConfig": {"fields": ["t"]}})
            handler = self.make(namespace, project)
            events = self.record(handler)
            client = self.connect(handler, subscribe="bus")
            client.fire("on_message", FakeMessage(
                "bus", bytes.fromhex("0103020009") + protocol.modbus_crc(bytes.fromhex("0103020009"))))
            self.wait_for(lambda: self.of(events, "data"), "the Modbus frame")
            self.assertEqual(self.of(events, "data"), [{"slave": 1, "fc": 3, "t": 9}])


if __name__ == "__main__":
    unittest.main()
