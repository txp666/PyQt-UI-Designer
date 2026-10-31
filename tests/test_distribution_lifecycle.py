"""The packaged entry point must complete checks and reject swallowed Qt errors."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
_RUN_MAIN = r"""
import runpy
import sys
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication, QTextEdit
from app.common.dist_smoke import DistributionSmokeTest

if sys.platform == "darwin":
    from qframelesswindow.mac import MacFramelessWindow
    for name in ("updateFrameless", "_hideSystemTitleBar", "setSystemTitleBarButtonVisible"):
        setattr(MacFramelessWindow, name, lambda *args, **kwargs: None)

if "__FAULT__" == "deleted_qobject":
    original_load = DistributionSmokeTest._load_demo
    def load_with_deleted_receiver(self):
        original_load(self)
        deleted = QTextEdit()
        deleted.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        # A Python callable can outlive its Qt target. The queued signal exception
        # reaches sys.excepthook instead of propagating out of signal.emit().
        self.serial.rawReceived.connect(lambda data: deleted.setPlainText(str(data)))
    DistributionSmokeTest._load_demo = load_with_deleted_receiver

runpy.run_path("main.py", run_name="__main__")
"""


class DistributionLifecycleTests(unittest.TestCase):
    def run_smoke(self, fault="none"):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "smoke.json"
            result = subprocess.run(
                [sys.executable, "-c", _RUN_MAIN.replace("__FAULT__", fault),
                 "--smoke-test-project", str(ROOT / "demo/project.uidp"),
                 "--smoke-test-report", str(report)],
                cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                capture_output=True, text=True, timeout=60,
            )
            self.assertTrue(report.exists(), result.stdout + result.stderr)
            return result, json.loads(report.read_text(encoding="utf-8"))

    def test_main_entry_runs_demo_and_every_widget_then_exits_normally(self):
        result, report = self.run_smoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + repr(report))
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["exception_count"], 0)
        self.assertEqual(report["cycles"], 6)
        self.assertEqual(report["preview_cycles"], 7)
        self.assertEqual(len(report["widget_types"]), 28)
        self.assertIn("demo_export", report["steps"])
        self.assertIn("registry_export", report["steps"])
        self.assertIn("tcp_loopback_exchange", report["steps"])
        self.assertTrue(report["tcp_loopback"])
        self.assertTrue(report["system_trust_store"])
        self.assertEqual(report["selected_widget"], "all_Label")
        self.assertIn("destroyed_selected_scene", report["steps"])
        self.assertIn("destroyed_window_signals", report["steps"])
        self.assertTrue(report["exported"])

    def test_deleted_qobject_slot_is_recorded_and_causes_nonzero_exit(self):
        result, report = self.run_smoke("deleted_qobject")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr + repr(report))
        self.assertEqual(report["status"], "failed", report)
        self.assertGreater(report["exception_count"], 0)
        self.assertIn("has been deleted", "\n".join(report["errors"]))
        self.assertNotIn("destroyed_window_signals", report["steps"])
