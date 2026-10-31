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
from app.core.command_runtime import send_modbus_command

HEX_CONFIG = {"parser": "hex", "parserConfig": {
    "header": "AA55", "footer": "55AA", "fields": [["v", 0, 2, "uint16"]]}}
# Frames counted by a length field and checked by a sum, and frames ended by silence: a quiet far
# longer than a loopback write takes, so each frame sent in one write is flushed whole.
COUNTED = {"header": "AA55", "footer": "", "lengthOffset": 2, "checksum": "和校验",
           "fields": [["cmd", 1, 1, "uint8"], ["temp", 2, 2, "int16", "小端(LE)"]]}
FRAMES = [bytes.fromhex("aa550401f6ff3c35"), bytes.fromhex("aa5504021000283d")]
MESSAGES = [{"cmd": 1, "temp": -10}, {"cmd": 2, "temp": 16}]
IDLE = {"header": "7E", "footer": "", "idleTimeout": 200, "fields": [["a", 0, 1, "uint8"]]}


class TcpLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def runtimes(self, config=None):
        exported = {}
        with patch.dict(sys.modules, {"serial_handler": SimpleNamespace(
                create_parser=protocol.create_parser, text_encoding=protocol.text_encoding,
                ModbusRequests=protocol.ModbusRequests)}):
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
            QTest.qWait(50)
            self.assertEqual(self.of(server_events, "raw"), [], "a hex link publishes whole frames")
            self.assertTrue(second.send(bytes.fromhex("aa55000255aa")))
            self.wait_for(lambda: self.of(server_events, "data"), "the second peer's frame")
            self.assertTrue(first.send(bytes.fromhex("0155aa")))
            self.wait_for(lambda: len(self.of(server_events, "data")) == 2, "the first peer's frame")
            self.assertEqual(self.of(server_events, "data"), [{"v": 2}, {"v": 1}])
            self.assertEqual(self.of(server_events, "raw"),
                             [bytes.fromhex("aa55000255aa"), bytes.fromhex("aa55000155aa")])

            self.assertTrue(server.send(b"all=1\n"))
            self.wait_for(lambda: ("data", {"all": 1}) in first_events
                          and ("data", {"all": 1}) in second_events, "the broadcast")
            second.disconnect()
            self.wait_for(lambda: server.peer_count == 1, "one peer left")
            self.assertTrue(server.send(b"one=1\n"))
            self.wait_for(lambda: ("data", {"one": 1}) in first_events, "the remaining peer")
            self.assertNotIn(("data", {"one": 1}), second_events)

    def test_hex_links_publish_each_frame_and_flush_after_the_line_goes_quiet(self):
        for namespace in self.runtimes():
            server, client = self.make(namespace), self.make(namespace)
            server_events, client_events = self.record(server), self.record(client)
            # The server's peers frame by silence; the client counts its frames.
            self.assertTrue(server.connect("127.0.0.1", 0, mode="服务端", parser_type="hex",
                                           parser_config=IDLE))
            self.assertTrue(client.connect("127.0.0.1", server.port, parser_type="hex",
                                           parser_config=COUNTED))
            self.wait_for(lambda: client.is_connected and server.peer_count == 1, "the client")

            wire = b"\x12" + b"".join(FRAMES)
            self.assertTrue(server.send(wire[:6]))
            self.assertTrue(server.send(wire[6:]))
            self.wait_for(lambda: len(self.of(client_events, "data")) == 2, "both frames")
            self.assertEqual([event[1] for event in client_events if event[0] in ("raw", "data")],
                             [FRAMES[0], MESSAGES[0], FRAMES[1], MESSAGES[1]], "each frame, then its message")

            for quiet_frame, message in ((bytes.fromhex("7e0102"), {"a": 1}), (bytes.fromhex("7e05"), {"a": 5})):
                self.assertTrue(client.send(quiet_frame))
                self.wait_for(lambda: ("data", message) in server_events, "the quiet after a frame")
            self.assertEqual(self.of(server_events, "raw"), [bytes.fromhex("7e0102"), bytes.fromhex("7e05")])

            # A client that frames by silence flushes on its own timer, and not once it is closed.
            client.disconnect()
            self.wait_for(lambda: server.peer_count == 0, "the client to leave")
            idle_client = self.make(namespace)
            idle_events = self.record(idle_client)
            self.assertTrue(idle_client.connect("127.0.0.1", server.port, parser_type="hex",
                                                parser_config=IDLE))
            self.wait_for(lambda: idle_client.is_connected and server.peer_count == 1, "the idle client")
            self.assertTrue(server.send(bytes.fromhex("337e09")))
            self.wait_for(lambda: self.of(idle_events, "data"), "the client's quiet")
            self.assertEqual(self.of(idle_events, "raw"), [bytes.fromhex("7e09")])
            self.assertEqual(self.of(idle_events, "data"), [{"a": 9}])
            timer, = idle_client._idle_timers.values()
            timer.setInterval(60000)  # from here the test decides when it fires
            self.assertTrue(server.send(bytes.fromhex("7e0a")))
            self.wait_for(timer.isActive, "the next frame to arrive")
            idle_client.disconnect()
            timer.timeout.emit()  # a tick already due as the stream closed
            self.assertEqual(len(self.of(idle_events, "raw")), 1, "a closed stream is not flushed")

    def test_invalid_parameters_never_open_anything(self):
        for namespace in self.runtimes():
            handler = self.make(namespace)
            events = self.record(handler)
            for arguments in (
                dict(host="127.0.0.1", port=0),
                dict(host="", port=80),
                dict(host="127.0.0.1", port=70000),
                dict(host="127.0.0.1", port=80, mode="udp"),
                dict(host="127.0.0.1", port=80, parser_type="hex", parser_config={"header": "XYZ"}),
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

    def test_modbus_tcp_link_frames_requests_with_mbap_and_parses_responses(self):
        config = {"parser": "modbus_tcp", "parserConfig": {"fields": ["temperature"]}}
        for namespace in self.runtimes(config):
            device, host = self.make(namespace), self.make(namespace, config)
            device_events, host_events = self.record(device), self.record(host)
            # A line link passes on the raw bytes as they arrive, and they hold no newline.
            self.assertTrue(device.connect("127.0.0.1", 0, mode="服务端", parser_type="line"))
            self.assertTrue(host.connect("127.0.0.1", device.port))
            self.wait_for(lambda: host.is_connected and device.peer_count == 1, "the host link")
            self.assertEqual(host.parser_type, "modbus_tcp")
            self.assertEqual(len(send_modbus_command(host, 1, 3, 0, 2)), 1)
            self.wait_for(lambda: self.of(device_events, "raw"), "the request")
            request = b"".join(self.of(device_events, "raw"))
            self.assertEqual(request[2:], bytes.fromhex("000000060103 00000002".replace(" ", "")))
            response = request[:2] + bytes.fromhex("0000 0007 01 03 04 00ff 0001".replace(" ", ""))
            self.assertTrue(device.send(response[:5]))
            QTest.qWait(30)
            self.assertTrue(device.send(response[5:]))
            self.wait_for(lambda: self.of(host_events, "data"), "the response")
            # The link noted the read, so its registers are also named by address.
            self.assertEqual(self.of(host_events, "data"),
                             [{"slave": 1, "fc": 3, "temperature": 255, "reg1": 1,
                               "start": 0, "hr0": 255, "hr1": 1}])
            # The same link framed as RTU over TCP keeps the CRC.
            self.assertTrue(host.connect("127.0.0.1", device.port, parser_type="modbus"))
            self.wait_for(lambda: host.is_connected and device.peer_count == 1, "the RTU link")
            self.assertEqual(host.parser_type, "modbus")
            del device_events[:]
            self.assertEqual(len(send_modbus_command(host, 1, 3, 0, 2)), 1)
            self.wait_for(lambda: self.of(device_events, "raw"), "the RTU request")
            self.assertEqual(b"".join(self.of(device_events, "raw")).hex(), "010300000002c40b")

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
