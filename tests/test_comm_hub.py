"""One hub fronts the links the link cards own, in the designer and in exports."""
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
from app.core.command_runtime import send_modbus_command
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
        """The hub and the three link classes, as the designer has them and as an export has them."""
        serial, tcp, mqtt, hub = {}, {}, {}, {}
        exec(_gen_serial_handler({}), serial)
        modules = {"serial_handler": SimpleNamespace(**serial)}
        with patch.dict(sys.modules, modules):
            exec(_gen_tcp_handler({}), tcp)
            exec(_gen_mqtt_handler({}), mqtt)
        mqtt["mqtt"] = FakePaho2
        exec(_gen_comm_hub(), hub)
        host = {**vars(comm_runtime), "SerialHandler": serial_runtime.SerialHandler,
                "TcpHandler": tcp_runtime.TcpHandler, "MqttHandler": mqtt_runtime.MqttHandler}
        exported = {**hub, "SerialHandler": serial["SerialHandler"], "TcpHandler": tcp["TcpHandler"],
                    "MqttHandler": mqtt["MqttHandler"]}
        return host, exported

    def make(self, namespace, config=None):
        hub = namespace["CommHub"](config=config)

        def cleanup():
            hub.disconnect()
            for link in hub.links:
                link.deleteLater()
            hub.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

        self.addCleanup(cleanup)
        return hub

    def add(self, hub, namespace, kind):
        """A link of the kind, registered on the hub as a link card registers its own."""
        link = namespace[kind]()
        hub.add_link(link)
        return link

    def wait_for(self, predicate, what):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate(), f"Timed out waiting for {what}")

    def test_hub_forwards_every_link_and_sends_over_all_connected_links(self):
        for namespace in self.runtimes():
            hub = self.make(namespace)
            serial, tcp = self.add(hub, namespace, "SerialHandler"), self.add(hub, namespace, "TcpHandler")
            # The project's settings count for the links registered so far and those registered later.
            hub.configure({"baudRate": 9600, "parser": "line", "parserConfig": {"separator": ";"}})
            mqtt = self.add(hub, namespace, "MqttHandler")
            self.assertEqual(hub.links, [serial, tcp, mqtt])
            self.assertEqual(serial._config["baudRate"], 9600)
            self.assertEqual(tcp._config["parser"], "line")
            self.assertEqual(mqtt._config["parserConfig"], {"separator": ";"})
            self.assertNotIn("baudRate", tcp._config)
            self.assertNotIn("baudRate", mqtt._config)
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
            serial._port = port
            self.assertTrue(hub.is_connected)
            self.assertEqual(hub.connected_links, [serial])
            self.assertTrue(tcp.connect("127.0.0.1", 0, mode="服务端"))
            peer = tcp_runtime.TcpHandler()
            self.addCleanup(peer.deleteLater)
            self.addCleanup(peer.disconnect)
            received = []
            peer.rawReceived.connect(received.append)
            self.assertTrue(peer.connect("127.0.0.1", tcp.port))
            self.wait_for(lambda: peer.is_connected and tcp.peer_count == 1, "the TCP peer")
            self.assertTrue(mqtt.connect(subscribe="in", publish="out"))
            client = FakeClient.instances[-1]
            client.fire("on_connect", {}, ReasonCode(0, "Success"), None)
            self.wait_for(lambda: mqtt.is_connected, "the broker")
            self.assertEqual(hub.connected_links, [serial, tcp, mqtt])
            self.assertEqual([event for event in events if event[0] == "connected"],
                             [("connected", f"TCP 服务端 127.0.0.1:{tcp.port}"),
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

            tcp.disconnect()
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

    def test_modbus_requests_are_framed_for_each_connected_link(self):
        for namespace in self.runtimes():
            hub = self.make(namespace, {"parser": "modbus"})
            serial, tcp = self.add(hub, namespace, "SerialHandler"), self.add(hub, namespace, "TcpHandler")
            port = MemoryPort()
            serial._port = port
            self.assertEqual(serial.parser_type, "modbus")
            self.assertTrue(tcp.connect("127.0.0.1", 0, mode="服务端", parser_type="modbus_tcp"))
            peer = tcp_runtime.TcpHandler()
            self.addCleanup(peer.deleteLater)
            self.addCleanup(peer.disconnect)
            received = []
            peer.rawReceived.connect(received.append)
            self.assertTrue(peer.connect("127.0.0.1", tcp.port))
            self.wait_for(lambda: peer.is_connected and tcp.peer_count == 1, "the TCP peer")
            frames = send_modbus_command(hub, 1, 6, 10, 500)
            self.assertEqual(port.sent, [bytes.fromhex("0106000a01f4a9df")])
            self.wait_for(lambda: received, "the MBAP frame")
            self.assertEqual(received[0][2:], bytes.fromhex("000000060106000a01f4"))
            self.assertEqual(frames, [port.sent[0], received[0]])
            with self.assertRaises(ValueError):
                send_modbus_command(hub, 1, 6, 10, 70000)
            self.assertEqual(len(port.sent), 1)

    def test_designer_hub_publishes_on_the_signal_bus(self):
        from app.common.signal_bus import signalBus
        from app.core.comm_manager import commHub
        self.assertEqual(commHub.links, [])  # the hub has no link of its own
        host, _exported = self.runtimes()
        serial, tcp, mqtt = (self.add(commHub, host, kind) for kind in ("SerialHandler", "TcpHandler", "MqttHandler"))
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
            tcp.connected.emit("TCP x")
            mqtt.dataReceived.emit({"v": 1})
            serial.rawReceived.emit(b"raw")
            tcp.dataSent.emit(b"sent")
            mqtt.error.emit("boom")
            tcp.disconnected.emit()
            self.assertEqual(seen, [("connected", "TCP x"), ("data", {"v": 1}), ("raw", b"raw"),
                                    ("sent", b"sent"), ("error", "boom"), ("disconnected",)])
        finally:
            for connection in connections:
                signalBus.disconnect(connection)
            for link in (serial, tcp, mqtt):
                commHub.remove_link(link)
                link.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(commHub.links, [])

    def test_each_card_owns_its_link_while_it_is_on_a_hub(self):
        from app.core.mqtt_card import MqttConfigCard
        from app.core.serial_card import SerialConfigCard
        from app.core.tcp_card import TcpConfigCard
        hub = self.make(vars(comm_runtime))
        cards = [SerialConfigCard(), TcpConfigCard(), MqttConfigCard()]
        try:
            for card, kind in zip(cards, (serial_runtime.SerialHandler, tcp_runtime.TcpHandler,
                                          mqtt_runtime.MqttHandler)):
                self.assertIsNone(card.link)  # on the designer canvas a card has no link
                card.set_serial_handler(hub)
                link = card.link
                self.assertIs(type(link), kind)
                self.assertIs(link.parent(), card)
                self.assertIs(hub.links[-1], link)
                card.set_serial_handler(hub)
                self.assertIs(card.link, link)
                card.set_serial_handler(None)
                self.assertIsNone(card.link)
                self.assertNotIn(link, hub.links)
                card.set_serial_handler(hub)
                self.assertIsNot(card.link, link)
            self.assertEqual(hub.links, [card.link for card in cards])
            # A card that goes away takes its link off the hub.
            cards.pop(1).deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertEqual(hub.links, [card.link for card in cards])
        finally:
            for card in cards:
                card.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(hub.links, [])

    def test_exported_hub_configures_the_exported_links(self):
        host, exported = self.runtimes()
        self.assertIsNot(exported["SerialHandler"], serial_runtime.SerialHandler)
        self.assertIsNot(exported["CommHub"], comm_runtime.CommHub)
        hub = self.make(exported, {"parser": "modbus", "parserConfig": {"fields": ["t"]}})
        serial, tcp = self.add(hub, exported, "SerialHandler"), self.add(hub, exported, "TcpHandler")
        self.assertEqual(serial.parser_type, "modbus")
        self.assertEqual(tcp._config["parserConfig"], {"fields": ["t"]})
        self.assertEqual(protocol.create_parser(*(tcp._config[k] for k in ("parser", "parserConfig"))).feed(
            bytes.fromhex("0103020009") + protocol.modbus_crc(bytes.fromhex("0103020009"))),
            [{"slave": 1, "fc": 3, "t": 9}])


if __name__ == "__main__":
    unittest.main()
