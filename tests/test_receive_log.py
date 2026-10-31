# coding: utf-8
"""The receive log shows text the way the link that received it spells it, and the 自动 display
format drops the noise of binary arithmetic without hiding real digits."""
import os
import time
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
        for value, shown in ((267 * 0.1, 26.7), (0.1 + 0.2, 0.3), (60.0, 60.0),
                             (25.299999237060547, 25.2999992370605), (1 / 3, 0.333333333333333)):
            with self.subTest(value=value):
                self.assertEqual(binding_decimals(value, "自动"), shown)
        for untouched in (267, True, "26.700000000000003", float("nan"), float("inf")):
            with self.subTest(value=untouched):
                result = binding_decimals(untouched, "自动")
                self.assertTrue(result is untouched or result != result)
        self.assertEqual(binding_decimals(267 * 0.1, "2"), "26.70")
        # A register scaled by an expression reads cleanly.
        entry = BindingEntry("display", "value", type_name="NumericDisplay", parse_mode="键值匹配",
                             key="t", expression="value * 0.1")
        self.assertEqual(str(entry.format_value(entry.evaluate(267))), "26.7")


class ReceiveLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        register_composite_widgets()

    def wait_for(self, predicate, what):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate(), f"Timed out waiting for {what}")

    def test_the_log_decodes_with_the_encoding_of_the_link_that_received(self):
        for parser_type, config, encoding in (("line", {"encoding": "GBK"}, "gbk"), ("line", {}, "utf-8"),
                                              ("hex", {"encoding": "gbk"}, "utf-8"), ("modbus_ascii", None, "utf-8")):
            with self.subTest(parser=parser_type, config=config):
                self.assertEqual(text_encoding(parser_type, config), encoding)
        card = DataRecvCard()
        self.addCleanup(card.deleteLater)
        output = card._output.toPlainText
        try:
            commHub.serial.text_encoding = "gbk"
            commHub.serial.rawReceived.emit("温度:25.3,湿度:60;".encode("gbk"))
            self.wait_for(lambda: "温度:25.3,湿度:60;" in output(), "the GBK text")
            self.assertEqual(commHub.raw_encoding, "gbk")
            # Another link still in UTF-8 is not read as GBK.
            commHub.tcp.rawReceived.emit("湿度=60\n".encode("utf-8"))
            self.wait_for(lambda: "湿度=60" in output(), "the UTF-8 text")
            self.assertEqual(commHub.raw_encoding, "utf-8")
        finally:
            commHub.serial.text_encoding = "utf-8"


if __name__ == "__main__":
    unittest.main()
