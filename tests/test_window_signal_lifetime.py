"""Window callbacks remain safe when PyQt cannot infer a QObject receiver."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_SETUP = r"""
import functools
import sys
import traceback
from contextlib import ExitStack
from unittest.mock import patch
from PyQt5 import sip
from PyQt5.QtCore import QEvent
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import qconfig
from qfluentwidgets.window.fluent_window import FluentTitleBar

errors = []
calls = []
created_title_bars = []
def record_exception(*exc):
    errors.append(''.join(traceback.format_exception(*exc)))
    traceback.print_exception(*exc)
sys.excepthook = record_exception

class OpaqueSlot:
    # Compiled methods may look like ordinary callables to PyQt. This preserves
    # their behavior while deliberately omitting Python's QObject-bound method.
    def __init__(self, function):
        self.function = function
        self.key = "_opaque_" + function.__name__
    def __get__(self, instance, owner):
        if instance is None:
            return self
        if self.key not in instance.__dict__:
            def invoke(*args):
                calls.append((type(instance).__name__, self.function.__name__))
                return self.function(instance, *args)
            instance.__dict__[self.key] = functools.partial(invoke)
        return instance.__dict__[self.key]

def opaque_slots(stack, cls, names):
    for name in names:
        stack.enter_context(patch.object(cls, name, OpaqueSlot(getattr(cls, name))))

app = QApplication([])
with ExitStack() as stack:
    if sys.platform == "darwin":
        from qframelesswindow.mac import MacFramelessWindow
        for name in ("updateFrameless", "_hideSystemTitleBar",
                     "setSystemTitleBarButtonVisible"):
            stack.enter_context(patch.object(MacFramelessWindow, name,
                                            lambda *args, **kwargs: None))
    opaque_slots(stack, FluentTitleBar, ("setTitle", "setIcon"))
    original_title_init = FluentTitleBar.__init__
    def record_title_bar(self, *args, **kwargs):
        original_title_init(self, *args, **kwargs)
        created_title_bars.append(self)
    stack.enter_context(patch.object(FluentTitleBar, "__init__", record_title_bar))
__CHECKS__
    assert not errors, errors
print("WINDOW_SIGNAL_LIFETIME_OK")
"""

_TITLE_CHECKS = """
old_bars = [bar for bar in created_title_bars if bar is not window.titleBar]
assert old_bars, "FluentWindow must exercise its constructor title-bar replacement"
app.sendPostedEvents(None, QEvent.DeferredDelete)
assert all(sip.isdeleted(bar) for bar in old_bars)

title_observations = []
window.windowTitleChanged.connect(title_observations.append)
for title, color in (("after initialization", "#00aa00"), ("replacement title", "#aa0000")):
    if title == "replacement title":
        old_bar = window.titleBar
        window.setTitleBar(FluentTitleBar(window))
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        assert sip.isdeleted(old_bar)
    window.setWindowTitle(title)
    pixmap = QPixmap(4, 4)
    pixmap.fill(QColor(color))
    window.setWindowIcon(QIcon(pixmap))
    assert window.titleBar.titleLabel.text() == title
    assert window.titleBar.iconLabel.pixmap().toImage().pixelColor(0, 0).name() == color
