# coding: utf-8
import sys
import os
from enum import Enum
from pathlib import Path

from PyQt5.QtCore import QLocale
from qfluentwidgets import (
    qconfig, QConfig, ConfigItem, OptionsConfigItem,
    BoolValidator, OptionsValidator, Theme, ConfigSerializer,
)

APP_NAME = "PyQt UI Designer"
APP_VERSION = "0.1.0"

CONFIG_DIR = Path(os.path.expanduser("~")) / ".pyqt_ui_designer"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"


class Language(Enum):
    CHINESE_SIMPLIFIED = QLocale(QLocale.Chinese, QLocale.China)
    ENGLISH = QLocale(QLocale.English)
    AUTO = QLocale()


class LanguageSerializer(ConfigSerializer):
    def serialize(self, language):
        return language.value.name() if language != Language.AUTO else "Auto"

    def deserialize(self, value: str):
        return Language(QLocale(value)) if value != "Auto" else Language.AUTO


def isWin11():
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000


class Config(QConfig):

    micaEnabled = ConfigItem("MainWindow", "MicaEnabled", isWin11(), BoolValidator())
    dpiScale = OptionsConfigItem(
        "MainWindow", "DpiScale", "Auto",
        OptionsValidator([1, 1.25, 1.5, 1.75, 2, "Auto"]),
        restart=True,
    )
    language = OptionsConfigItem(
        "MainWindow", "Language", Language.AUTO,
        OptionsValidator(Language), LanguageSerializer(), restart=True,
    )

    recentProjects = ConfigItem("Project", "RecentProjects", [])
    lastProjectPath = ConfigItem("Project", "LastProjectPath", "")
    gridSize = ConfigItem("Designer", "GridSize", 10)
    snapToGrid = ConfigItem("Designer", "SnapToGrid", True, BoolValidator())
    showGrid = ConfigItem("Designer", "ShowGrid", True, BoolValidator())
    canvasWidth = ConfigItem("Designer", "CanvasWidth", 1200)
    canvasHeight = ConfigItem("Designer", "CanvasHeight", 800)

    defaultBaudRate = OptionsConfigItem(
        "Serial", "DefaultBaudRate", 115200,
        OptionsValidator([9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]),
    )


cfg = Config()
cfg.themeMode.value = Theme.AUTO
qconfig.load(str(CONFIG_FILE), cfg)
