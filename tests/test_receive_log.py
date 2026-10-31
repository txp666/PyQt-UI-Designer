# coding: utf-8
"""The receive log shows text the way the link that received it spells it, and the 自动 display
format drops the noise of binary arithmetic without hiding real digits."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.core.binding_values import binding_decimals
from app.core.comm_manager import commHub
from app.core.data_binding import BindingEntry
from app.core.protocol_parser import text_encoding
from app.widgets.composite import DataRecvCard, register_composite_widgets


class AutoFormatTests(unittest.TestCase):
    def test_auto_keeps_real_digits_and_drops_binary_noise(self):
        self.assertEqual(binding_decimals(267 * 0.1, "自动"), 26.7)
        self.assertEqual(binding_decimals(0.1 + 0.2, "自动"), 0.3)
        self.assertEqual(binding_decimals(60.0, "自动"), 60.0)
        self.assertEqual(binding_decimals(25.299999237060547, "自动"), 25.2999992370605)
        self.assertEqual(binding_decimals(1 / 3, "自动"), 0.333333333333333)
        for untouched in (267, True, "26.700000000000003", float("nan"), float("inf")):
            with self.subTest(value=untouched):
                result = binding_decimals(untouched, "自动")
                self.assertTrue(result is untouched or result != result)
        self.assertEqual(binding_decimals(267 * 0.1, "2"), "26.70")

    def test_a_scaled_register_reads_cleanly(self):
        entry = BindingEntry("display", "value", type_name="NumericDisplay", parse_mode="键值匹配",
                             key="t", expression="value * 0.1")
        self.assertEqual(str(entry.format_value(entry.evaluate(267))), "26.7")


class ReceiveLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        register_composite_widgets()

    def test_links_know_their_text_encoding(self):
        self.assertEqual(text_encoding("line", {"encoding": "GBK"}), "gbk")
        self.assertEqual(text_encoding("line", {}), "utf-8")
        self.assertEqual(text_encoding("hex", {"encoding": "gbk"}), "utf-8")
        self.assertEqual(text_encoding("modbus_ascii", None), "utf-8")

    def test_the_log_decodes_with_the_encoding_of_the_link_that_received(self):
        card = DataRecvCard()
        self.addCleanup(card.deleteLater)
        gbk = "温度:25.3,湿度:60;".encode("gbk")
        try:
            commHub.serial.text_encoding = "gbk"
            commHub.serial.rawReceived.emit(gbk)
            QTest.qWait(50)
            self.assertEqual(commHub.raw_encoding, "gbk")
            self.assertEqual(commHub.decode_raw(gbk), "温度:25.3,湿度:60;")
            self.assertIn("温度:25.3,湿度:60;", card._output.toPlainText())
            # Another link still in UTF-8 is not read as GBK.
            commHub.tcp.rawReceived.emit("湿度=60\n".encode("utf-8"))
            QTest.qWait(50)
            self.assertEqual(commHub.raw_encoding, "utf-8")
            self.assertIn("湿度=60", card._output.toPlainText())
        finally:
            commHub.serial.text_encoding = "utf-8"


if __name__ == "__main__":
    unittest.main()
