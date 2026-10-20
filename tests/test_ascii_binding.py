"""An empty ASCII field clears text, while a truncated field leaves it intact."""
import unittest

from tests import test_binding_resilience as binding_checks


class AsciiBindingTests(unittest.TestCase):
    setUpClass = classmethod(binding_checks.BindingResilienceTests.setUpClass.__func__)
    run_both = binding_checks.BindingResilienceTests.run_both

    def test_complete_empty_fields_clear_preview_and_standalone_displays(self):
        fields = {"parseMode": "HEX字节提取", "dataType": "ASCII",
                  "frameHeader": "AA55", "frameTail": "55AA"}
        self.run_both([
            binding_checks.bound("Label", "label", {**fields, "byteOffset": 0}),
            binding_checks.bound("NumericDisplay", "value", {**fields, "byteOffset": 2}),
            binding_checks.bound("Label", "mapped", {
                **fields, "expression": "'EMPTY' if value == '' else value"}),
        ], """
            emit_raw(bytes.fromhex("AA55") + b"xxOK" + bytes.fromhex("55AA"))
            assert text("label") == "xxOK" and text("value") == "OK"
            emit_raw(bytes.fromhex("AA5555AA"))
            assert text("label") == "" and text("mapped") == "EMPTY"
            # Offset two is absent, rather than an empty field, in this frame.
            assert text("value") == "OK"
            emit_raw(bytes.fromhex("AA55") + b"xx" + bytes.fromhex("55AA"))
            assert text("value") == ""
            # Complete frames coalesced in one read must apply the last empty value.
            emit_raw(bytes.fromhex("AA55") + b"old" + bytes.fromhex("55AAAA5555AA"))
            assert text("label") == "" and text("mapped") == "EMPTY"
        """)

    def test_partial_frames_and_short_offsets_do_not_clear_previous_text(self):
        self.run_both([
            binding_checks.bound("Label", "value", {
                "parseMode": "HEX字节提取", "dataType": "ASCII", "byteOffset": 2,
                "frameHeader": "AA55", "frameTail": "55AA"}),
        ], """
            emit_raw(bytes.fromhex("AA55") + b"xxREADY" + bytes.fromhex("55AA"))
            assert text("value") == "READY"
            emit_raw(bytes.fromhex("AA55") + b"x" + bytes.fromhex("55AA"))
            assert text("value") == "READY"
            emit_raw(bytes.fromhex("AA55"))
            assert text("value") == "READY"
            emit_raw(b"xx")
            assert text("value") == "READY"
            emit_raw(bytes.fromhex("55AA"))
            assert text("value") == ""
            emit_raw(bytes.fromhex("AA55") + b"xxNEXT" + bytes.fromhex("55AA"))
            assert text("value") == "NEXT"
            emit_raw(bytes.fromhex("AA55") + b"xx\\x00ignored" + bytes.fromhex("55AA"))
            assert text("value") == ""
        """)
