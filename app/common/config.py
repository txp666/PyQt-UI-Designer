# coding: utf-8
import json
import sys
import os
from enum import Enum
from pathlib import Path

from qfluentwidgets import (
    qconfig, QConfig, ConfigItem, OptionsConfigItem,
    BoolValidator, OptionsValidator, Theme, ConfigSerializer,
)
from app.common.metadata import APP_NAME, APP_VERSION

CONFIG_DIR = Path(os.path.expanduser("~")) / ".pyqt_ui_designer"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"
# The English texts, {Chinese source text: English}; also exported with the applications.
TRANSLATION_FILE = Path(__file__).resolve().parents[1] / "resource" / "i18n" / "en.json"


class Language(Enum):
    """The interface language setting, in the order the settings page offers it."""
    AUTO = "Auto"
    CHINESE_SIMPLIFIED = "zh_CN"
    ENGLISH = "en_US"


class LanguageSerializer(ConfigSerializer):
    def serialize(self, language):
        return language.value

    def deserialize(self, value: str):
        try:
            return Language(value)
        except ValueError:
            return Language.AUTO


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
# qconfig.load forwards cfg's themeChanged to qconfig but not themeColorChanged, which the palette listens to.
cfg.themeColorChanged.connect(qconfig.themeColorChanged)
if sys.platform == "darwin" and hasattr(cfg, "fontFamilies"):
    qconfig.set(cfg.fontFamilies, ["PingFang SC", "Helvetica Neue"], save=False)


def language_setting():
    """The language setting as stored: "Auto", "zh_CN" or "en_US"."""
    return cfg.get(cfg.language).value


def english_table():
    """The English table, {Chinese source text: English}."""
    return json.loads(TRANSLATION_FILE.read_text(encoding="utf-8"))
