"""The Modbus poller of the preview and of exported applications: what the bindings and chart curves
read; the link cards set its parameters and show its status."""
import json
from pathlib import Path
import textwrap
import unittest

from tests import test_preview_export_parity as parity

ROOT = Path(__file__).resolve().parents[1]
TUTORIALS = ROOT / "examples" / "tutorials"

# The parity harness's preview runs no bindings; the poller still needs to know what they read, and
# the widgets of a project with containers are found by id. Time is the test's: poller._now.
SETUP = textwrap.indent(r'''
import struct
from PyQt5.QtGui import QColor
from serial_handler import create_parser, modbus_crc
export = os.environ["APPLICATION_MODE"] == "export"
if export:
    from data_binding import ModbusPoller
    def widget(name): return window.widgets[name]
else:
    from app.core.modbus_poller import ModbusPoller
    from app.core.data_binding import bindingEngine
    bindingEngine.load_bindings_from_project(project.widgets)
    def widget(name): return bindingEngine._widget_map[name]
poller, = window.findChildren(ModbusPoller)
clock = [0]
poller._now = lambda: clock[0]
def tick():
    poller._timer.timeout.emit()
def rtu(pdu):
    pdu = bytes.fromhex(pdu)
    return pdu + modbus_crc(pdu)
# The device: replies parsed the way the serial link parses them, on the reads it noted.
device = create_parser("modbus", {}, serial.modbus_requests)
def reply(pdu):
    for data in device.feed(rtu(pdu)):
        serial.dataReceived.emit(data)
def registers(*values):
    return "".join(value.hex() if isinstance(value, bytes) else f"{value:04x}" for value in values)
# The PLC tutorial's blocks, as the status tooltip lists them.
PLC_TIP = "\n".join((
    "从站 1 · 功能码 1 · 地址 0–3 · 周期 500 ms",
    "从站 1 · 功能码 3 · 地址 100–105 · 周期 500 ms",
    "从站 1 · 功能码 3 · 地址 200–201 · 周期 500 ms"))
''', " " * 12)  # as indented as the checks it follows


def tutorial_widgets(name):
    return json.loads((TUTORIALS / name).read_text(encoding="utf-8"))["widgets"]


def control(name, kind, properties, row=0):
    data = parity.control(name, kind, properties, row)
    data["geometry"].update(x=10, y=10 + row * 250, w=500, h=230)
    return data


def bound(name, binding, row):
    return parity.control(name, "NumericDisplay", {}, row) | {"binding": {"parseMode": "Modbus", **binding}}


