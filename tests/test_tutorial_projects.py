"""The video tutorials' example projects keep loading and exporting as the designer changes."""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from app.core.code_generator import generate_project
from app.core.project import ProjectData
from app.widgets.basic import register_basic_widgets
from app.widgets.chart import register_chart_widgets
from app.widgets.comm import register_comm_widgets
from app.widgets.composite import register_composite_widgets
from app.widgets.display import register_display_widgets
from app.widgets.layout import register_layout_widgets


TUTORIALS = Path(__file__).resolve().parents[1] / "examples" / "tutorials"


class TutorialProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for register in (
            register_basic_widgets, register_chart_widgets, register_comm_widgets,
            register_composite_widgets, register_display_widgets, register_layout_widgets,
        ):
            register()

    def test_every_tutorial_project_loads_and_exports(self):
        projects = sorted(TUTORIALS.glob("*.uidp"))
        self.assertTrue(projects)
        for source in projects:
            with self.subTest(project=source.name):
                project = ProjectData.from_dict(json.loads(source.read_text(encoding="utf-8")))
                project.file_path = str(source)
                with tempfile.TemporaryDirectory() as folder:
                    generate_project(project, folder, theme_mode="Auto")
                    generated = sorted(Path(folder).glob("*.py"))
                    self.assertIn("main.py", [path.name for path in generated])
                    for path in generated:
                        compile(path.read_text(encoding="utf-8"), str(path), "exec")
