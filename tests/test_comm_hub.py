"""One hub fronts the serial, TCP and MQTT links in the designer and in exports."""
import os
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.core import comm_runtime, mqtt_runtime, protocol_parser as protocol, serial_runtime, tcp_runtime
from app.core.code_generator import _gen_comm_hub, _gen_mqtt_handler, _gen_serial_handler, _gen_tcp_handler
from tests.test_mqtt_runtime import FakeClient, FakePaho2, ReasonCode


class MemoryPort:
    def __init__(self):
        self.is_open = True
        self.sent = []

    def write(self, data):
        self.sent.append(data)
        return len(data)

    def close(self):
        self.is_open = False


class CommHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        FakeClient.instances.clear()
        paho = patch.object(mqtt_runtime, "mqtt", FakePaho2)
        paho.start()
        self.addCleanup(paho.stop)

    def runtimes(self):
        serial, tcp, mqtt, hub = {}, {}, {}, {}
        exec(_gen_serial_handler({}), serial)
        modules = {"serial_handler": SimpleNamespace(**serial)}
        with patch.dict(sys.modules, modules):
            exec(_gen_tcp_handler({}), tcp)
            exec(_gen_mqtt_handler({}), mqtt)
        mqtt["mqtt"] = FakePaho2
        modules.update(tcp_handler=SimpleNamespace(**tcp), mqtt_handler=SimpleNamespace(**mqtt))
        with patch.dict(sys.modules, modules):
            exec(_gen_comm_hub(), hub)
        return vars(comm_runtime), hub

    def make(self, namespace, config=None):
        hub = namespace["CommHub"](config=config)

        def cleanup():
            hub.disconnect()
            hub.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

        self.addCleanup(cleanup)
        return hub

    def wait_for(self, predicate, what):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate(), f"Timed out waiting for {what}")

    def test_hub_forwards_every_link_and_sends_over_all_connected_links(self):
        for namespace in self.runtimes():
            hub = self.make(namespace, {"baudRate": 9600, "parser": "line",
                                        "parserConfig": {"separator": ";"}})
            self.assertEqual(hub.tcp._config["parser"], "line")
            self.assertEqual(hub.mqtt._config["parserConfig"], {"separator": ";"})
            self.assertNotIn("baudRate", hub.tcp._config)
            events, states = [], []
            hub.connected.connect(lambda name: events.append(("connected", name)))
            hub.disconnected.connect(lambda: events.append(("disconnected",)))
            hub.error.connect(lambda message: events.append(("error", message)))
            hub.dataReceived.connect(lambda data: events.append(("data", data)))
            hub.rawReceived.connect(lambda data: events.append(("raw", data)))
            hub.dataSent.connect(lambda data: events.append(("sent", data)))
            hub.connectionChanged.connect(states.append)
            self.assertFalse(hub.is_connected)
            self.assertFalse(hub.send(b"nobody"))
            hub.disconnect()
            self.assertEqual(events, [])

            port = MemoryPort()
            hub.serial._port = port
            self.assertTrue(hub.is_connected)
            self.assertEqual(hub.connected_links, [hub.serial])
            self.assertTrue(hub.tcp.connect("127.0.0.1", 0, mode="服务端"))
            peer = tcp_runtime.TcpHandler()
            self.addCleanup(peer.deleteLater)
            self.addCleanup(peer.disconnect)
            received = []
            peer.rawReceived.connect(received.append)
            self.assertTrue(peer.connect("127.0.0.1", hub.tcp.port))
            self.wait_for(lambda: peer.is_connected and hub.tcp.peer_count == 1, "the TCP peer")
            self.assertTrue(hub.mqtt.connect(subscribe="in", publish="out"))
            client = FakeClient.instances[-1]
            client.fire("on_connect", {}, ReasonCode(0, "Success"), None)
            self.wait_for(lambda: hub.mqtt.is_connected, "the broker")
            self.assertEqual(hub.connected_links, [hub.serial, hub.tcp, hub.mqtt])
            self.assertEqual([event for event in events if event[0] == "connected"],
                             [("connected", f"TCP 服务端 127.0.0.1:{hub.tcp.port}"),
                              ("connected", "MQTT 127.0.0.1:1883")])
            self.assertEqual(states, [True, True])

            self.assertTrue(hub.send_text("READ\n"))
            self.assertEqual(port.sent, [b"READ\n"])
            self.wait_for(lambda: received == [b"READ\n"], "the TCP delivery")
            self.assertEqual(client.published, [("out", b"READ\n", 0, False)])
            self.assertEqual([event for event in events if event[0] == "sent"], [("sent", b"READ\n")] * 3)

            self.assertTrue(peer.send(b"a=1;b=2\n"))
            client.fire("on_message", SimpleNamespace(topic="in", payload=b"c=3"))
            self.wait_for(lambda: len([e for e in events if e[0] == "data"]) == 2, "both frames")
            # The broker's queued message and the socket's round trip race each other.
            self.assertCountEqual([e[1] for e in events if e[0] == "data"], [{"a": 1, "b": 2}, {"c": 3}])

            hub.tcp.disconnect()
            self.assertTrue(hub.is_connected)
            self.assertEqual(states, [True, True, True])
            hub.disconnect()
            self.assertFalse(hub.is_connected)
            self.assertFalse(port.is_open)
            self.assertFalse(client.loop_running)
            self.assertEqual(events.count(("disconnected",)), 3)
            self.assertEqual(states[-1], False)
            hub.disconnect()
            self.assertEqual(events.count(("disconnected",)), 3)

    def test_designer_hub_publishes_on_the_signal_bus(self):
        from app.common.signal_bus import signalBus
        from app.core.comm_manager import commHub
        from app.core.serial_manager import serialManager
        self.assertIs(serialManager, commHub.serial)
        self.assertIsInstance(commHub.tcp, tcp_runtime.TcpHandler)
        self.assertIsInstance(commHub.mqtt, mqtt_runtime.MqttHandler)
        self.assertIsInstance(commHub.serial, serial_runtime.SerialHandler)
        seen = []
        connections = [
            signalBus.serialConnected.connect(lambda name: seen.append(("connected", name))),
            signalBus.serialDataReceived.connect(lambda data: seen.append(("data", data))),
            signalBus.serialRawReceived.connect(lambda data: seen.append(("raw", data))),
            signalBus.serialDataSent.connect(lambda data: seen.append(("sent", data))),
            signalBus.serialError.connect(lambda message: seen.append(("error", message))),
            signalBus.serialDisconnected.connect(lambda: seen.append(("disconnected",))),
        ]
        try:
            commHub.tcp.connected.emit("TCP x")
            commHub.mqtt.dataReceived.emit({"v": 1})
            commHub.serial.rawReceived.emit(b"raw")
            commHub.tcp.dataSent.emit(b"sent")
            commHub.mqtt.error.emit("boom")
            commHub.tcp.disconnected.emit()
            self.assertEqual(seen, [("connected", "TCP x"), ("data", {"v": 1}), ("raw", b"raw"),
                                    ("sent", b"sent"), ("error", "boom"), ("disconnected",)])
        finally:
            for connection in connections:
                signalBus.disconnect(connection)

    def test_cards_resolve_a_hub_to_their_own_link(self):
        from app.core.mqtt_card import MqttConfigCard
        from app.core.serial_card import SerialConfigCard
        from app.core.tcp_card import TcpConfigCard
        hub = self.make(vars(comm_runtime))
        cards = [SerialConfigCard(), TcpConfigCard(), MqttConfigCard()]
        try:
            for card, link in zip(cards, hub.links):
                card.set_serial_handler(hub)
                self.assertIs(card._handler, link)
                card.set_serial_handler(link)
                self.assertIs(card._handler, link)
                self.assertEqual(getattr(hub, card.LINK), link)
                card.set_serial_handler(None)
                self.assertIsNone(card._handler)
        finally:
            for card in cards:
                card.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_exported_hub_uses_the_exported_link_modules(self):
        host, exported = self.runtimes()
        self.assertIsNot(exported["SerialHandler"], serial_runtime.SerialHandler)
        hub = self.make(exported, {"parser": "modbus", "parserConfig": {"fields": ["t"]}})
        self.assertIs(type(hub.serial), exported["SerialHandler"])
        self.assertIs(type(hub.tcp), exported["TcpHandler"])
        self.assertIs(type(hub.mqtt), exported["MqttHandler"])
        self.assertEqual(hub.link("tcp"), hub.tcp)
        with self.assertRaises(ValueError):
            hub.link("udp")
        self.assertEqual(hub.tcp._config["parserConfig"], {"fields": ["t"]})
        self.assertEqual(protocol.create_parser(*(hub.tcp._config[k] for k in ("parser", "parserConfig"))).feed(
            bytes.fromhex("0103020009") + protocol.modbus_crc(bytes.fromhex("0103020009"))),
            [{"slave": 1, "fc": 3, "t": 9}])


if __name__ == "__main__":
    unittest.main()
