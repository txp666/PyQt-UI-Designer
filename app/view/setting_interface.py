# coding: utf-8
"""Settings interface with Fluent setting cards."""
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

from qfluentwidgets import (
    ScrollArea, ExpandLayout, SettingCardGroup,
    SwitchSettingCard, ComboBoxSettingCard,
    PrimaryPushSettingCard, OptionsSettingCard,
    FluentIcon as FIF, InfoBar, InfoBarPosition,
    setTheme, Theme, MessageBox,
)

from app.common.config import cfg, APP_VERSION, isWin11
from app.common.signal_bus import signalBus
from app.common.update_checker import UpdateCheckThread, RELEASE_URL


class SettingInterface(ScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingInterface")
        self.setWidgetResizable(True)

        self._container = QWidget()
        self._container.setObjectName("settingContainer")
        self._layout = ExpandLayout(self._container)
        self._layout.setContentsMargins(36, 20, 36, 20)
        self._layout.setSpacing(20)
        self.setWidget(self._container)

        self._init_cards()
        self.setStyleSheet(
            "QScrollArea, #settingContainer { background: transparent; border: none; }"
        )

    def _init_cards(self):
        # personalization
        self.personalGroup = SettingCardGroup("个性化", self._container)

        self.themeCard = OptionsSettingCard(
            cfg.themeMode, FIF.BRUSH, "主题",
            "切换应用程序的外观",
            texts=["浅色", "深色", "跟随系统"],
            parent=self.personalGroup,
        )
        self.themeCard.optionChanged.connect(self._on_theme_changed)

        self.micaCard = SwitchSettingCard(
            FIF.TRANSPARENT, "云母效果",
            "窗口背景半透明 (仅 Win11)",
            configItem=cfg.micaEnabled,
            parent=self.personalGroup,
        )
        self.micaCard.checkedChanged.connect(signalBus.micaEnableChanged)
        self.micaCard.setEnabled(isWin11())

        self.zoomCard = ComboBoxSettingCard(
            cfg.dpiScale, FIF.ZOOM, "界面缩放",
            "调整控件和字体大小",
            texts=["100%", "125%", "150%", "175%", "200%", "自动"],
            parent=self.personalGroup,
        )

        self.personalGroup.addSettingCard(self.themeCard)
        self.personalGroup.addSettingCard(self.micaCard)
        self.personalGroup.addSettingCard(self.zoomCard)

        # designer settings
        self.designerGroup = SettingCardGroup("设计器", self._container)

        self.gridCard = SwitchSettingCard(
            FIF.TILES, "显示网格",
            "在画布上显示对齐网格",
            configItem=cfg.showGrid,
            parent=self.designerGroup,
        )
        self.snapCard = SwitchSettingCard(
            FIF.PIN, "吸附网格",
            "移动控件时自动吸附到网格",
            configItem=cfg.snapToGrid,
            parent=self.designerGroup,
        )

        self.designerGroup.addSettingCard(self.gridCard)
        self.designerGroup.addSettingCard(self.snapCard)

        # serial defaults
        self.serialGroup = SettingCardGroup("串口默认设置", self._container)

        self.baudCard = ComboBoxSettingCard(
            cfg.defaultBaudRate, FIF.SPEED_HIGH, "默认波特率",
            "新项目的默认串口波特率",
            texts=["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"],
            parent=self.serialGroup,
        )
        self.serialGroup.addSettingCard(self.baudCard)

        # about
        self.aboutGroup = SettingCardGroup("关于", self._container)
        self.aboutCard = PrimaryPushSettingCard(
            "检查更新", FIF.INFO, "PyQt UI Designer",
            f"版本 {APP_VERSION}  •  面向硬件工程师的可视化上位机设计工具",
            parent=self.aboutGroup,
        )
        self.aboutCard.clicked.connect(self._check_update)
        self.aboutGroup.addSettingCard(self.aboutCard)

        self._layout.addWidget(self.personalGroup)
        self._layout.addWidget(self.designerGroup)
        self._layout.addWidget(self.serialGroup)
        self._layout.addWidget(self.aboutGroup)

        self._update_thread = None

    def _on_theme_changed(self, ci):
        setTheme(cfg.get(ci))
        signalBus.themeChanged.emit()

    def _check_update(self):
        if self._update_thread and self._update_thread.isRunning():
            return
        self.aboutCard.button.setEnabled(False)
        self.aboutCard.button.setText("检查中...")
        self._update_thread = UpdateCheckThread(APP_VERSION, self)
        self._update_thread.result.connect(self._on_update_result)
        self._update_thread.start()

    def _on_update_result(self, has_new, latest, current, url, changelog, error):
        self.aboutCard.button.setEnabled(True)
        self.aboutCard.button.setText("检查更新")

        if error:
            InfoBar.error("检查更新失败", error, parent=self,
                          duration=4000, position=InfoBarPosition.TOP)
            return

        if has_new:
            body = f"发现新版本 {latest}（当前 v{current}）\n\n"
            if changelog:
                lines = changelog.strip().splitlines()
                body += "\n".join(lines[:15])
                if len(lines) > 15:
                    body += "\n..."
            body += "\n\n是否打开下载页面？"
            w = MessageBox("发现新版本", body, self.window())
            w.yesButton.setText("前往下载")
            w.cancelButton.setText("稍后再说")
            if w.exec():
                QDesktopServices.openUrl(QUrl(url))
        else:
            InfoBar.success("已是最新版本",
                            f"当前版本 v{current} 已是最新",
                            parent=self, duration=3000,
                            position=InfoBarPosition.TOP)
