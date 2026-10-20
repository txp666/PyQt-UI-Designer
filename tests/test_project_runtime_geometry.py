"""Editable geometry, numeric ranges and image references survive standalone export."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QPoint, QRectF
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication

from app.core.code_generator import generate_project
from app.core.project import ProjectData, ProjectManager
from app.designer.canvas import DesignScene
from app.designer.canvas_item import CanvasItem
from app.designer.property_editor import PropertyEditor
from app.widgets.basic import register_basic_widgets
from app.widgets.chart import register_chart_widgets
from app.widgets.display import register_display_widgets
from app.widgets.layout import register_layout_widgets
from tests import test_preview_export_parity as parity


def item(name, kind, properties=None, geometry=(20, 20, 180, 40), **extra):
    return {"id": name, "type": kind, "properties": properties or {},
            "geometry": dict(zip(("x", "y", "w", "h"), geometry)), **extra}


class ProjectRuntimeGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for register in (register_basic_widgets, register_chart_widgets,
                         register_display_widgets, register_layout_widgets):
            register()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.scene = DesignScene()
        self.addCleanup(self.scene.clear)

    def run_both(self, project, checks):
        script = parity._RUN_APPLICATION.replace(
            'project.widgets = json.loads(os.environ["PROJECT_WIDGETS"])',
            'project.widgets = json.loads(os.environ["PROJECT_WIDGETS"])\n'
            '    project.file_path = os.environ.get("PROJECT_FILE") or None')
        script = script.replace(
            'widgets = {item["id"]: widget for item, widget\n'
            '               in zip(project.widgets, window._widgets)}',
            'from app.core.data_binding import bindingEngine\n'
            '    widgets = dict(bindingEngine._widget_map)')
        script = script.replace("__CHECKS__", textwrap.indent(textwrap.dedent(checks).strip(), "    "))
        output = self.folder / "standalone"
        generate_project(project, output, theme_mode="Light")
        # The export must work after relocation, outside the source project tree.
        moved = self.folder / "relocated-export"
        output.rename(moved)
        for mode in ("preview", "export"):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [sys.executable, "-c", script], cwd=moved,
                    env={**os.environ, "PYTHONPATH": "", "QT_QPA_PLATFORM": "offscreen",
                         "APPLICATION_MODE": mode, "DESIGNER_ROOT": str(parity._ROOT),
                         "PROJECT_WIDGETS": json.dumps(project.widgets),
                         "PROJECT_FILE": project.file_path or ""},
                    capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("PREVIEW_EXPORT_PARITY_OK", result.stdout)

    def test_inverted_ranges_have_one_restored_value_in_designer_preview_and_export(self):
        project = ProjectData()
        project.widgets = [item(kind, kind, {"minimum": 80, "maximum": 20, "value": 50})
                           for kind in ("Slider", "SpinBox", "GaugeMeter")]
        for data in project.widgets:
            canvas = CanvasItem.from_dict(data)
            self.scene.add_canvas_item(canvas)
            self.assertEqual({key: canvas.properties[key] for key in ("minimum", "maximum", "value")},
                             {"minimum": 80, "maximum": 80, "value": 80})
        self.run_both(project, r'''
            for kind in ("Slider", "SpinBox"):
                widget = widgets[kind]
                assert (widget.minimum(), widget.maximum(), widget.value()) == (80, 80, 80)
            assert widgets["GaugeMeter"]._value == 80
            check_payloads([])
        ''')

    def test_range_edits_sync_the_property_panel_and_survive_save_and_export(self):
        for kind in ("Slider", "SpinBox", "GaugeMeter"):
            canvas = CanvasItem(kind, {"minimum": 0, "maximum": 100, "value": 75}, widget_id=kind)
            self.scene.add_canvas_item(canvas)
            editor = PropertyEditor()
            try:
                editor._load_item(canvas)
                for name, value, expected in (("maximum", 50, (0, 50, 50)),
                                               ("minimum", 60, (60, 60, 60)),
                                               ("maximum", -5, (-5, -5, -5))):
                    editor._editors[name].setValue(value)
                    self.assertEqual(tuple(canvas.properties[key] for key in ("minimum", "maximum", "value")), expected)
                    self.assertEqual(tuple(editor._editors[key].value() for key in ("minimum", "maximum", "value")), expected)
                    current = canvas._inner_widget
                    self.assertEqual(current._value if kind == "GaugeMeter" else current.value(), expected[2])
            finally:
                sip.delete(editor)
        manager = ProjectManager()
        project_file = self.folder / "ranges.uidp"
        manager.save_from_scene(self.scene, str(project_file))
        saved = copy.deepcopy(manager.current.widgets)
        manager.load_to_scene(self.scene, str(project_file))
        self.assertEqual(manager.export_scene_data(self.scene).widgets, saved)
        self.run_both(manager.current, r'''
            for kind in ("Slider", "SpinBox"):
                widget = widgets[kind]
                assert (widget.minimum(), widget.maximum(), widget.value()) == (-5, -5, -5)
            gauge = widgets["GaugeMeter"]
            assert gauge._value == -5
            gauge.set_range(0, 20)
            assert gauge._value == 0
            gauge.set_value(15)
            gauge.set_range(0, 10)
            assert gauge._value == 10
            check_payloads([])
        ''')

    def test_tab_coordinates_keep_free_managed_hidden_and_nested_pages_in_place(self):
        tabs = CanvasItem.from_dict(item("tabs", "TabWidget", {
            "tabNames": "Free\nManaged\nNested", "currentTab": 0, "_tabLayout_1": "垂直",
        }, (300, 40, 300, 180), children=[
            item("bottom", "PushButton", {"text": "Bottom"}, (20, 130, 180, 40)),
            item("managed", "PushButton", {"text": "Managed"}, (8, 32, 180, 36), tabIndex=1),
            item("nested", "TabWidget", {"tabNames": "Inner", "currentTab": 0},
                 (10, 50, 250, 120), tabIndex=2, children=[
                     item("inner_button", "PushButton", {"text": "Inner"}, (20, 65, 150, 36)),
                 ]),
        ]))
        self.scene.add_canvas_item(tabs)
        free = tabs._container_children[0]
        expected_free = free.scenePos()
        tabs.set_property("currentTab", 1)
        managed = tabs._container_children[1]
        origin = tabs._inner_widget.currentWidget().mapTo(tabs._inner_widget, QPoint())
        self.assertEqual(managed.pos().y(), origin.y())
        self.assertEqual(free.scenePos(), expected_free)
        tabs.set_property("currentTab", 0)
        manager = ProjectManager()
        project_file = self.folder / "tabs.uidp"
        for _ in range(3):
            before = [entry.to_dict() for entry in self.scene.top_level_canvas_items()]
            manager.save_from_scene(self.scene, str(project_file))
            manager.load_to_scene(self.scene, str(project_file))
            self.assertEqual([entry.to_dict() for entry in self.scene.top_level_canvas_items()], before)
        data = manager.export_scene_data(self.scene)
        managed_y = data.widgets[0]["children"][1]["geometry"]["y"]
        self.run_both(data, "MANAGED_Y = " + repr(managed_y) + "\n" + textwrap.dedent(r'''
            from PyQt5.QtCore import QPoint
            from qfluentwidgets import Theme, setTheme
            root = window if os.environ["APPLICATION_MODE"] == "preview" else window._page
            tabs = widgets["tabs"]
            for theme in (Theme.DARK, Theme.LIGHT):
                setTheme(theme)
                for page, name, expected in ((0, "bottom", (320, 170)),
                                              (1, "managed", (308, 40 + MANAGED_Y)),
                                              (2, "inner_button", (330, 155))):
                    tabs.setCurrentIndex(page)
                    app.processEvents(); app.processEvents()
                    widget = widgets[name]
                    point = widget.mapTo(root, QPoint())
                    assert (point.x(), point.y()) == expected, (name, point, expected)
                    assert widget.isVisible()
                    assert widget.visibleRegion().boundingRect().height() == widget.height(), (name, widget.visibleRegion().boundingRect())
                    assert widgets["bottom"].isVisible() == (page == 0)
                tabs.resize(340, 210)
                app.processEvents(); app.processEvents()
                tabs.setCurrentIndex(0)
                app.processEvents(); app.processEvents()
                assert widgets["bottom"].mapTo(root, QPoint()) == QPoint(320, 170)
            check_payloads([])
        '''))

    def test_relative_images_load_edit_save_as_and_export_without_changing_reference(self):
        source = self.folder / "project"
        source.mkdir()
        (source / "images").mkdir()
        image = QImage(40, 20, QImage.Format_RGB32)
        image.fill(QColor("#12ab34"))
        self.assertTrue(image.save(str(source / "images" / "sample.png")))
        project_file = source / "source.uidp"
        document = ProjectData()
        document.widgets = [item("group", "GroupBox", {"title": "Images"}, (20, 20, 300, 180), children=[
            item("image", "ImageDisplay", {"imagePath": "images/sample.png"}, (20, 35, 200, 100)),
        ])]
        project_file.write_text(json.dumps(document.to_dict()), encoding="utf-8")
        manager = ProjectManager()
        manager.load_to_scene(self.scene, str(project_file))
        canvas_image = self.scene.top_level_canvas_items()[0]._container_children[0]
        self.assertEqual(canvas_image.properties["imagePath"], "images/sample.png")
        self.assertEqual(canvas_image._inner_widget._label.pixmap().toImage().pixelColor(0, 0).name(), "#12ab34")
        canvas_image.set_property("imagePath", "./images/sample.png")
        self.assertFalse(canvas_image._inner_widget._label.pixmap().isNull())
        destination = self.folder / "saved-elsewhere"
        destination.mkdir()
        renamed = destination / "copy.uidp"
        manager.mark_dirty()
        before = canvas_image.properties.copy()
        editor = PropertyEditor()
        editor.set_scene(self.scene)
        editor._load_item(canvas_image)
        self.addCleanup(lambda: sip.delete(editor))
        with patch("app.core.project.os.replace", side_effect=OSError("save failed")):
            with self.assertRaises(OSError):
                manager.save_from_scene(self.scene, str(renamed))
        self.assertEqual(canvas_image.properties, before)
        self.assertEqual(manager.current.file_path, str(project_file))
        manager.save_from_scene(self.scene, str(renamed))
        reference = canvas_image.properties["imagePath"]
        from qfluentwidgets import LineEdit
        self.assertEqual(editor._editors["imagePath"].findChild(LineEdit).text(), reference)
        self.assertFalse(Path(reference).is_absolute())
        self.assertEqual((destination / reference).resolve(), (source / "images" / "sample.png").resolve())
        self.assertFalse(canvas_image._inner_widget._label.pixmap().isNull())
        manager.load_to_scene(self.scene, str(renamed))
        image_data = manager.current.widgets[0]["children"][0]
        self.assertEqual(image_data["properties"]["imagePath"], reference)
        # Newly created or pasted descendants must inherit the loaded project's directory.
        pasted = CanvasItem.from_dict(item("pasted", "CardContainer", children=[
            item("pasted_image", "ImageDisplay", {"imagePath": reference}),
        ]))
        self.scene.add_canvas_item(pasted)
        self.assertFalse(pasted._container_children[0]._inner_widget._label.pixmap().isNull())
        self.run_both(manager.current, r'''
            from pathlib import Path
            image = widgets["image"]
            pixmap = image._label.pixmap()
            assert pixmap is not None and not pixmap.isNull()
            assert pixmap.toImage().pixelColor(0, 0).name() == "#12ab34"
            assert Path(image._path).is_absolute()
            if os.environ["APPLICATION_MODE"] == "export":
                assert Path(image._path).parent.name == "assets"
            check_payloads([])
        ''')


if __name__ == "__main__":
    unittest.main()
