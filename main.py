# coding: utf-8
import os
import sys
import ctypes
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator

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
app.exec()