class ModbusPollerTests(unittest.TestCase):
    run_both = parity.PreviewExportParityTests.run_both

    def test_polls_the_bindings_once_a_modbus_link_connects(self):
        # The PLC tutorial's TCP card is not connected: 500 ms, 1000 ms and slave 1 by default.
        widgets = tutorial_widgets("10-PLC恒压供水.uidp")
        self.run_both(widgets, SETUP + r"""
            assert (poller.default_period, poller.timeout, poller.default_slave) == (500, 1000, 1)
            assert poller.status() == "等待连接", poller.status()  # the serial link parses lines
            assert poller._timer.isActive() and poller._timer.interval() == 500  # it keeps looking
            serial.connected.emit("PLC")
            check_payloads([])
            serial.configure({"parser": "modbus"})
            serial.connected.emit("PLC")  # a Modbus link: polling starts at once
            coils, live, setpoint = rtu("010100000004"), rtu("010300640006"), rtu("010300c80002")
            assert poller.blocks() == [[1, 1, 0, 4, 500], [1, 3, 100, 6, 500], [1, 3, 200, 2, 500]], poller.blocks()
            assert (poller.status(), poller.tooltip()) == ("3 块 · 轮询中", PLC_TIP), poller.status()
            assert poller._timer.interval() == 500 and poller._timer.isActive()
            assert widget("plc_link")._status.text() == "未连接"  # its link is not the one polling
            check_payloads([coils])
            assert serial.modbus_master._timer.interval() == 1000
            tick()  # waiting for the reply
            check_payloads([coils])
            reply("01010101")  # 1 号泵运行
            check_payloads([coils, live])
            # A write while a read is on the wire waits for its reply, then goes ahead of the next read.
            click_switch("run")
            start = rtu("01050003ff00")
            check_payloads([coils, live])
            reply("01030c" + registers(struct.pack(">f", 0.42), struct.pack(">f", 36.5), 452, 76))
            check_payloads([coils, live, start])
            reply("01050003ff00")
            check_payloads([coils, live, start, setpoint])
            reply("010304" + registers(struct.pack(">f", 0.40)))
            assert poller.status() == "3 块 · 正常", poller.status()
            if export:
                for name, text in (("pressure", "0.42"), ("flow", "36.5"), ("target", "0.40")):
                    assert widgets[name]._value.text() == text, (name, widgets[name]._value.text())
                assert widgets["level"]._ring.value() == 76
                assert [widgets[name]._on for name in ("pump1", "pump2")] == [True, False]
            tick()  # nothing is due before 500 ms
            check_payloads([coils, live, start, setpoint])
            clock[0] = 500  # all three are due again, in plan order, one at a time
            tick()
            reply("01010101")
            check_payloads([coils, live, start, setpoint, coils, live])
            serial.disconnect()  # the read on the wire is cancelled; nothing to read with
            assert (poller.status(), poller.blocks()) == ("等待连接", []), poller.status()
        """)

    def test_the_first_link_card_whose_link_parses_modbus_sets_period_timeout_and_slave(self):
        self.run_both([
            # First in the document, but its link is not connected: its settings do not count.
            control("tcp", "TcpConfigCard", {"defaultParser": "modbus_tcp", "modbusPeriod": 100,
                                             "modbusTimeout": 50, "modbusSlave": 9}),
            control("bus", "SerialConfigCard", {"defaultParser": "modbus", "modbusPeriod": 300,
                                                "modbusTimeout": 60000, "modbusSlave": 7}, 1),
            # The same serial link parses Modbus for this card too, but it comes later.
            control("spare", "SerialConfigCard", {"modbusPeriod": 200, "modbusTimeout": 40,
                                                  "modbusSlave": 8}, 2),
            bound("value", {"mbArea": "保持寄存器", "mbRegIndex": 0}, 10),
            bound("other", {"mbRegIndex": 10, "mbSlaveFilter": 2, "mbPeriod": 1000}, 11),
        ], SETUP + r"""
            tcp, bus, spare = widgets["tcp"], widgets["bus"], widgets["spare"]
            # No link parses Modbus yet: the built-in defaults.
            assert (poller.default_period, poller.timeout, poller.default_slave) == (500, 1000, 1)
            assert [card.modbus_settings for card in (tcp, bus, spare)] == [
                (100, 50, 9), (300, 60000, 7), (200, 40, 8)]
            serial.configure({"parser": "modbus"})
            serial.connected.emit("PLC")
            assert (poller.default_period, poller.timeout, poller.default_slave) == (300, 60000, 7)
            other, value = rtu("0203000a0001"), rtu("070300000001")
            assert poller.blocks() == [[2, 3, 10, 1, 1000], [7, 3, 0, 1, 300]], poller.blocks()
            assert poller._timer.interval() == 300  # the period
            check_payloads([other])  # one read for both serial cards
            assert serial.modbus_master._timer.interval() == 60000  # the timeout
            for card in (bus, spare):
                assert card._status.text() == "● 已连接 · 2 块 · 轮询中", card._status.text()
            assert tcp._status.text() == "未连接", tcp._status.text()
            reply("0203020001")
            reply("0703020002")
            check_payloads([other, value])
            # The second card's settings do not count; the first card's count at once.
            spare.set_modbus_period(50)
            assert poller.default_period == 300
            bus.set_modbus_period(100)  # a block of another period is a new block: read now
            assert poller.default_period == 100 and poller._timer.interval() == 100
            check_payloads([other, value, value])
            assert bus._status.text() == "● 已连接 · 2 块 · 轮询中", bus._status.text()
            reply("0703020002")
            bus.set_modbus_slave(8)  # the slave of the bindings that filter none
            assert poller.default_slave == 8
            check_payloads([other, value, value, rtu("080300000001")])
            bus.set_modbus_timeout(2000)  # from the next read on
            reply("0803020003")
            clock[0] = 1000
            tick()
            check_payloads([other, value, value, rtu("080300000001"), rtu("080300000001")])
            assert serial.modbus_master._timer.interval() == 2000
            reply("0803020003")
            # No link card's link parses Modbus any more: the defaults again.
            serial.disconnect()
            assert (poller.default_period, poller.timeout, poller.default_slave) == (500, 1000, 1)
            assert bus._status.text() == spare._status.text() == "未连接", bus._status.text()
        """)

    def test_a_connected_link_card_shows_the_status_and_the_blocks(self):
        # The PLC tutorial with a serial card added: the TCP card comes first, but only the serial link
        # connects, so the serial card's settings count and it shows what the poller reads.
        widgets = tutorial_widgets("10-PLC恒压供水.uidp") + [
            control("serial_link", "SerialConfigCard", {"modbusTimeout": 60000}, 3)]
        self.run_both(widgets, SETUP + r"""
            card, tcp = widget("serial_link"), widget("plc_link")
            ok = QColor("#237b27")  # the colour of 已连接, whatever the blocks do
            assert (card._status.text(), card._status.toolTip()) == ("未连接", "")
            serial.connected.emit("PLC")  # the serial link parses lines: the connection only
            assert (card._status.text(), card._status.toolTip()) == ("● 已连接", ""), card._status.text()
            serial.configure({"parser": "modbus"})
            serial.connected.emit("PLC")
            coils, live, setpoint = rtu("010100000004"), rtu("010300640006"), rtu("010300c80002")
            assert (card._status.text(), card._status.toolTip()) == ("● 已连接 · 3 块 · 轮询中", PLC_TIP), \
                card._status.text()
            assert tcp._status.text() == "未连接", tcp._status.text()
            reply("01010101")
            reply("01030c" + registers(0, 0, 0, 0, 0, 0))
            reply("010304" + registers(0, 0))
            assert (card._status.text(), card._status.toolTip()) == ("● 已连接 · 3 块 · 正常", PLC_TIP), \
                card._status.text()
            clock[0] = 500
            tick()
            reply("01010101")
            reply("018302")  # the live block's addresses are refused
            serial.modbus_master._timer.timeout.emit()  # and the setpoints do not come
            check_payloads([coils, live, setpoint] * 2)
            assert card._status.text() == "● 已连接 · 第 2 块异常 02 非法数据地址", card._status.text()
            assert card._status.lightColor == ok, card._status.lightColor.name()
            clock[0] = 1000
            tick()
            reply("01010101")
            reply("01030c" + registers(0, 0, 0, 0, 0, 0))
            serial.modbus_master._timer.timeout.emit()
            failed = "● 已连接 · 第 3 块无响应（从站 1 功能码 3 地址 200）"
            assert (card._status.text(), card._status.toolTip()) == (failed, PLC_TIP), card._status.text()
            assert card._status.lightColor == ok, card._status.lightColor.name()
            # 单行 has no status line, only the connection: nothing of the poller's shows there.
            card.set_display_mode("单行")
            assert (card._sl_status.text(), card._sl_status.toolTip()) == ("● 已连接", ""), card._sl_status.text()
            card.set_display_mode("完整")
            for name in ("pressure", "flow", "target", "frequency", "level", "pump1", "pump2", "fault", "run"):
                widget(name).hide()
            widget("trend").configure([])  # the chart's curves read 100–101 and 200–201
            tick()
            nothing = "● 已连接 · 没有 Modbus 绑定"
            assert (card._status.text(), card._status.toolTip()) == (nothing, nothing), card._status.text()
            serial.disconnect()
            assert (card._status.text(), card._status.toolTip()) == ("未连接", ""), card._status.text()
            assert poller.status() == "等待连接", poller.status()
        """)

    def test_fast_blocks_are_read_more_often_and_hidden_tab_pages_not_at_all(self):
        self.run_both([
            control("bus", "SerialConfigCard", {"modbusPeriod": 300, "modbusTimeout": 60000}),
            bound("fast", {"mbRegIndex": 0, "mbPeriod": 100}, 5),
            parity.control("tabs", "TabWidget", {"tabNames": "趋势\n说明"}, 6) | {"children": [
                bound("slow", {"mbRegIndex": 50}, 0),
                parity.control("note", "Label", {"text": "说明"}) | {"tabIndex": 1}]},
        ], SETUP + r"""
            bus = widgets["bus"]
            fast, slow = rtu("010300000001"), rtu("010300320001")
            def answer():
                while serial.modbus_master.busy():
                    reply("0103020007")
            serial.configure({"parser": "modbus"})
            serial.connected.emit("PLC")
            assert bus._status.text() == "● 已连接 · 2 块 · 轮询中", bus._status.text()
            assert poller._timer.interval() == 100, poller._timer.interval()  # the fastest block
            check_payloads([fast])
            answer()
            assert bus._status.text() == "● 已连接 · 2 块 · 正常", bus._status.text()
            for clock[0] in range(100, 700, 100):
                tick()
                answer()
            assert (port.writes.count(fast), port.writes.count(slow)) == (7, 3), port.writes
            # On the other tab page the slow reading is out of sight, and no longer read.
            widget("tabs").setCurrentIndex(1)
            app.processEvents()
            for clock[0] in range(700, 1300, 100):
                tick()
                answer()
            assert bus._status.text() == "● 已连接 · 1 块 · 正常", bus._status.text()
            assert (port.writes.count(fast), port.writes.count(slow)) == (13, 3), port.writes
            widget("tabs").setCurrentIndex(0)
            app.processEvents()
            tick()  # back in sight: a new plan, whose new block is read at once
            answer()
            assert (port.writes.count(fast), port.writes.count(slow)) == (13, 4), port.writes
            assert bus._status.text() == "● 已连接 · 2 块 · 轮询中", bus._status.text()
        """)

    def test_a_block_no_link_can_send_counts_as_no_reply_and_polling_goes_on(self):
        self.run_both([
            control("bus", "SerialConfigCard", {"modbusTimeout": 60000}),
            bound("low", {"mbRegIndex": 0}, 5),
            bound("high", {"mbRegIndex": 50}, 6),
        ], SETUP + r"""
            bus = widgets["bus"]
            failures = []
            serial.error.connect(failures.append)
            write = port.write
            def unplugged(payload):
                port.write = write  # once
                raise OSError("device unplugged during write")
            port.write = unplugged
            serial.configure({"parser": "modbus"})
            serial.connected.emit("PLC")
            assert len(failures) == 1, failures
            check_payloads([rtu("010300320001")])  # the next block goes out at once
            reply("0103020007")
            assert bus._status.text() == "● 已连接 · 第 1 块无响应（从站 1 功能码 3 地址 0）", bus._status.text()
            assert poller._timer.isActive() and poller.blocks()
            clock[0] = 500
            tick()
            reply("0103020007")
            reply("0103020007")
            check_payloads([rtu("010300320001"), rtu("010300000001"), rtu("010300320001")])
            assert bus._status.text() == "● 已连接 · 2 块 · 正常", bus._status.text()
        """)

    def test_tutorial_projects_plan_their_blocks(self):
        # Their link cards set no period of their own: the default, 500 ms. 02: the four bindings read holding
        # registers 0–3; the chart's two curves name no register table, so they read holding registers
        # too: the measured float32 at 4–5 and the setpoint at 1.
        for name, expected, bindings_only in (
                ("02-温控仪监控.uidp", [[1, 3, 0, 6, 500]], [[1, 3, 0, 4, 500]]),
                ("10-PLC恒压供水.uidp", [[1, 1, 0, 4, 500], [1, 3, 100, 6, 500], [1, 3, 200, 2, 500]],
                 [[1, 1, 0, 4, 500], [1, 3, 100, 6, 500], [1, 3, 200, 2, 500]])):
            with self.subTest(project=name):
                widgets = tutorial_widgets(name)
                self.run_both(widgets, SETUP + f'''
            from serial_handler import plan_blocks
            serial.configure({{"parser": "modbus"}})
            serial.connected.emit("COM")
            assert poller.blocks() == {expected!r}, poller.blocks()
            charts = {{widget_id for widget_id, *_need in poller._needs()
                       if hasattr(widget(widget_id), "modbus_needs")}}
            needs = [dict(zip(("slave", "table", "address", "count", "period"), need))
                     for widget_id, *need, _visible in poller._needs() if widget_id not in charts]
            for need in needs:
                need["slave"] = need["slave"] if need["slave"] > 0 else poller.default_slave
            assert plan_blocks(needs, poller.default_period) == {bindings_only!r}
            check_payloads([rtu("{"%02x%02x%04x%04x" % tuple(expected[0][:4])}")])
                ''')


if __name__ == "__main__":
    unittest.main()
