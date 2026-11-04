"""Every Chinese interface text goes through tr() / N_() and has an English translation (tools/check_i18n.py)."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TranslationTests(unittest.TestCase):
    def test_every_text_is_translatable_and_translated(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "check_i18n.py")],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
