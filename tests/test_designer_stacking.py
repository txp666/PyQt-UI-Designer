"""Overlapping controls must retain their visible and clickable order."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QApplication
from app.core.project import ProjectManager
from app.designer.canvas import DesignScene
from app.designer.canvas_item import CanvasItem
from app.widgets.basic import register_basic_widgets
from tests import test_preview_export_parity as parity


class DesignerStackingTests(unittest.TestCase):
    run_both = parity.PreviewExportParityTests.run_both

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        register_basic_widgets()

    def make_scene(self):
        scene = DesignScene()
        for name in ("back", "front"):
            item = CanvasItem("PushButton", {
                "text": name, "command": name.upper(),
            }, widget_id=name)
            item.setPos(20, 20)
            scene.add_canvas_item(item)
        self.addCleanup(scene.clear)
        return scene

    @staticmethod
    def top_at_overlap(scene):
        return next(item.widget_id for item in scene.items(QPointF(50, 35))
                    if isinstance(item, CanvasItem))

    def test_repeated_save_reload_keeps_topmost_control(self):
        scene = self.make_scene()
        manager = ProjectManager()
        self.assertEqual(self.top_at_overlap(scene), "front")
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "overlap.uidp")
            for _ in range(3):
                manager.save_from_scene(scene, path)
                self.assertEqual([w["id"] for w in manager.current.widgets],
                                 ["back", "front"])
                manager.load_to_scene(scene, path)
                self.assertEqual(self.top_at_overlap(scene), "front")

    def test_preview_and_export_click_same_control_as_designer(self):
        scene = self.make_scene()
        project = ProjectManager().export_scene_data(scene)
        self.assertEqual(self.top_at_overlap(scene), "front")
        self.run_both(project.widgets, r'''
            from PyQt5.QtCore import QPoint
            surface = widgets["back"].parentWidget()
            target = surface.childAt(QPoint(50, 35))
            assert target is widgets["front"], target
            QTest.mouseClick(target, Qt.LeftButton)
            check_payloads([b"FRONT\r\n"])
        ''')


if __name__ == "__main__":
    unittest.main()
