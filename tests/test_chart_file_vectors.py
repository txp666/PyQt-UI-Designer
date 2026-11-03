"""The chart's history files match tests/data/chart_file_vectors.json, which FluentHMI Studio's chart is checked
against too, so either app reads what the other saved."""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import sip
from PyQt5.QtWidgets import QApplication

from app.core.chart_runtime import RealtimeLineChart

VECTORS = json.loads((Path(__file__).parent / "data" / "chart_file_vectors.json").read_text(encoding="utf-8"))


class ChartFileVectorTests(unittest.TestCase):
    def test_saved_and_loaded_files_match_the_shared_vectors(self):
        self.app = QApplication.instance() or QApplication([])
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        for case in VECTORS["save"]:
            chart = RealtimeLineChart()
            self.addCleanup(sip.delete, chart)
            chart.configure([{"name": name} for name in case["names"]])
            for history, values in zip(chart._data, case["values"]):
                for value in values:
                    history.append(value)
            for kind in ("csv", "json"):
                with self.subTest(case["title"], kind=kind):
                    path = folder / f"saved.{kind}"
                    chart.save_data(path)
                    self.assertEqual(path.read_bytes().decode("utf-8"), case[kind])
        for case in VECTORS["load"]:
            with self.subTest(case["title"]):
                path = folder / f"load.{case['format']}"
                path.write_bytes(case["text"].encode("utf-8"))
                if case.get("error"):
                    with self.assertRaises(ValueError):
                        chart._read_history(path)
                    continue
                names, histories = chart._read_history(path)
                values = [list(history.values()) for history in histories]
                for history in histories:
                    history.close()
                self.assertEqual(names, case["names"])
                self.assertEqual(values, case["values"])


if __name__ == "__main__":
    unittest.main()
