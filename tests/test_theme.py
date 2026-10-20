"""Theme transitions must preserve content and match standalone exports."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import sip
from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication, QLabel, QWidget
from qfluentwidgets import Theme, qconfig, setTheme

from app.core.chart_runtime import RealtimeLineChart
from app.core.code_generator import generate_project
from app.core.project import ProjectData
from app.designer.palette import _DraggableListWidget
from app.widgets.basic import create_widget
from app.widgets.composite import DataRecvCard, LogDisplayBox
from app.widgets.display import NumericDisplay
from app.widgets.layout import HBoxContainer, GroupBoxContainer, TabContainer


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        previous_mode = qconfig.themeMode.value
        previous_palette = QPalette(self.app.palette())
        self.addCleanup(lambda: self.app.setPalette(previous_palette))
        self.addCleanup(lambda: setTheme(previous_mode, save=False))
        self.change_theme(Theme.LIGHT)

    def track(self, obj):
        self.addCleanup(lambda: sip.delete(obj) if not sip.isdeleted(obj) else None)
        return obj

    def change_theme(self, theme):
        setTheme(theme, save=False)
        self.app.processEvents()

    def test_numeric_and_label_keep_user_formatting_and_value(self):
        numeric = self.track(NumericDisplay())
        numeric.set_title("压力")
        numeric.set_value("25.30")
        numeric.set_unit("kPa")
        numeric.set_value_color("#b04bd1")
        numeric.set_font_size(37)
        label = self.track(create_widget("Label", {
            "text": "采集状态", "fontSize": 23, "bold": True,
        }))
        light_title = numeric._title_label.styleSheet()
        for theme in (Theme.DARK, Theme.LIGHT):
            with self.subTest(theme=theme):
                self.change_theme(theme)
                self.assertEqual(numeric._value_label.text(), "25.30")
                self.assertEqual(numeric._title_label.text(), "压力")
                self.assertEqual(numeric._unit_label.text(), "kPa")
                self.assertIn("#b04bd1", numeric._value_label.styleSheet())
                self.assertIn("37px", numeric._value_label.styleSheet())
                self.assertEqual(label.text(), "采集状态")
                self.assertEqual(label.font().pointSize(), 23)
                self.assertTrue(label.font().bold())
                self.assertIn("transparent", label.styleSheet())
                self.assertIn("border: none", label.styleSheet())
                if theme == Theme.DARK:
                    self.assertNotEqual(numeric._title_label.styleSheet(), light_title)
                else:
                    self.assertEqual(numeric._title_label.styleSheet(), light_title)

    def test_chart_recolors_without_rebuilding_or_losing_samples(self):
        chart = self.track(RealtimeLineChart())
        chart.configure([{"name": "压力", "key": "pressure"},
                         {"name": "温度", "key": "temperature"}], 50)
        chart.set_title("采集曲线")
        chart.on_parsed({"pressure": 12.5, "temperature": 24.0})
        chart.on_parsed({"pressure": 13.5, "temperature": 25.0})
        chart._checkboxes[1].setChecked(False)
        chart._refresh_all()
        histories = tuple(chart._data)
        curves = tuple(chart._curves)
        checkboxes = tuple(chart._checkboxes)
        self.assertIsNotNone(chart._plot, "pyqtgraph is a required application dependency")
        light_bg = chart._plot.backgroundBrush().color()
        light_axis = chart._plot.getAxis("left").textPen().color()
        light_curve = chart._curves[0].opts["pen"].color()
        for theme in (Theme.DARK, Theme.LIGHT):
            with self.subTest(theme=theme):
                self.change_theme(theme)
                self.assertEqual(tuple(chart._data), histories)
                self.assertEqual(tuple(chart._curves), curves)
                self.assertEqual(tuple(chart._checkboxes), checkboxes)
                self.assertEqual(list(chart._data[0].values()), [12.5, 13.5])
                self.assertEqual(list(chart._data[1].values()), [24.0, 25.0])
                self.assertFalse(chart._checkboxes[1].isChecked())
                self.assertFalse(chart._curves[1].isVisible())
                self.assertEqual(chart._display_points, 50)
                self.assertIn("采集曲线", chart._plot.plotItem.titleLabel.text)
                if theme == Theme.DARK:
                    self.assertLess(chart._plot.backgroundBrush().color().lightness(), 100)
                    self.assertGreater(chart._plot.getAxis("left").textPen().color().lightness(), 150)
                    self.assertNotEqual(chart._curves[0].opts["pen"].color(), light_curve)
                else:
                    self.assertEqual(chart._plot.backgroundBrush().color(), light_bg)
                    self.assertEqual(chart._plot.getAxis("left").textPen().color(), light_axis)
                    self.assertEqual(chart._curves[0].opts["pen"].color(), light_curve)

    def test_container_children_selection_and_palette_survive_theme_change(self):
        layout = self.track(HBoxContainer())
        layout.set_spacing(17)
        child = QLabel("数值: 42")
        layout._layout.addWidget(child)
        group = self.track(GroupBoxContainer())
        group.set_title("运行参数")
        tabs = self.track(TabContainer())
        tabs.set_tab_names("采集\n设置")
        tabs.setCurrentIndex(1)
        page = tabs.widget(1)
        tab_child = QLabel("设定值", page)
        palette = self.track(_DraggableListWidget())
        palette.addItems(["按钮", "标签"])
        palette.setCurrentRow(1)
        widgets = (layout, group, tabs, palette)
        light_styles = [widget.styleSheet() for widget in widgets]
        for theme in (Theme.DARK, Theme.LIGHT):
            with self.subTest(theme=theme):
                self.change_theme(theme)
                self.assertIs(layout._layout.itemAt(0).widget(), child)
                self.assertEqual(child.text(), "数值: 42")
                self.assertEqual(layout._layout.spacing(), 17)
                self.assertEqual(group.title(), "运行参数")
                self.assertEqual(tabs.currentIndex(), 1)
                self.assertIs(tabs.widget(1), page)
                self.assertIs(tab_child.parent(), page)
                self.assertEqual(tabs.tabText(1), "设置")
                self.assertEqual(palette.currentRow(), 1)
                styles = [widget.styleSheet() for widget in widgets]
                if theme == Theme.DARK:
                    for before, after in zip(light_styles, styles):
                        self.assertNotEqual(before, after)
                else:
                    self.assertEqual(styles, light_styles)
                palette.ensurePolished()
                foreground = palette.palette().color(QPalette.Text).lightness()
                if theme == Theme.DARK:
                    self.assertGreater(foreground, 150)
                else:
                    self.assertLess(foreground, 100)

    def test_terminal_background_and_received_content_remain_readable(self):
        receive = self.track(DataRecvCard())
        log = self.track(LogDisplayBox())
        receive._on_raw_recv(b"pressure=25.30\n")
        receive._on_sent(b"READ\n")
        receive._hex_check.setChecked(True)
        receive._autoscroll_check.setChecked(False)
        log.append_log("sample timeout", "warn")
        documents = [widget._output.toHtml() for widget in (receive, log)]
        for theme in (Theme.DARK, Theme.LIGHT):
            with self.subTest(theme=theme):
                self.change_theme(theme)
                self.assertEqual(
                    [widget._output.toHtml() for widget in (receive, log)], documents)
                self.assertEqual(receive._count, 1)
                self.assertTrue(receive._hex_check.isChecked())
                self.assertFalse(receive._autoscroll_check.isChecked())
                for widget in (receive, log):
                    widget._output.ensurePolished()
                    palette = widget._output.palette()
                    self.assertLess(palette.color(QPalette.Base).lightness(), 70)
                    self.assertGreater(palette.color(QPalette.Text).lightness(), 150)
                    self.assertIn("monospace", widget._output.styleSheet())

    def pixel_color(self, widget, point):
        """Read the painted result, not the QSS or palette's intended color."""
        pixmap = widget.grab()
        self.assertFalse(pixmap.isNull())
        ratio = pixmap.devicePixelRatio()
        return pixmap.toImage().pixelColor(
            round(point.x() * ratio), round(point.y() * ratio))

    def test_preview_canvas_actually_paints_theme_without_rebuilding_widgets(self):
        from app.view.preview_interface import PreviewCanvas
        # A contrasting parent exposes a QWidget subclass that stores a valid
        # background stylesheet but never paints it.
        host = self.track(QWidget())
        palette = host.palette()
        palette.setColor(QPalette.Window, QColor("#8b008b"))
        host.setPalette(palette)
        host.setAutoFillBackground(True)
        host.resize(280, 220)
        canvas = PreviewCanvas(host)
        canvas.setGeometry(10, 10, 240, 180)
        canvas._create_widget_recursive({
            "type": "NumericDisplay",
            "properties": {"value": "25.30", "title": "压力", "unit": "kPa"},
            "geometry": {"x": 15, "y": 15, "w": 100, "h": 90},
        }, canvas)
        number = canvas._widgets[0]
        number.set_value("42.75")
        host.show()
        for theme in (Theme.DARK, Theme.LIGHT, Theme.DARK):
            with self.subTest(theme=theme):
                self.change_theme(theme)
                canvas._update_style()
                self.app.processEvents()
                expected = QColor("#2b2b2b" if theme == Theme.DARK else "#ffffff")
                self.assertEqual(self.pixel_color(canvas, QPoint(210, 150)), expected)
                self.assertIs(canvas._widgets[0], number)
                self.assertEqual(number._value_label.text(), "42.75")
                self.assertEqual(self.pixel_color(host, QPoint(270, 210)), QColor("#8b008b"))

    def test_running_preview_canvas_and_scroll_background_repaint_on_theme_change(self):
        from app.view.preview_interface import PreviewInterface
        preview = self.track(PreviewInterface())
        self.addCleanup(preview._stop_preview)
        # MainWindow routes the finished signal to this method in production.
        qconfig.themeChangedFinished.connect(preview.on_theme_changed)
        project = ProjectData()
        project.canvas_width, project.canvas_height = 240, 180
        project.widgets = [{
            "id": "preview_number", "type": "NumericDisplay",
            "properties": {"title": "压力", "value": "25.30", "unit": "kPa"},
            "geometry": {"x": 15, "y": 15, "w": 100, "h": 90},
        }]
        preview.set_project_data(project)
        preview.resize(820, 540)
        preview.show()
        preview._run_btn.click()
        self.app.processEvents()
        self.assertTrue(preview._running)
        canvas = preview._preview_canvas
        number = canvas._widgets[0]
        number.set_value("42.75")
        for theme in (Theme.DARK, Theme.LIGHT, Theme.DARK):
            with self.subTest(theme=theme):
                self.change_theme(theme)
                canvas_point = canvas.mapTo(preview, QPoint(210, 150))
                viewport = preview._scroll.viewport()
                outer_point = QPoint(5, 5)
                self.assertFalse(canvas.geometry().contains(outer_point))
                scroll_point = viewport.mapTo(preview, outer_point)
                dark = theme == Theme.DARK
                self.assertEqual(self.pixel_color(preview, canvas_point),
                                 QColor("#2b2b2b" if dark else "#ffffff"))
                self.assertEqual(self.pixel_color(preview, scroll_point),
                                 QColor("#202020" if dark else "#f5f5f5"))
                self.assertIs(canvas._widgets[0], number)
                self.assertEqual(number._value_label.text(), "42.75")
                self.assertTrue(preview._running)

    def test_native_palette_follows_explicit_theme(self):
        from app.core.theme_runtime import ThemeController
        controller = self.track(ThemeController(self.app, "Light"))
        native = self.track(QLabel("原生标签"))
        for theme in (Theme.DARK, Theme.LIGHT):
            with self.subTest(theme=theme):
                self.change_theme(theme)
                foreground = native.palette().color(QPalette.WindowText).lightness()
                background = self.app.palette().color(QPalette.Window).lightness()
                if theme == Theme.DARK:
                    self.assertGreater(foreground, 150)
                    self.assertLess(background, 100)
                else:
                    self.assertLess(foreground, 100)
                    self.assertGreater(background, 150)

    def test_auto_tracks_system_but_fixed_theme_does_not(self):
        from app.core.theme_runtime import ThemeController
        with patch("app.core.theme_runtime.darkdetect.theme", return_value="Light") as detect:
            controller = self.track(ThemeController(self.app, "Auto"))
            self.assertEqual(qconfig.themeMode.value, Theme.AUTO)
            self.assertEqual(qconfig.theme, Theme.LIGHT)
            detect.return_value = "Dark"
            controller._check_system_theme()
            self.app.processEvents()
            self.assertEqual(qconfig.theme, Theme.DARK)
            self.assertEqual(qconfig.themeMode.value, Theme.AUTO)
            detect.return_value = "Light"
            controller._check_system_theme()
            self.app.processEvents()
            self.assertEqual(qconfig.theme, Theme.LIGHT)
            self.change_theme(Theme.DARK)
            controller._check_system_theme()
            self.assertEqual(qconfig.theme, Theme.DARK)
            self.assertEqual(qconfig.themeMode.value, Theme.DARK)

    def test_saved_auto_mode_resolves_system_again_on_startup(self):
        from app.core.theme_runtime import ThemeController
        with patch("app.core.theme_runtime.darkdetect.theme", return_value="Light") as detect:
            self.change_theme(Theme.AUTO)
            self.assertEqual(qconfig.theme, Theme.LIGHT)
            # The saved preference is still Auto, but the system changed while
            # the application was not running. Startup must resolve it again.
            detect.return_value = "Dark"
            self.track(ThemeController(self.app, "Auto"))
            self.assertEqual(qconfig.themeMode.value, Theme.AUTO)
            self.assertEqual(qconfig.theme, Theme.DARK)
            self.assertLess(self.app.palette().color(QPalette.Window).lightness(), 100)

    def test_exported_main_inherits_mode_and_keeps_widgets_readable(self):
        # Deliberately omit RealtimeChart/SerialConfigCard: their embedded
        # imports must not accidentally supply another widget's dependencies.
        project = ProjectData()
        project.widgets = [
            {"id": "number", "type": "NumericDisplay",
             "properties": {"title": "压力", "unit": "kPa"}},
            {"id": "label", "type": "Label",
             "properties": {"text": "状态", "fontSize": 21, "bold": True}},
            {"id": "receive", "type": "DataRecvCard"},
            {"id": "group", "type": "GroupBox",
             "properties": {"title": "运行参数"}},
            {"id": "tabs", "type": "TabWidget",
             "properties": {"tabNames": "采集\n设置", "currentTab": 1}},
            {"id": "image", "type": "ImageDisplay"},
            {"id": "gauge", "type": "GaugeMeter"},
            {"id": "led", "type": "LEDIndicator"},
        ]
        code = """
import runpy
import sys
from contextlib import ExitStack
from unittest.mock import patch
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import Theme, isDarkTheme, qconfig, setTheme
import darkdetect

def check_application():
    app = QApplication.instance()
    app.processEvents()
    window = next(w for w in app.topLevelWidgets() if hasattr(w, "widgets"))
    assert qconfig.themeMode.value.value == EXPECTED_MODE
    assert isDarkTheme() == (EXPECTED_MODE != "Light")
    number = window.widgets["number"]
    number.set_value("25.30")
    number.set_value_color("#b04bd1")
    number.set_font_size(37)
    receive = window.widgets["receive"]
    receive._on_raw(b"pressure=25.30")
    content = receive._text.toHtml()
    group = window.widgets["group"]
    tabs = window.widgets["tabs"]
    page = tabs.widget(1)
    label = window.widgets["label"]

    def check_colors(dark):
        app.processEvents()
        for w in (window._page, label, group, tabs.widget(1)):
            w.ensurePolished()
        background = window._page.palette().color(QPalette.Window).lightness()
        foreground = app.palette().color(QPalette.WindowText).lightness()
        assert (background < 100) if dark else (background > 150)
        assert (foreground > 150) if dark else (foreground < 100)
        # The page background must not cascade over the terminal's own colors.
        assert receive._text.palette().color(QPalette.Base).lightness() < 70
        assert receive._text.palette().color(QPalette.Text).lightness() > 150
        assert receive._text.toHtml() == content
        assert number._value.text() == "25.30"
        assert "#b04bd1" in number._value.styleSheet()
        assert "37px" in number._value.styleSheet()
        assert label.font().pointSize() == 21
        assert label.font().bold()
        assert tabs.widget(1) is page and tabs.currentIndex() == 1
        assert group.title() == "运行参数"

    check_colors(isDarkTheme())
    if EXPECTED_MODE == "Auto":
        controller = app.findChildren(__import__("theme_support").ThemeController)[0]
        with patch.object(darkdetect, "theme", return_value="Light"):
            controller._check_system_theme()
            assert qconfig.themeMode.value == Theme.AUTO
            assert not isDarkTheme()
            check_colors(False)
    for theme in (Theme.LIGHT, Theme.DARK, Theme.LIGHT):
        setTheme(theme, save=False)
        check_colors(theme == Theme.DARK)
    print("EXPORTED_THEME_OK", EXPECTED_MODE)
    return 0

with ExitStack() as stack:
    # offscreen winIds are not Cocoa pointers. Leave FluentWindow and its
    # children real; only disable the native macOS title-bar bridge.
    if sys.platform == "darwin":
        from qframelesswindow.mac import MacFramelessWindow
        for method in ("updateFrameless", "_hideSystemTitleBar",
                       "setSystemTitleBarButtonVisible"):
            stack.enter_context(patch.object(
                MacFramelessWindow, method, lambda *args, **kwargs: None))
    stack.enter_context(patch.object(darkdetect, "theme", return_value="Dark"))
    stack.enter_context(patch.object(QApplication, "exec", staticmethod(check_application)))
    runpy.run_path("main.py", run_name="__main__")
"""
        for mode in ("Light", "Dark", "Auto", None):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                self.change_theme(Theme.DARK)
                generate_project(project, folder, theme_mode=mode)
                self.assertTrue((Path(folder) / "theme_support.py").is_file())
                for source in Path(folder).glob("*.py"):
                    compile(source.read_text(), str(source), "exec")
                expected_mode = mode or "Dark"
                script = f"EXPECTED_MODE = {expected_mode!r}\n" + code
                result = subprocess.run(
                    [sys.executable, "-c", script], cwd=folder,
                    env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": ""},
                    text=True, capture_output=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"EXPORTED_THEME_OK {expected_mode}", result.stdout)


if __name__ == "__main__":
    unittest.main()