assert title_observations == ["after initialization", "replacement title"]
assert not errors, errors
window.deleteLater()
app.sendPostedEvents(None, QEvent.DeferredDelete)
"""


class WindowSignalLifetimeTests(unittest.TestCase):
    def run_script(self, checks, cwd=_ROOT):
        script = _SETUP.replace(
            "__CHECKS__", textwrap.indent(textwrap.dedent(checks).strip(), "    "))
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", script],
            cwd=cwd, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": ""},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WINDOW_SIGNAL_LIFETIME_OK", result.stdout)

    def test_designer_retires_replaced_title_and_icon_callbacks(self):
        self.run_script(
            "from app.view.main_window import MainWindow\nwindow = MainWindow()\n"
            + _TITLE_CHECKS)

    def test_selected_scene_can_be_destroyed_after_its_view(self):
        self.run_script("""
            from app.designer.canvas import DesignScene, DesignView
            from app.designer.canvas_item import CanvasItem
            from app.widgets.basic import register_basic_widgets
            register_basic_widgets()
            opaque_slots(stack, DesignView, ("_on_selection_changed",))
            scene = DesignScene()
            view = DesignView(scene)
            item = CanvasItem("Label", {})
            scene.add_canvas_item(item)
            item.setSelected(True)
            assert item in scene.selectedItems()
            assert ("DesignView", "_on_selection_changed") in calls
            view.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            assert sip.isdeleted(view) and not sip.isdeleted(scene)
            calls.clear()
            # QGraphicsScene's destructor emits selectionChanged while removing
            # selected items. It must not call back into the already deleted view.
            scene.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            assert sip.isdeleted(scene)
            assert not calls, calls
        """)

    def test_fluent_bridges_preserve_theme_and_config_updates_and_are_idempotent(self):
        self.run_script("""
            import types
            from qfluentwidgets import (
                CardWidget, OptionsSettingCard, SwitchSettingCard, RangeSettingCard,
                ColorSettingCard, ComboBoxSettingCard, FluentIcon, Theme, setTheme,
                ConfigItem, BoolValidator, OptionsConfigItem, OptionsValidator,
                RangeConfigItem, RangeValidator, ColorConfigItem,
            )
            from qfluentwidgets.common.animation import BackgroundAnimationWidget
            from app.core.qt_window_lifetime import install_fluent_signal_lifetimes
            classes = (OptionsSettingCard, SwitchSettingCard, RangeSettingCard,
                       ColorSettingCard, ComboBoxSettingCard)
            opaque_slots(stack, BackgroundAnimationWidget, ("_updateBackgroundColor",))
            for cls in classes:
                opaque_slots(stack, cls, ("setValue",))
            install_fluent_signal_lifetimes()
            methods = [cls.setValue for cls in classes]
            install_fluent_signal_lifetimes()
            assert methods == [cls.setValue for cls in classes]
            assert all(isinstance(method, types.FunctionType) for method in methods)

            options = OptionsConfigItem("Test", "Options", "A", OptionsValidator(["A", "B"]))
            switch = ConfigItem("Test", "Switch", False, BoolValidator())
            number = RangeConfigItem("Test", "Range", 1, RangeValidator(0, 10))
            color = ColorConfigItem("Test", "Color", "#112233")
            combo = OptionsConfigItem("Test", "Combo", "A", OptionsValidator(["A", "B"]))
            cards = [
                OptionsSettingCard(options, FluentIcon.BRUSH, "Options", texts=["A", "B"]),
                SwitchSettingCard(FluentIcon.BRUSH, "Switch", configItem=switch),
                RangeSettingCard(number, FluentIcon.BRUSH, "Range"),
                ColorSettingCard(color, FluentIcon.BRUSH, "Color"),
                ComboBoxSettingCard(combo, FluentIcon.BRUSH, "Combo", texts=["A", "B"]),
            ]
            for item, value in ((options, "B"), (switch, True), (number, 7),
                                (color, QColor("#abcdef")), (combo, "B")):
                qconfig.set(item, value, save=False)
            assert cards[0].choiceLabel.text() == "B"
            assert cards[1].switchButton.isChecked()
            assert cards[2].slider.value() == 7
            assert cards[3].colorPicker.color.name() == "#abcdef"
            assert cards[4].comboBox.currentText() == "B"
            background = CardWidget()
            setTheme(Theme.DARK, save=False)
            assert ("CardWidget", "_updateBackgroundColor") in calls
            for widget in cards + [background]:
                widget.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            calls.clear()
            for item, value in ((options, "A"), (switch, False), (number, 2),
                                (color, QColor("#112233")), (combo, "A")):
                qconfig.set(item, value, save=False)
            setTheme(Theme.LIGHT, save=False)
            assert not calls, calls
            app.processEvents()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
        """)

    def test_standalone_retires_title_and_theme_callbacks_without_designer_imports(self):
        from app.core.code_generator import generate_project
        from app.core.project import ProjectData

        with tempfile.TemporaryDirectory() as folder:
            generate_project(ProjectData(), folder)
            self.run_script(
                "from ui import MainUI\n"
                "opaque_slots(stack, MainUI, ('apply_theme',))\n"
                "window = MainUI()\n"
                + _TITLE_CHECKS
                + """
calls.clear()
qconfig.themeChangedFinished.emit()
assert not any(name == "apply_theme" for _, name in calls), calls
assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
""", cwd=folder)

    def test_destroyed_designer_panels_release_global_and_scene_callbacks(self):
        self.run_script("""
            from app.common.signal_bus import signalBus
            from app.designer.palette import WidgetPalette, _DraggableListWidget
            from app.designer.property_editor import PropertyEditor
            from app.view.main_window import MainWindow
            from app.view.preview_interface import PreviewInterface
            opaque_slots(stack, MainWindow,
                         ("_on_canvas_changed", "_on_theme_changed", "setMicaEffectEnabled"))
            opaque_slots(stack, PreviewInterface, ("_show_notification",))
            opaque_slots(stack, PropertyEditor,
                         ("_on_widget_selected", "_on_deselected",
                          "_sync_saved_image_path", "commit_pending_edits"))
            opaque_slots(stack, WidgetPalette, ("refresh_icons",))
            opaque_slots(stack, _DraggableListWidget, ("apply_theme",))
            window = MainWindow()
            scene = window.designer_interface.scene

            def emit_external_signals():
                signalBus.canvasChanged.emit()
                signalBus.micaEnableChanged.emit(False)
                signalBus.showNotification.emit("title", "text", "info", 1)
                signalBus.widgetSelected.emit("missing-widget")
                signalBus.widgetDeselected.emit()
                signalBus.projectSaved.emit("project.uidp")
                qconfig.themeChangedFinished.emit()
                if not sip.isdeleted(scene):
                    scene.aboutToSerialize.emit()

            calls.clear()
            emit_external_signals()
            assert window._project_mgr.is_dirty
            expected = {"_on_canvas_changed", "_on_theme_changed", "setMicaEffectEnabled",
                        "_show_notification", "_on_widget_selected", "_on_deselected",
                        "_sync_saved_image_path", "commit_pending_edits",
                        "refresh_icons", "apply_theme"}
            assert expected.issubset({name for _, name in calls}), calls
            assert not errors, errors
            window.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            assert sip.isdeleted(window)
            calls.clear()
            emit_external_signals()
            assert not calls, calls
        """)


if __name__ == "__main__":
    unittest.main()
