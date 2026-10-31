"""The Modbus master queue every link owns, and the block planner of the Modbus poller, in the designer
and in the exported serial_handler.py."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication

from app.core import command_runtime, modbus_master, tcp_runtime
from app.core.code_generator import _gen_serial_handler
from app.core.command_runtime import modbus_request

VECTORS = Path(__file__).resolve().parent / "data" / "poll_plan_vectors.json"


class Link(QObject):
    """A connected link that parses Modbus and records what it is asked to send."""
    dataReceived = pyqtSignal(dict)
    disconnected = pyqtSignal()

    def __init__(self, master_class=None, parser_type="modbus"):
        super().__init__()
        self.parser_type, self.is_connected, self.accept, self.sent = parser_type, True, True, []
        if master_class is not None:
            self.modbus_master = master_class(self)

    def send(self, data):
        self.sent.append(bytes(data))
        return self.accept


def rtu(*request):
    return modbus_master.modbus_frame(modbus_request(*request))


class ModbusMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        exported = {}
        exec(_gen_serial_handler({}), exported)
        cls.namespaces = (vars(modbus_master), exported)

    def link(self, namespace, parser_type="modbus"):
        link = Link(namespace["ModbusMaster"], parser_type)
        self.addCleanup(link.deleteLater)
        return link

    def test_plans_match_the_vectors_both_repositories_share(self):
        cases = json.loads(VECTORS.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 17)
        for namespace in self.namespaces:
            for case in cases:
                with self.subTest(case=case["name"]):
                    self.assertEqual(namespace["plan_blocks"](case["needs"], case["defaultPeriod"]),
                                     case["blocks"])

    def test_one_request_on_the_wire_and_writes_ahead_of_waiting_reads(self):
        for namespace in self.namespaces:
            link = self.link(namespace)
            master, done = link.modbus_master, []
            first = master.enqueue(modbus_request(1, 3, 100, 2), 1000, "read", done.append)
            self.assertEqual(first, rtu(1, 3, 100, 2))
            master.enqueue(modbus_request(1, 3, 200, 2), 1000, "read", done.append)
            master.enqueue(modbus_request(1, 6, 10, 500), 1000, "write", done.append)
            master.enqueue(modbus_request(1, 5, 3, 0xFF00), 1000, "write", done.append)
            self.assertEqual(link.sent, [first], "the others wait for the reply")
            self.assertTrue(master.busy())
            self.assertEqual(master.pending(), 3)
            # Writes go ahead of the waiting read, in the order they came.
            link.dataReceived.emit({"slave": 1, "fc": 3, "reg0": 7, "reg1": 8, "start": 100})
            self.assertEqual(link.sent[-1], rtu(1, 6, 10, 500))
            link.dataReceived.emit({"slave": 1, "fc": 6, "address": 10, "value": 500})
            self.assertEqual(link.sent[-1], rtu(1, 5, 3, 0xFF00))
            link.dataReceived.emit({"slave": 1, "fc": 5, "address": 3, "value": 0xFF00})
            self.assertEqual(link.sent[-1], rtu(1, 3, 200, 2))
            self.assertEqual([result.ok for result in done], [True, True, True])
            self.assertEqual(done[0].message["reg1"], 8)
            self.assertEqual(done[0].problem, "")
            # MBAP and ASCII links get their own frames.
            tcp = self.link(namespace, "modbus_tcp")
            namespace["_transaction"][0] = 0x40
            self.assertEqual(tcp.modbus_master.enqueue(modbus_request(1, 3, 0, 2)).hex(), "004100000006010300000002")
            ascii_link = self.link(namespace, "modbus_ascii")
            self.assertEqual(ascii_link.modbus_master.enqueue(modbus_request(1, 3, 100, 2)), b":01030064000296\r\n")

    def test_replies_pair_by_slave_function_code_and_address(self):
        for namespace in self.namespaces:
            link = self.link(namespace)
            master, done = link.modbus_master, []
            master.enqueue(modbus_request(1, 3, 100, 2), 1000, "read", done.append)
            for other in ({"slave": 2, "fc": 3, "reg0": 1, "start": 100},   # another slave
                          {"slave": 1, "fc": 4, "reg0": 1, "start": 100},   # another table
                          {"slave": 1, "fc": 3, "reg0": 1, "start": 200},   # another block
                          {"slave": 1, "fc": 3, "reg0": 1}):                # another count: no start
                link.dataReceived.emit(other)
            self.assertEqual(done, [])
            link.dataReceived.emit({"slave": 1, "fc": 0x83, "error": 2, "start": 100})
            self.assertEqual((done[0].ok, done[0].problem), (False, "设备返回异常 02 非法数据地址"))
            master.enqueue(modbus_request(1, 6, 10, 500), 1000, "write", done.append)
            link.dataReceived.emit({"slave": 1, "fc": 6, "address": 11, "value": 500})  # another register
            self.assertEqual(len(done), 1)
            link.dataReceived.emit({"slave": 1, "fc": 0x86, "error": 3})  # an exception names no address
            self.assertEqual(done[1].problem, "设备返回异常 03 非法数据值")
            self.assertEqual(done[1].message, {"slave": 1, "fc": 0x86, "error": 3})
            self.assertFalse(master.busy())

    def test_timeouts_disconnects_and_refused_requests(self):
        for namespace in self.namespaces:
            link = self.link(namespace)
            master, done = link.modbus_master, []
            master.enqueue(modbus_request(1, 3, 0, 1), 250, "read", done.append)
            master.enqueue(modbus_request(1, 3, 10, 1), 400, "read", done.append)
            self.assertEqual(master._timer.interval(), 250)
            master._timer.timeout.emit()  # no reply in time: the next one goes out
            self.assertEqual((done[0].ok, done[0].message, done[0].problem), (False, {}, "无响应（250 ms 超时）"))
            self.assertEqual(link.sent[-1], rtu(1, 3, 10, 1))
            master.enqueue(modbus_request(1, 3, 20, 1), 300, "read", done.append)
            # The link goes down: every request ends as timed out, the one on the wire and the waiting one.
            link.disconnected.emit()
            self.assertEqual([result.problem for result in done[1:]], ["无响应（400 ms 超时）", "无响应（300 ms 超时）"])
            self.assertFalse(master.busy() or master.pending() or master._timer.isActive())
            sent = len(link.sent)
            link.is_connected = False
            self.assertIsNone(master.enqueue(modbus_request(1, 3, 0, 1), 1000, "read", done.append))
            link.is_connected, link.accept = True, False  # the link refuses what would go out at once
            self.assertIsNone(master.enqueue(modbus_request(1, 3, 0, 1), 1000, "read", done.append))
            self.assertEqual((len(done), len(link.sent), master.busy()), (3, sent + 1, False))
            # A card withdraws the reads it has not sent yet; the one on the wire keeps its callback.
            link.accept, owner = True, object()
            master.enqueue(modbus_request(1, 3, 0, 1), 1000, "read", done.append, owner=owner)
            master.enqueue(modbus_request(1, 3, 5, 1), 1000, "read", done.append, owner=owner)
            master.withdraw(owner)
            self.assertEqual((master.busy(), master.pending()), (True, 0))

    def test_commands_queue_on_modbus_links_and_go_straight_out_on_the_others(self):
        for namespace in self.namespaces:
            line, plc = self.link(namespace, "line"), self.link(namespace)
            hub = SimpleNamespace(connected_links=[line, plc], is_connected=True)
            plc.modbus_master.enqueue(modbus_request(1, 3, 0, 1))  # a poll read on the wire
            write = modbus_request(1, 6, 10, 500)
            accepted = namespace["modbus_dispatch"](hub, write, 1000, "write")
            self.assertEqual(line.sent, [rtu(1, 6, 10, 500)], "a line link is written at once")
            self.assertEqual(plc.sent, [rtu(1, 3, 0, 1)], "the PLC link finishes its read first")
            self.assertEqual(accepted, [(line.sent[0], None), (rtu(1, 6, 10, 500), plc.modbus_master)])
            plc.dataReceived.emit({"slave": 1, "fc": 3, "reg0": 0, "start": 0})
            self.assertEqual(plc.sent[-1], rtu(1, 6, 10, 500))
            self.assertIsNone(line.modbus_master._current, "a line link's master is never used")
            # Reads that only a Modbus link can answer go to those links only.
            read = modbus_request(1, 3, 0, 1)
            self.assertEqual(namespace["modbus_dispatch"](hub, read, 1000, "read", modbus_only=True),
                             [(rtu(1, 3, 0, 1), plc.modbus_master)])
            self.assertEqual(len(line.sent), 1)
        # A TCP server with no client has nobody to send to, so polling does not start on it.
        server = tcp_runtime.TcpHandler()
        self.addCleanup(server.deleteLater)
        self.addCleanup(server.disconnect)
        self.assertTrue(server.connect("127.0.0.1", 0, mode="服务端", parser_type="modbus_tcp"))
        self.assertTrue(server.is_connected)
        self.assertFalse(server.can_send)
        # Controls send through the hub this way, with a 1000 ms timeout.
        plc = self.link(vars(modbus_master))
        self.assertEqual(command_runtime.send_modbus_command(plc, 1, 6, 10, 500), [rtu(1, 6, 10, 500)])
        self.assertEqual(plc.modbus_master._timer.interval(), 1000)


if __name__ == "__main__":
    unittest.main()
