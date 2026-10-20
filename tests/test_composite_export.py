"""Exercise configured cards and containers in preview and standalone applications."""
import unittest

from tests import test_preview_export_parity as parity


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
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            assert bus._poll_timer.isActive()
            assert bus._poll_timer.interval() == 250
            assert not bus._send_btn.isEnabled()
            bus._poll_timer.timeout.emit()
            check_payloads([frame, frame])
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            assert not bus._poll_timer.isActive()
            assert bus._send_btn.isEnabled()
            # Malformed text must not turn into a write to address zero.
            address = getattr(bus, "_addr_edit", None) or bus._addr
            address.setText("not-an-address")
            QTest.mouseClick(bus._send_btn, Qt.LeftButton)
            check_payloads([frame, frame])
            assert "整数" in bus._status.text()
            address.setText("32")
            bus._poll_edit.setText("9999999999999999")
            QTest.mouseClick(bus._poll_btn, Qt.LeftButton)
            assert not bus._poll_timer.isActive()
            assert "60000" in bus._status.text()
            QTest.mouseClick(bus._send_btn, Qt.LeftButton)
            check_payloads([frame, frame, frame])
        ''')

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
            from qfluentwidgets import Theme, setTheme
            for theme in (Theme.DARK, Theme.LIGHT):
                setTheme(theme)
                app.processEvents()
                for kind, widget in widgets.items():
                    assert widget._title == f"配置-{kind}"
                    # Render before and after clearing the title to prove it is painted.
                    titled = widget.grab().toImage()
                    widget.set_title("")
                    empty = widget.grab().toImage()
                    assert titled != empty, kind
                    widget.set_title(f"配置-{kind}")
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
