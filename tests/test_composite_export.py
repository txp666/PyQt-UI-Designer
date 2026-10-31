"""Exercise configured cards and containers in preview and standalone applications."""
import copy
import json
from pathlib import Path
import sys
import textwrap
import unittest

from tests import test_preview_export_parity as parity

ROOT = Path(__file__).resolve().parents[1]
PLC_EXAMPLE = ROOT / "examples" / "tutorials" / "10-PLC恒压供水.uidp"

# The parity harness's preview runs no bindings; the Modbus card's 自动 polling still needs to know
# what they read, and the widgets of a project with containers are found by id.
_AUTO_SETUP = textwrap.indent(r'''
import struct
from serial_handler import create_parser, modbus_crc
export = os.environ["APPLICATION_MODE"] == "export"
if export:
    def widget(name): return window.widgets[name]
else:
    from app.core.data_binding import bindingEngine
    bindingEngine.load_bindings_from_project(project.widgets)
    def widget(name): return bindingEngine._widget_map[name]
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
clock = [0]
''', " " * 12)  # as indented as the checks it precedes


def control(name, kind, properties, row=0):
    data = parity.control(name, kind, properties, row)
    data["geometry"].update(x=10, y=10 + row * 250, w=500, h=230)
    return data


class CompositeExportTests(unittest.TestCase):
    run_both = parity.PreviewExportParityTests.run_both

    def test_modbus_card_preserves_configuration_and_real_send_and_poll_controls(self):
        self.run_both([control("bus", "ModbusConfigCard", {
            "title": "压力控制总线", "defaultSlave": 7,
            "defaultFunc": "06 写单寄存器", "defaultAddr": 32,
            "defaultValue": 125, "defaultPoll": 250,
        })], r'''
            from PyQt5.QtWidgets import QLabel
            bus = widgets["bus"]
            assert "压力控制总线" in [label.text() for label in bus.findChildren(QLabel)]
            assert not bus._poll_timer.isActive()
            assert bus._poll_edit.text() == "250"
            QTest.mouseClick(bus._send_btn, Qt.LeftButton)
            frame = bytes.fromhex("07060020007d4847")
            check_payloads([frame])
            # The first request goes out at once. No link parses Modbus here, so no reply can be
            # recognised: every tick sends again without waiting.
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            assert bus._poll_timer.isActive()
            assert bus._poll_timer.interval() == 250
            assert not bus._send_btn.isEnabled()
            check_payloads([frame, frame])
            bus._poll_timer.timeout.emit()
            check_payloads([frame] * 3)
            assert bus._status.text().startswith("已发送: 07 06"), bus._status.text()
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            assert not bus._poll_timer.isActive()
            assert bus._send_btn.isEnabled()
            # Malformed text must not turn into a write to address zero.
            address = getattr(bus, "_addr_edit", None) or bus._addr
            address.setText("not-an-address")
            QTest.mouseClick(bus._send_btn, Qt.LeftButton)
            check_payloads([frame] * 3)
            assert "整数" in bus._status.text()
            address.setText("32")
            bus._poll_edit.setText("9999999999999999")
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            assert not bus._poll_timer.isActive()
            assert "60000" in bus._status.text()
            QTest.mouseClick(bus._send_btn, Qt.LeftButton)
            check_payloads([frame] * 4)
        ''')

    def test_modbus_card_polls_its_table_one_reply_at_a_time(self):
        self.run_both([
            control("bus", "ModbusConfigCard", {
                # The longest timeout: the test fires the reply timer itself.
                "defaultPoll": 60000, "timeout": 60000, "pollList": "1,3,100,2\n# 线圈\n1，1，0，3",
            }),
            parity.control("value", "NumericDisplay", {"title": "设定"}, 16) | {"binding": {
                "parseMode": "Modbus", "mbArea": "保持寄存器", "mbRegIndex": 101}},
        ], r'''
            from serial_handler import create_parser, modbus_crc
            def rtu(pdu):
                pdu = bytes.fromhex(pdu)
                return pdu + modbus_crc(pdu)
            # The device: replies parsed the way the serial link parses them, on the reads it noted.
            serial.configure({"parser": "modbus"})
            device = create_parser("modbus", {}, serial.modbus_requests)
            def reply(pdu):
                for data in device.feed(rtu(pdu)):
                    serial.dataReceived.emit(data)
            bus = widgets["bus"]
            registers, coils = rtu("010300640002"), rtu("010100000003")
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)  # the first round starts at once
            assert bus._status.text() == "轮询中 · 2 条", bus._status.text()
            check_payloads([registers])
            bus._poll_timer.timeout.emit()  # waiting for the first reply: no new round
            check_payloads([registers])
            reply("01030441ca6666")  # the next read goes out only after this reply
            check_payloads([registers, coils])
            bus._poll_timer.timeout.emit()  # still waiting for the coils: no new round
            check_payloads([registers, coils])
            reply("01010201ff")  # two bytes of coils for a read of three: it answers some other read
            check_payloads([registers, coils])
            assert bus._status.text() == "轮询中 · 2 条", bus._status.text()
            reply("018102")
            assert bus._status.text() == "第 2 条异常 02 非法数据地址 · 1/2", bus._status.text()
            assert bus._status.toolTip() == bus._status.text()
            if os.environ["APPLICATION_MODE"] == "export":  # the preview harness runs no bindings
                assert widgets["value"]._value.text() == "26214", widgets["value"]._value.text()

            bus._poll_timer.timeout.emit()
            check_payloads([registers, coils, registers])
            serial.modbus_master._timer.timeout.emit()  # no reply in time: the round moves on to the coils
            check_payloads([registers, coils, registers, coils])
            reply("01010105")
            assert bus._status.text() == "第 1 条无响应 · 1/2", bus._status.text()
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            assert not bus._poll_timer.isActive() and bus._send_btn.isEnabled()

            # A manual request reports its reply too.
            QTest.mouseClick(bus._send_btn, Qt.LeftButton)
            reply("010302002a")
            assert bus._status.text() == "设备已响应", bus._status.text()
            QTest.mouseClick(bus._send_btn, Qt.LeftButton)
            assert serial.modbus_master.busy()
            serial.modbus_master._timer.timeout.emit()
            assert bus._status.text() == "无响应（60000 ms 超时）", bus._status.text()
            bus.set_poll_list("1,6,0,1")
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            assert not bus._poll_timer.isActive()
            assert bus._status.text() == "轮询表第 1 条应为 从站,功能码(1–4),地址,数量", bus._status.text()
            bus.set_poll_list("1,3,0,126")  # well formed, but one register too many: say so
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            assert not bus._poll_timer.isActive()
            assert bus._status.text() == "轮询表第 1 条：Modbus 值或读取数量超出功能码允许范围", bus._status.text()
        ''')

    def test_modbus_card_polls_automatically_what_the_bindings_show(self):
        # The bindings of the PLC tutorial, polled by a card with no poll table.
        widgets = json.loads(PLC_EXAMPLE.read_text(encoding="utf-8"))["widgets"]
        poller = next(item for item in widgets if item["id"] == "poller")
        poller["properties"] = {"title": "自动轮询", "pollMode": "自动", "defaultPoll": 500, "timeout": 60000}
        self.run_both(widgets, _AUTO_SETUP + r'''
            bus = widgets["poller"]
            assert bus._mode_hint.text() == "轮询方式：自动", bus._mode_hint.text()
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)  # the serial link parses lines: nothing to read with
            assert bus._status.text() == "自动 · 等待连接", bus._status.text()
            check_payloads([])
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            serial.configure({"parser": "modbus"})
            bus._now = lambda: clock[0]
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            coils, live, setpoint = rtu("010100000004"), rtu("010300640006"), rtu("010300c80002")
            assert bus._status.text() == "自动 · 3 块 · 轮询中", bus._status.text()
            assert bus._status.toolTip() == "\n".join((
                "从站 1 · 功能码 1 · 地址 0–3 · 周期 500 ms",
                "从站 1 · 功能码 3 · 地址 100–105 · 周期 500 ms",
                "从站 1 · 功能码 3 · 地址 200–201 · 周期 500 ms")), bus._status.toolTip()
            assert bus._poll_timer.interval() == 500 and not bus._send_btn.isEnabled()
            check_payloads([coils])
            bus._poll_timer.timeout.emit()  # waiting for the reply
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
            assert bus._status.text() == "自动 · 3 块 · 正常", bus._status.text()
            if export:
                for name, text in (("pressure", "0.42"), ("flow", "36.5"), ("target", "0.40")):
                    assert widgets[name]._value.text() == text, (name, widgets[name]._value.text())
                assert widgets["level"]._ring.value() == 76
                assert [widgets[name]._on for name in ("pump1", "pump2")] == [True, False]
            bus._poll_timer.timeout.emit()  # nothing is due before 500 ms
            check_payloads([coils, live, start, setpoint])

            clock[0] = 500  # all three are due again, in plan order
            bus._poll_timer.timeout.emit()
            reply("01010101")
            reply("018302")  # the live block's addresses are refused
            serial.modbus_master._timer.timeout.emit()  # and the setpoints do not come
            check_payloads([coils, live, start, setpoint] + [coils, live, setpoint])
            assert bus._status.text() == "自动 · 第 2 块异常 02 非法数据地址", bus._status.text()
            clock[0] = 1000
            bus._poll_timer.timeout.emit()
            reply("01010101")
            reply("01030c" + registers(0, 0, 0, 0, 0, 0))
            serial.modbus_master._timer.timeout.emit()
            assert bus._status.text() == "自动 · 第 3 块无响应（从站 1 功能码 3 地址 200）", bus._status.text()
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            assert not bus._poll_timer.isActive() and bus._send_btn.isEnabled()
        ''')

    def test_modbus_card_reads_fast_blocks_more_often_starts_on_connect_and_skips_hidden_tabs(self):
        self.run_both([
            control("bus", "ModbusConfigCard", {"pollMode": "自动", "defaultPoll": 300, "timeout": 60000}),
            parity.control("fast", "NumericDisplay", {}, 5) | {"binding": {
                "parseMode": "Modbus", "mbArea": "保持寄存器", "mbRegIndex": 0, "mbPeriod": 100}},
            parity.control("tabs", "TabWidget", {"tabNames": "趋势\n说明"}, 6) | {"children": [
                parity.control("slow", "NumericDisplay", {}) | {"binding": {
                    "parseMode": "Modbus", "mbArea": "保持寄存器", "mbRegIndex": 50}},
                parity.control("note", "Label", {"text": "说明"}) | {"tabIndex": 1}]},
        ], _AUTO_SETUP + r'''
            bus = widgets["bus"]
            fast, slow = rtu("010300000001"), rtu("010300320001")
            def answer():
                while serial.modbus_master.busy():
                    reply("0103020007")
            bus._now = lambda: clock[0]
            serial.configure({"parser": "modbus"})
            serial.connected.emit("PLC")  # autoStart: polling starts as a Modbus link connects
            assert bus._polling and bus._status.text() == "自动 · 2 块 · 轮询中", bus._status.text()
            assert bus._poll_timer.interval() == 100, bus._poll_timer.interval()  # the fastest block
            check_payloads([fast])
            answer()
            assert bus._status.text() == "自动 · 2 块 · 正常", bus._status.text()
            for clock[0] in range(100, 700, 100):
                bus._poll_timer.timeout.emit()
                answer()
            assert (port.writes.count(fast), port.writes.count(slow)) == (7, 3), port.writes
            # On the other tab page the slow reading is out of sight, and no longer read.
            widget("tabs").setCurrentIndex(1)
            app.processEvents()
            for clock[0] in range(700, 1300, 100):
                bus._poll_timer.timeout.emit()
                answer()
            assert bus._status.text() == "自动 · 1 块 · 正常", bus._status.text()
            assert (port.writes.count(fast), port.writes.count(slow)) == (13, 3), port.writes
            widget("fast").hide()
            bus._poll_timer.timeout.emit()
            assert bus._status.text() == "自动 · 没有 Modbus 绑定", bus._status.text()
            serial.disconnect()
            assert not bus._polling and bus._status.text() == "未连接", bus._status.text()
        ''')

    def test_projects_from_before_automatic_polling_keep_their_poll_table(self):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            import check_uidp
        finally:
            sys.path.remove(str(ROOT / "tools"))
        from app.core.project import ProjectData
        document = json.loads(PLC_EXAMPLE.read_text(encoding="utf-8"))
        original = copy.deepcopy(document)
        self.assertEqual(check_uidp.problems(document), [])
        cards = {item["id"]: item for item in ProjectData.from_dict(document).widgets}
        self.assertEqual({key: cards["poller"]["properties"][key] for key in ("pollMode", "autoStart")},
                         {"pollMode": "轮询表", "autoStart": False})
        self.assertEqual(document, original, "loading leaves the document as it was read")
        # Any card saved without a pollMode, with or without a table, waits for 轮询 as it did.
        for properties, expected in (({"defaultPoll": 500}, {"pollMode": "轮询表", "autoStart": False}),
                                     ({"pollMode": "自动"}, {"pollMode": "自动"})):
            loaded = ProjectData.from_dict({"widgets": [
                {"type": "ModbusConfigCard", "id": "bus", "properties": properties}]})
            self.assertEqual({key: value for key, value in loaded.widgets[0]["properties"].items()
                              if key in ("pollMode", "autoStart")}, expected)

    def test_send_card_preserves_title_placeholder_and_all_newline_choices(self):
        self.run_both([control("send", "DataSendCard", {
            "title": "手动命令", "placeholder": "输入采样指令",
        })], r'''
            from PyQt5.QtWidgets import QLabel
            send = widgets["send"]
            assert "手动命令" in [label.text() for label in send.findChildren(QLabel)]
            assert send._input.placeholderText() == "输入采样指令"
            assert send._newline_combo.currentText() == "\\r\\n"
            expected = []
            for choice, ending in (("无", b""), ("\\r\\n", b"\r\n"),
                                   ("\\n", b"\n"), ("\\r", b"\r")):
                send._newline_combo.setCurrentIndex(send._newline_combo.findText(choice))
                send._input.setText("READ")
                QTest.keyClick(send._input, Qt.Key_Return)
                expected.append(b"READ" + ending)
                check_payloads(expected)
            hex_toggle = getattr(send, "_hex_check", None) or send._hex_cb
            hex_toggle.setChecked(True)
            send._input.setText("ABC")
            QTest.mouseClick(send._send_btn, Qt.LeftButton)
            expected.append(bytes.fromhex("0abc"))
            check_payloads(expected)
        ''')

    def test_table_restores_columns_receives_samples_and_bounds_history(self):
        self.run_both([control("table", "DataTable", {
            "columns": "参数\n当前值\n单位", "maxRows": 10,
        })], r'''
            table = widgets["table"]
            view = table._table
            assert [view.horizontalHeaderItem(i).text() for i in range(view.columnCount())] == ["参数", "当前值", "单位"]
            serial.dataReceived.emit({"温度": 24.5, "状态": "<ready>&ok"})
            assert view.rowCount() == 2
            assert view.item(0, 0).text() == "温度"
            assert view.item(0, 1).text() == "24.5"
            assert view.item(1, 1).text() == "<ready>&ok"
            serial.dataReceived.emit({f"v{i}": i for i in range(25)})
            assert view.rowCount() == 10
            assert view.item(9, 0).text() == "v9"
            serial.dataReceived.emit({"new": 42})
            assert view.rowCount() == 1
            assert view.item(0, 0).text() == "new"
            table.clear_data()
            for i in range(15): table.append_row([i, i * 2, "kPa"])
            assert view.rowCount() == 10
            assert view.item(0, 0).text() == "5"
            assert view.item(9, 2).text() == "kPa"
            table.set_columns([])
            assert view.columnCount() == 2
            table.set_columns(["字段"])
            serial.dataReceived.emit({"one": 1})
            assert view.columnCount() == 1 and view.rowCount() == 1
            assert view.item(0, 0).text() == "one"
            check_payloads([])
        ''')

    def test_receive_and_log_cards_render_original_text_and_bound_all_event_types(self):
        self.run_both([
            control("recv", "DataRecvCard", {"title": "原始收发", "maxLines": 50}),
            control("log", "LogBox", {"maxLines": 50}, 1),
        ], r'''
            from PyQt5.QtWidgets import QLabel
            recv, log = widgets["recv"], widgets["log"]
            output = getattr(recv, "_output", None) or recv._text
            log_output = getattr(log, "_output", None) or log._text
            assert "原始收发" in [label.text() for label in recv.findChildren(QLabel)]
            assert recv._max_lines == log._max_lines == 50
            payload = '<state value="ON">设备 & ready</state>'
            serial.rawReceived.emit(payload.encode())
            serial.dataSent.emit(payload.encode())
            serial.dataReceived.emit({"status": payload})
            assert output.toPlainText().count(payload) == 2, output.toPlainText()
            assert payload in log_output.toPlainText(), log_output.toPlainText()
            serial.connected.emit("<COM&7>")
            serial.error.emit("<failed>&connection")
            assert "<COM&7>" in output.toPlainText()
            assert "<COM&7>" in log_output.toPlainText()
            assert "<failed>&connection" in log_output.toPlainText()
            for index in range(70):
                serial.connected.emit(f"connection-{index}")
                assert output.document().blockCount() <= 50
                assert log_output.document().blockCount() <= 50
            assert "connection-69" in output.toPlainText()
            assert "connection-0 " not in output.toPlainText()
            for index in range(70):
                serial.rawReceived.emit(f"sample-{index}\nsecond-{index}".encode())
                serial.dataReceived.emit({"sample": index})
                assert output.document().blockCount() <= 50
                assert log_output.document().blockCount() <= 50
            assert "sample-69\nsecond-69" in output.toPlainText()
            assert "sample=69" in log_output.toPlainText()
            recv._clear_btn.click()
            log.clear_log()
            assert output.toPlainText() == log_output.toPlainText() == ""
            assert recv._counter.text() == "0 条"
        ''')

    def test_container_titles_survive_export_and_theme_changes(self):
        self.run_both([control(kind, kind, {"title": f"配置-{kind}"}, index)
                       for index, kind in enumerate(("HBoxLayout", "VBoxLayout", "FlexLayout", "CardContainer"))], r'''
            from PyQt5.QtGui import QImage, QPainter
            from qfluentwidgets import Theme, setTheme
            painted = []
            class RecordingPainter(QPainter):
                def drawText(self, *args):
                    painted.append((args[-1], self.pen().color().name()))
                    return super().drawText(*args)
            def render_title(widget):
                painted.clear()
                image = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
                image.fill(Qt.transparent)
                # Render the real paintEvent and forward every call to Qt. The
                # Windows offscreen font backend does not guarantee glyph pixels.
                with patch.object(sys.modules[type(widget).__module__],
                                  "QPainter", RecordingPainter):
                    widget.render(image)
                return list(painted)
            for theme in (Theme.DARK, Theme.LIGHT):
                setTheme(theme)
                app.processEvents()
                color = "#b3b3b3" if theme == Theme.DARK else "#606060"
                for kind, widget in widgets.items():
                    title = f"配置-{kind}"
                    assert widget._title == title
                    assert (title, color) in render_title(widget), (kind, painted)
                    widget.set_title("")
                    assert not any(text for text, _ in render_title(widget)), (kind, painted)
                    widget.set_title(title)
            check_payloads([])
        ''')

    def test_ring_percentage_and_separator_orientation_match_preview(self):
        self.run_both([
            control("ring", "ProgressRingDisplay", {"maximum": 200, "value": 50}),
            control("horizontal", "Separator", {"orientation": "horizontal"}, 1),
            control("vertical", "Separator", {"orientation": "vertical"}, 2),
        ], r'''
            ring = widgets["ring"]._ring
            assert ring.isTextVisible()
            assert ring.text() == "25%", ring.text()
            widgets["ring"].set_value(80)
            assert ring.text() == "40%", ring.text()
            assert widgets["horizontal"].width() == 500
            assert widgets["horizontal"].height() == 2
            assert widgets["vertical"].width() == 2
            assert widgets["vertical"].height() == 230
            if os.environ["APPLICATION_MODE"] == "preview":
                from app.widgets.layout import apply_layout_property
                line = widgets["vertical"]
                apply_layout_property(line, "Separator", "orientation", "horizontal")
                line.resize(300, 40)
                assert (line.width(), line.height()) == (300, 2)
                apply_layout_property(line, "Separator", "orientation", "vertical")
                line.resize(40, 160)
                assert (line.width(), line.height()) == (2, 160)
            check_payloads([])
        ''')


if __name__ == "__main__":
    unittest.main()
