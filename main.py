# coding: utf-8
import os
import sys
import ctypes
from pathlib import Path

from PyQt5 import sip
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator

from app.common.dist_smoke import DistributionSmokeTest

smoke_test = DistributionSmokeTest.from_arguments(sys.argv)

from app.common.config import cfg

if cfg.get(cfg.dpiScale) != "Auto":
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = str(cfg.get(cfg.dpiScale))
else:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)

QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
app = QApplication(sys.argv)
app.setApplicationName("PyQt UI Designer")
app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings)

from app.core.theme_runtime import ThemeController

theme_controller = ThemeController(app, cfg.get(cfg.themeMode))

locale = cfg.get(cfg.language).value
translator = FluentTranslator(locale)
app.installTranslator(translator)

from app.view.main_window import MainWindow  # noqa: E402

w = MainWindow()

if sys.platform == "win32":
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "pyqt.ui.designer"
    )
_icon_path = Path(__file__).resolve().parent / "logo.png"
if _icon_path.exists():
    _icon = QIcon(str(_icon_path))
    app.setWindowIcon(_icon)
    w.setWindowIcon(_icon)

w.show()
if smoke_test is not None:
    smoke_test.start(app, w)
exit_code = app.exec()
# Dispose the widget tree while QApplication still exists. Letting SIP tear
# down these native objects during interpreter finalization is order-dependent.
w.setting_interface.shutdown_update_check()
# The design scene has no Qt parent by design, so deleting the window leaves it,
# and the real widget behind every canvas item, alive until finalization.
scene = w.designer_interface.scene
w.deleteLater()
theme_controller.deleteLater()
app.sendPostedEvents(None, QEvent.DeferredDelete)
if smoke_test is not None:
    exit_code = smoke_test.finish(exit_code)  # checks, then disposes, the scene itself
if not sip.isdeleted(scene):
    scene.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
sys.exit(exit_code)
