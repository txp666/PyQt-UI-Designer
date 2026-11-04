# coding: utf-8
"""Settings interface with Fluent setting cards."""
import sys

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

from qfluentwidgets import (
    ScrollArea, ExpandLayout, SettingCardGroup,
    SwitchSettingCard, ComboBoxSettingCard, CustomColorSettingCard,
    PrimaryPushSettingCard, OptionsSettingCard,
    FluentIcon as FIF, InfoBar, InfoBarPosition,
    setTheme, setThemeColor, Theme,
)

from app.common.config import cfg, APP_VERSION, isWin11
from app.common.signal_bus import signalBus
from app.common.update_checker import UpdateCheckThread, RELEASE_URL
from app.core.i18n import tr
from app.core.signal_lifetime import SignalConnections
from app.view.update_dialog import UpdateDialog


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
        self.personalGroup = SettingCardGroup(tr("个性化"), self._container)

        self.themeCard = OptionsSettingCard(
            cfg.themeMode, FIF.BRUSH, tr("主题"),
            tr("切换应用程序的外观"),
            texts=[tr("浅色"), tr("深色"), tr("跟随系统")],
            parent=self.personalGroup,
        )
        self.themeCard.optionChanged.connect(self._on_theme_changed)

        # The card saves the colour; setThemeColor restyles the Fluent widgets with it.
        self.themeColorCard = CustomColorSettingCard(
            cfg.themeColor, FIF.PALETTE, tr("主题色"),
            tr("选择 Fluent 控件的强调色"),
            parent=self.personalGroup,
        )
        self.themeColorCard.colorChanged.connect(lambda color: setThemeColor(color))

        # Takes effect at the next start, in the designer and in the applications it exports.
        self.languageCard = ComboBoxSettingCard(
            cfg.language, FIF.LANGUAGE, tr("语言"),
            tr("界面和导出应用的语言，重启后生效"),
            texts=[tr("跟随系统"), "简体中文", "English"],  # i18n: ignore
            parent=self.personalGroup,
        )
        self.languageCard.comboBox.currentIndexChanged.connect(self._on_language_changed)

        # Mica is a Windows 11 backdrop: off and disabled on Windows 10, no card elsewhere.
        self.micaCard = None
        if sys.platform == "win32":
            if isWin11():
                self.micaCard = SwitchSettingCard(
                    FIF.TRANSPARENT, tr("云母效果"), tr("窗口和表面显示半透明"),
                    configItem=cfg.micaEnabled, parent=self.personalGroup,
                )
                self.micaCard.checkedChanged.connect(signalBus.micaEnableChanged)
            else:
                self.micaCard = SwitchSettingCard(
                    FIF.TRANSPARENT, tr("云母效果"), tr("需要 Windows 11"), parent=self.personalGroup)
                self.micaCard.setEnabled(False)

        self.zoomCard = ComboBoxSettingCard(
            cfg.dpiScale, FIF.ZOOM, tr("界面缩放"),
            tr("调整控件和字体大小"),
            texts=["100%", "125%", "150%", "175%", "200%", tr("自动")],
            parent=self.personalGroup,
        )

        self.personalGroup.addSettingCard(self.themeCard)
        self.personalGroup.addSettingCard(self.themeColorCard)
        self.personalGroup.addSettingCard(self.languageCard)
        if self.micaCard is not None:
            self.personalGroup.addSettingCard(self.micaCard)
        self.personalGroup.addSettingCard(self.zoomCard)

        # designer settings
        self.designerGroup = SettingCardGroup(tr("设计器"), self._container)

        self.gridCard = SwitchSettingCard(
            FIF.TILES, tr("显示网格"),
            tr("在画布上显示对齐网格"),
            configItem=cfg.showGrid,
            parent=self.designerGroup,
        )
        self.snapCard = SwitchSettingCard(
            FIF.PIN, tr("吸附网格"),
            tr("移动控件时自动吸附到网格"),
            configItem=cfg.snapToGrid,
            parent=self.designerGroup,
        )

        self.designerGroup.addSettingCard(self.gridCard)
        self.designerGroup.addSettingCard(self.snapCard)

        # serial defaults
        self.serialGroup = SettingCardGroup(tr("串口默认设置"), self._container)

        self.baudCard = ComboBoxSettingCard(
            cfg.defaultBaudRate, FIF.SPEED_HIGH, tr("默认波特率"),
            tr("新项目的默认串口波特率"),
            texts=["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"],
            parent=self.serialGroup,
        )
        self.serialGroup.addSettingCard(self.baudCard)

        # about
        self.aboutGroup = SettingCardGroup(tr("关于"), self._container)
        self.aboutCard = PrimaryPushSettingCard(
            tr("检查更新"), FIF.INFO, "PyQt UI Designer",
            tr("版本 %1  •  面向硬件工程师的可视化上位机设计工具", APP_VERSION),
            parent=self.aboutGroup,
        )
        self.aboutCard.clicked.connect(self._check_update)
        self.aboutGroup.addSettingCard(self.aboutCard)

        self._layout.addWidget(self.personalGroup)
        self._layout.addWidget(self.designerGroup)
        self._layout.addWidget(self.serialGroup)
        self._layout.addWidget(self.aboutGroup)

        self._update_thread = None
        self._update_connections = SignalConnections(self)

    def _on_theme_changed(self, ci):
        setTheme(cfg.get(ci))

    def _on_language_changed(self, _index):
        # The card saves the setting; the interface keeps its language until the restart.
        InfoBar.success(tr("语言已更改"), tr("重启软件后生效"), parent=self,
                        duration=3000, position=InfoBarPosition.TOP)

    def _check_update(self):
        if self._update_thread and self._update_thread.isRunning():
            return
        if self._update_thread is not None:
            self._finish_update_check(self._update_thread)
        self.aboutCard.button.setEnabled(False)
        self.aboutCard.button.setText(tr("检查中…"))
        thread = self._update_thread = UpdateCheckThread(APP_VERSION, self)
        self._update_connections.connect(thread.result, self._on_update_result)
        self._update_connections.connect(
            thread.finished, lambda: self._finish_update_check(thread))
        thread.start()

    def _finish_update_check(self, thread):
        if self._update_thread is thread:
            self._update_thread = None
            self._update_connections.clear()
            thread.deleteLater()

    def shutdown_update_check(self):
        """Finish blocking network I/O before deleting its parent widget."""
        self._update_connections.clear()
        thread, self._update_thread = self._update_thread, None
        if thread is not None:
            thread.requestInterruption()
            thread.wait()
            thread.deleteLater()

    def _on_update_result(self, has_new, latest, current, url, changelog, error):
        self.aboutCard.button.setEnabled(True)
        self.aboutCard.button.setText(tr("检查更新"))

        if error:
            InfoBar.error(tr("检查更新失败"), error, parent=self,
                          duration=4000, position=InfoBarPosition.TOP)
            return

        if has_new:
            # The notes scroll inside the dialog, so even a long changelog leaves the buttons in view.
            if UpdateDialog(latest, current, changelog, self.window()).exec():
                QDesktopServices.openUrl(QUrl(url))
        else:
            InfoBar.success(tr("已是最新版本"),
                            tr("当前版本 v%1 已是最新", current),
                            parent=self, duration=3000,
                            position=InfoBarPosition.TOP)
