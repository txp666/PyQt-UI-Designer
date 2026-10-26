"""Real loopback sockets must give the host and exported TCP links identical behaviour."""
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

from app.core import protocol_parser as protocol
from app.core import tcp_runtime
from app.core.code_generator import _gen_tcp_handler

HEX_CONFIG = {"parser": "hex", "parserConfig": {
    "header": "AA55", "footer": "55AA", "fields": [["v", 0, 2, "uint16"]]}}


class TcpLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def runtimes(self, config=None):
        exported = {}
        with patch.dict(sys.modules, {"serial_handler": SimpleNamespace(
                create_parser=protocol.create_parser)}):
            exec(_gen_tcp_handler(config or {}), exported)
        return vars(tcp_runtime), exported

    def make(self, namespace, config=None):
        handler = namespace["TcpHandler"](config=config)

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
        handler.peersChanged.connect(lambda count: events.append(("peers", count)))
        return events

    def wait_for(self, predicate, what):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate(), f"Timed out waiting for {what}")

    @staticmethod
    def of(events, kind):
        return [event[1] for event in events if event[0] == kind]

    def test_server_and_client_exchange_frames_split_across_writes(self):
        for namespace in self.runtimes():
            server, client = self.make(namespace), self.make(namespace)
            server_events, client_events = self.record(server), self.record(client)
            self.assertTrue(server.connect("127.0.0.1", 0, mode="服务端"))
            self.assertTrue(server.is_connected)
            self.assertGreater(server.port, 0)
            self.assertEqual(server_events, [("connected", f"TCP 服务端 127.0.0.1:{server.port}")])
            self.assertTrue(client.connect("127.0.0.1", server.port))
            self.assertFalse(client.is_connected)
            self.wait_for(lambda: client.is_connected and server.peer_count == 1, "the client")
            self.assertEqual(client_events, [("connected", f"TCP 127.0.0.1:{server.port}")])
            self.assertIn(("peers", 1), server_events)

            self.assertTrue(client.send(b"temp=25.5,hu"))
            QTest.qWait(30)
            self.assertTrue(client.send(b"mi=60\na=1\n"))
            self.wait_for(lambda: len(self.of(server_events, "data")) == 2, "two frames")
            self.assertEqual(self.of(server_events, "data"), [{"temp": 25.5, "humi": 60}, {"a": 1}])
            self.assertEqual(b"".join(self.of(server_events, "raw")), b"temp=25.5,humi=60\na=1\n")
            self.assertEqual(self.of(client_events, "sent"), [b"temp=25.5,hu", b"mi=60\na=1\n"])

            self.assertTrue(server.send(b"READ\n"))
            self.wait_for(lambda: ("data", {"ch0": "READ"}) in client_events, "the command")
            self.assertEqual(self.of(server_events, "sent"), [b"READ\n"])

            client.disconnect()
            self.assertFalse(client.is_active)
            self.assertEqual(client_events[-1], ("disconnected",))
            self.wait_for(lambda: server.peer_count == 0, "the peer to leave")
            self.assertEqual(server_events[-1], ("peers", 0))
            self.assertFalse(server.send(b"x"))
            self.assertEqual(server_events[-1], ("error", "发送失败: 没有已连接的 TCP 客户端"))
            server.disconnect()
            self.assertFalse(server.is_connected)
            self.assertEqual(server_events[-1], ("disconnected",))
            client.disconnect()  # idle: nothing more to report
            self.assertEqual(client_events[-1], ("disconnected",))
            self.assertEqual(client_events.count(("disconnected",)), 1)

    def test_server_close_and_refused_connection_report_error_then_disconnected(self):
        for namespace in self.runtimes():
            server, client = self.make(namespace), self.make(namespace)
            client_events = self.record(client)
            self.assertTrue(server.connect("", 0, mode="server"))
            self.assertTrue(server.description.startswith("TCP 服务端 0.0.0.0:"))
            port = server.port
            self.assertTrue(client.connect("127.0.0.1", port))
            self.wait_for(lambda: client.is_connected, "the client")
            server.disconnect()
            self.wait_for(lambda: ("disconnected",) in client_events, "the close")
            self.assertEqual(client_events[-2:],
                             [("error", "TCP 连接已被对方关闭"), ("disconnected",)])
            self.assertFalse(client.is_active)

            refused = self.make(namespace)
            events = self.record(refused)
            self.assertTrue(refused.connect("127.0.0.1", port))
            self.wait_for(lambda: ("disconnected",) in events, "the refusal")
            errors = self.of(events, "error")
            self.assertEqual(len(errors), 1, events)
            self.assertTrue(errors[0].startswith("TCP 连接"), errors)
            self.assertEqual(events[-1], ("disconnected",))
            self.assertFalse(refused.is_active)

    def test_each_peer_has_its_own_parser_and_commands_reach_every_peer(self):
        for namespace in self.runtimes(HEX_CONFIG):
            server = self.make(namespace, HEX_CONFIG)
            first, second = self.make(namespace), self.make(namespace)
            server_events = self.record(server)
            first_events, second_events = self.record(first), self.record(second)
            self.assertTrue(server.connect("127.0.0.1", 0, mode="服务端"))
            for client in (first, second):
                self.assertTrue(client.connect("127.0.0.1", server.port, parser_type="line"))
            self.wait_for(lambda: server.peer_count == 2 and first.is_connected
                          and second.is_connected, "both clients")
            self.assertTrue(first.send(bytes.fromhex("aa5500")))
            self.wait_for(lambda: self.of(server_events, "raw"), "the first half")
            self.assertTrue(second.send(bytes.fromhex("aa55000255aa")))
            self.wait_for(lambda: self.of(server_events, "data"), "the second peer's frame")
            self.assertTrue(first.send(bytes.fromhex("0155aa")))
            self.wait_for(lambda: len(self.of(server_events, "data")) == 2, "the first peer's frame")
            self.assertEqual(self.of(server_events, "data"), [{"v": 2}, {"v": 1}])

            self.assertTrue(server.send(b"all=1\n"))
            self.wait_for(lambda: ("data", {"all": 1}) in first_events
                          and ("data", {"all": 1}) in second_events, "the broadcast")
            second.disconnect()
            self.wait_for(lambda: server.peer_count == 1, "one peer left")
            self.assertTrue(server.send(b"one=1\n"))
            self.wait_for(lambda: ("data", {"one": 1}) in first_events, "the remaining peer")
            self.assertNotIn(("data", {"one": 1}), second_events)

    def test_invalid_parameters_never_open_anything(self):
        for namespace in self.runtimes():
            handler = self.make(namespace)
            events = self.record(handler)
            for arguments in (
                dict(host="127.0.0.1", port=0),
                dict(host="", port=80),
                dict(host="127.0.0.1", port=70000),
                dict(host="127.0.0.1", port=80, mode="udp"),
                dict(host="127.0.0.1", port=80, parser_type="hex", parser_config={"header": ""}),
                dict(host="not an address", port=0, mode="服务端"),
            ):
                with self.subTest(**arguments):
                    self.assertFalse(handler.connect(**arguments))
                    self.assertFalse(handler.is_active)
                    self.assertTrue(events[-1][0] == "error"
                                    and events[-1][1].startswith("TCP 参数无效"), events[-1])
            self.assertEqual(len(events), 6)

    def test_project_parser_and_overrides_match_serial_rules(self):
        for namespace in self.runtimes(HEX_CONFIG):
            server, client = self.make(namespace, HEX_CONFIG), self.make(namespace, HEX_CONFIG)
            server_events, client_events = self.record(server), self.record(client)
            self.assertTrue(server.connect("127.0.0.1", 0, mode="服务端"))
            # Another mode drops the project's hex settings instead of applying them to lines.
            self.assertTrue(client.connect("127.0.0.1", server.port, parser_type="line"))
            self.wait_for(lambda: client.is_connected and server.peer_count == 1, "the client")
            self.assertTrue(client.send(bytes.fromhex("aa55002a55aa")))
            self.wait_for(lambda: self.of(server_events, "data"), "the hex frame")
            self.assertEqual(self.of(server_events, "data"), [{"v": 42}])
            self.assertTrue(server.send(b"x=1\n"))
            self.wait_for(lambda: self.of(client_events, "data"), "the line")
            self.assertEqual(self.of(client_events, "data"), [{"x": 1}])
        exported = self.runtimes({"baudRate": 9600, "parity": "Even", **HEX_CONFIG})[1]
        self.assertEqual(exported["TcpHandler"].DEFAULT_CONFIG, HEX_CONFIG)

    def test_reconnecting_replaces_the_previous_link(self):
        for namespace in self.runtimes():
            first, second, client = self.make(namespace), self.make(namespace), self.make(namespace)
            states = []
            client.connectionChanged.connect(states.append)
            for server in (first, second):
                self.assertTrue(server.connect("127.0.0.1", 0, mode="服务端"))
            self.assertTrue(client.connect("127.0.0.1", first.port))
            self.wait_for(lambda: first.peer_count == 1, "the first connection")
            self.assertTrue(client.connect("127.0.0.1", second.port))
            self.wait_for(lambda: second.peer_count == 1 and first.peer_count == 0,
                          "the replacement connection")
            self.assertEqual(states, [True, False, True])
            self.assertEqual(client.description, f"TCP 127.0.0.1:{second.port}")


if __name__ == "__main__":
    unittest.main()
