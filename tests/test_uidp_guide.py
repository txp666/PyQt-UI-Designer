"""docs/uidp-format.md lets people and AI assistants write .uidp files by hand: its widget list and the widget
reference in docs/uidp-widgets.md must match the widget definitions, and its complete example must load and use
only real property names and options."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_uidp  # noqa: E402
import uidp_reference  # noqa: E402


def _doc(name: str) -> str:
    # A Windows checkout may turn the line endings into CRLF.
    return (ROOT / "docs" / name).read_text(encoding="utf-8").replace("\r\n", "\n")


class UidpGuideTests(unittest.TestCase):
    def setUp(self):
        self.document = _doc("uidp-format.md")

    def test_generated_parts_are_current(self):
        for name, generate in uidp_reference.GENERATED.items():
            with self.subTest(name):
                document = _doc(name)
                updated = uidp_reference.with_generated(document, generate())
                self.assertIsNotNone(updated, f"docs/{name} has lost the marker line of its generated part")
                self.assertTrue(updated == document,
                                f"docs/{name} is out of date: run python tools/uidp_reference.py docs")

    def test_guide_fits_one_read(self):
        # An AI assistant reads the guide with one command. In a test the 32 KB guide came back as "output too
        # large", and the assistant cloned the whole repository to read it, which took several more steps; with
        # the widget reference moved out, the 16 KB guide came back whole.
        size = len(self.document.encode("utf-8"))
        self.assertLess(size, 20000, f"docs/uidp-format.md is {size} bytes: keep it under 20 000, "
                                     "details belong in uidp-widgets.md")

    def test_example_project_is_valid(self):
        # The example is what an AI copies from first, and a misspelt property or option would do nothing.
        match = re.search(r"## 一个完整的例子.*?```json\n(.*?)\n```", self.document, re.S)
        self.assertIsNotNone(match, 'no ```json example under "## 一个完整的例子"')
        self.assertEqual(check_uidp.problems(json.loads(match.group(1))), [])

    def test_checker_reports_misspellings(self):
        project = {"widgets": [
            {"type": "GaugeMeter", "id": "rpm", "properties": {"maxValue": 3000}},
            {"type": "TcpConfigCard", "id": "tcp", "properties": {"defaultMode": "client"}},
            {"type": "RealtimeChart", "id": "chart", "properties": {"_curve_0_title": "负载"}},
            {"type": "PushButton", "id": "reset", "binding": {"parseMode": "键值匹配", "key": "x"}},
        ]}
        found = "\n".join(check_uidp.problems(project))
        for expected in ("没有属性 maxValue", "defaultMode 不能是 'client'", "曲线没有字段 title",
                         "PushButton 不能绑定数据"):
            self.assertIn(expected, found)
        self.assertEqual(check_uidp.problems({"widgets": [{"type": "Gauge"}]}), ["未知控件类型: Gauge"])


if __name__ == "__main__":
    unittest.main()
