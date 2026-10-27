"""docs/uidp-format.md lets people and AI assistants write .uidp files by hand: its widget reference must match
the widget definitions, and its complete example must load and use only real property names and options."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_uidp  # noqa: E402
import uidp_reference  # noqa: E402


class UidpGuideTests(unittest.TestCase):
    def setUp(self):
        # A Windows checkout may turn the line endings into CRLF.
        self.document = (ROOT / "docs" / "uidp-format.md").read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_widget_reference_is_current(self):
        updated = uidp_reference.with_widget_reference(self.document)
        self.assertIsNotNone(updated, "docs/uidp-format.md has lost the marker line of its widget reference")
        self.assertTrue(updated == self.document, "The widget reference in docs/uidp-format.md is out of date: "
                                                  "run python tools/uidp_reference.py docs/uidp-format.md")

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
