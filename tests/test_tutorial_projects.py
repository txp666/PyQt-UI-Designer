"""The video tutorials' example projects keep loading and exporting as the designer changes."""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from app.core.code_generator import generate_project
from app.core.project import ProjectData
from app.widgets.basic import register_basic_widgets
from app.widgets.chart import register_chart_widgets
from app.widgets.comm import register_comm_widgets
from app.widgets.composite import register_composite_widgets
from app.widgets.display import register_display_widgets
from app.widgets.layout import register_layout_widgets


TUTORIALS = Path(__file__).resolve().parents[1] / "examples" / "tutorials"


class TutorialProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for register in (
            register_basic_widgets, register_chart_widgets, register_comm_widgets,
            register_composite_widgets, register_display_widgets, register_layout_widgets,
        ):
            register()

    def test_every_tutorial_project_loads_and_exports(self):
        projects = sorted(TUTORIALS.glob("*.uidp"))
        self.assertTrue(projects)
        for source in projects:
            with self.subTest(project=source.name):
                project = ProjectData.from_dict(json.loads(source.read_text(encoding="utf-8")))
                project.file_path = str(source)
                with tempfile.TemporaryDirectory() as folder:
                    generate_project(project, folder, theme_mode="Auto")
                    generated = sorted(Path(folder).glob("*.py"))
                    self.assertIn("main.py", [path.name for path in generated])
                    for path in generated:
                        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_plc_example_polls_writes_and_binds_by_register_address(self):
        from tests import test_preview_export_parity as parity
        source = TUTORIALS / "10-PLC恒压供水.uidp"
        widgets = json.loads(source.read_text(encoding="utf-8"))["widgets"]
        parity.PreviewExportParityTests.run_both(self, widgets, r'''
            import struct
            import time
            from PyQt5.QtNetwork import QHostAddress, QTcpServer
            def wait_for(predicate, what):
                deadline = time.monotonic() + 8
                while not predicate() and time.monotonic() < deadline:
                    QTest.qWait(10)
                assert predicate(), f"Timed out waiting for {what}"

            class Plc:
                """A Modbus TCP PLC with the register map in examples/tutorials/README.md."""
                def __init__(self):
                    self.hr, self.coils, self.requests, self.buffer = {}, {0: 1, 1: 0, 2: 0, 3: 0}, [], b""
                    self.set_float(100, 0.42); self.set_float(102, 36.5); self.set_float(200, 0.40)
                    self.hr[104], self.hr[105] = 452, 76
                    self.peer = None
                    self.server = QTcpServer()
                    assert self.server.listen(QHostAddress(QHostAddress.LocalHost), 0)
                    self.server.newConnection.connect(self.accept)
                def set_float(self, address, value):
                    self.hr[address], self.hr[address + 1] = struct.unpack(">HH", struct.pack(">f", value))
                def float_at(self, address):
                    return struct.unpack(">f", struct.pack(">HH", self.hr[address], self.hr[address + 1]))[0]
                def accept(self):
                    self.peer = self.server.nextPendingConnection()
                    self.peer.readyRead.connect(self.read)
                def read(self):
                    self.buffer += bytes(self.peer.readAll())
                    while len(self.buffer) >= 6 and len(self.buffer) >= 6 + int.from_bytes(self.buffer[4:6], "big"):
                        size = 6 + int.from_bytes(self.buffer[4:6], "big")
                        adu, self.buffer = self.buffer[:size], self.buffer[size:]
                        self.peer.write(self.answer(adu))
                def answer(self, adu):
                    unit, fc = adu[6], adu[7]
                    address, count = struct.unpack(">HH", adu[8:12])
                    self.requests.append((fc, address, count))
                    if fc == 3:
                        pdu = bytes([3, 2 * count]) + b"".join(
                            self.hr.get(address + i, 0).to_bytes(2, "big") for i in range(count))
                    elif fc == 1:
                        bits = sum(self.coils.get(address + i, 0) << i for i in range(count))
                        pdu = bytes([1, (count + 7) // 8]) + bits.to_bytes((count + 7) // 8, "little")
                    elif fc == 5:
                        self.coils[address] = int(adu[10:12] == b"\xff\x00")
                        pdu = adu[7:12]
                    elif fc == 16:
                        for i in range(count):
                            self.hr[address + i] = int.from_bytes(adu[13 + 2 * i:15 + 2 * i], "big")
                        pdu = adu[7:12]
                    else:
                        pdu = bytes([fc | 0x80, 1])
                    return adu[:2] + b"\0\0" + (len(pdu) + 1).to_bytes(2, "big") + bytes([unit]) + pdu

            export = os.environ["APPLICATION_MODE"] == "export"
            if export:
                from data_binding import ModbusPoller
            else:  # the preview harness runs no bindings; the poller reads what they show
                from app.core.modbus_poller import ModbusPoller
                from app.core.data_binding import bindingEngine
                bindingEngine.load_bindings_from_project(project.widgets)
            poller, = window.findChildren(ModbusPoller)
            plc = Plc()
            link = widgets["plc_link"]
            link._port_spin.setValue(plc.server.serverPort())
            QTest.mouseClick(link._connect_btn, Qt.LeftButton)  # no Modbus card: polling starts once connected
            wait_for(lambda: poller.status() == "3 块 · 正常", "a full poll round")
            assert plc.requests[:3] == [(1, 0, 4), (3, 100, 6), (3, 200, 2)], plc.requests
            if export:
                for name, text in (("pressure", "0.42"), ("flow", "36.5"), ("target", "0.40")):
                    assert widgets[name]._value.text() == text, (name, widgets[name]._value.text())
                assert abs(widgets["frequency"]._value - 45.2) < 1e-6, widgets["frequency"]._value
                assert widgets["level"]._ring.value() == 76
                assert [widgets[name]._on for name in ("pump1", "pump2", "fault")] == [True, False, False]
                assert not widgets["run"]._switch.isChecked()

            setpoint = widgets["setpoint"]
            setpoint.setText("0.45")
            QTest.keyClick(setpoint, Qt.Key_Return)
            wait_for(lambda: (16, 200, 2) in plc.requests, "the FC16 setpoint write")
            assert abs(plc.float_at(200) - 0.45) < 1e-6, plc.float_at(200)
            QTest.mouseClick(widgets["run"]._switch.indicator, Qt.LeftButton)
            wait_for(lambda: plc.coils[3] == 1, "the FC05 start command")
            if export:
                wait_for(lambda: widgets["target"]._value.text() == "0.45", "the new setpoint read back")
                wait_for(lambda: widgets["run"]._switch.isChecked(), "the start coil read back")
            QTest.mouseClick(link._connect_btn, Qt.LeftButton)  # 断开
            assert poller.status() == "等待连接", poller.status()
        ''')
