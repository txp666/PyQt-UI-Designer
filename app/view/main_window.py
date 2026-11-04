# coding: utf-8
"""Main application window using FluentWindow with navigation."""
from pathlib import Path

from PyQt5.QtCore import QSize, Qt, QSignalBlocker
from PyQt5.QtGui import QIcon, QColor, QKeySequence
from PyQt5.QtWidgets import QApplication, QFileDialog, QShortcut

from qfluentwidgets import (
    NavigationItemPosition, FluentWindow, SplashScreen,
    FluentIcon as FIF, InfoBar, InfoBarPosition, MessageBox, PushButton, qconfig,
)

from app.common.config import cfg, APP_NAME, isWin11
from app.common.signal_bus import signalBus
from app.core.i18n import tr
from app.core.project import ProjectManager
from app.core.qt_window_lifetime import TitleBarLifecycleMixin
from app.core.signal_lifetime import SignalConnections
from app.view.designer_interface import DesignerInterface
from app.view.preview_interface import PreviewInterface
from app.view.setting_interface import SettingInterface

from app.widgets.basic import register_basic_widgets
from app.widgets.layout import register_layout_widgets
from app.widgets.display import register_display_widgets
from app.widgets.chart import register_chart_widgets
from app.widgets.comm import register_comm_widgets
from app.widgets.composite import register_composite_widgets


def _project_name(path):
    """The project's file name, as the title bar shows it."""
    return path.split("/")[-1].split("\\")[-1] if path else tr("未保存项目")


class MainWindow(TitleBarLifecycleMixin, FluentWindow):

    def __init__(self):
        super().__init__()

        register_basic_widgets()
        register_layout_widgets()
        register_display_widgets()
        register_chart_widgets()
        register_comm_widgets()
        register_composite_widgets()

        self._project_mgr = ProjectManager()
        self._init_window()
        self._create_interfaces()
        self._connect_signals()
        self._init_navigation()


    def _create_interfaces(self):
        self.designer_interface = DesignerInterface(self)
        self.designer_interface.populate_palette()
        # A save replaces the project object, so the panel asks for the current one each time.
        self.designer_interface.set_project_source(lambda: self._project_mgr.current)

        self.preview_interface = PreviewInterface(self)
        self.preview_interface.set_mica_enabled(self.isMicaEffectEnabled())
        self.setting_interface = SettingInterface(self)

    def _connect_signals(self):
        self._external_connections = SignalConnections(self)
        self._external_connections.connect(
            signalBus.micaEnableChanged, self.setMicaEffectEnabled)
        self._external_connections.connect(
            signalBus.micaEnableChanged, self._on_mica_changed)
        self._external_connections.connect(
            signalBus.canvasChanged, self._on_canvas_changed)
        self._external_connections.connect(
            qconfig.themeChangedFinished, self._on_theme_changed)
        self.stackedWidget.currentChanged.connect(self._on_page_changed)
        self.preview_interface.projectDataRequested.connect(self._sync_preview)
        self.designer_interface.newRequested.connect(self._new_project)
        self.designer_interface.openRequested.connect(self._open_project)
        self.designer_interface.saveRequested.connect(self._save_project)
        self.designer_interface.saveAsRequested.connect(self._save_project_as)
        self.designer_interface.historyChanged.connect(self._on_history_changed)

        QShortcut(QKeySequence.Save, self, self._save_project)
        QShortcut(QKeySequence.SaveAs, self, self._save_project_as)
        QShortcut(QKeySequence.New, self, self._new_project)
        QShortcut(QKeySequence.Open, self, self._open_project)
        QShortcut(QKeySequence("Ctrl+Shift+E"), self, self._export_code)

    def _on_canvas_changed(self):
        self._project_mgr.mark_dirty()
        if hasattr(self, "preview_interface"):
            self.preview_interface.invalidate_project(tr("设计已更改，请重新运行预览"))
        self._update_title()

    def _on_history_changed(self):
        # Undoing back to the saved design clears the unsaved mark; redoing away from it sets it again.
        self._project_mgr.set_dirty(not self.designer_interface.is_saved_state())
        self._update_title()

    def _on_theme_changed(self):
        self.designer_interface.on_theme_changed()
        self.preview_interface.on_theme_changed()

    def _on_mica_changed(self, _enabled):
        self.preview_interface.set_mica_enabled(self.isMicaEffectEnabled())

    def _init_navigation(self):
        self.addSubInterface(
            self.designer_interface, FIF.EDIT, tr("设计器"),
            NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.preview_interface, FIF.PLAY, tr("预览运行"),
            NavigationItemPosition.TOP,
        )

        self.navigationInterface.addSeparator()

        # 新建、打开、保存 are on the designer toolbar
        self.navigationInterface.addItem(
            "nav_export", FIF.CODE, tr("导出代码"),
            onClick=lambda: self._export_code(),
            position=NavigationItemPosition.BOTTOM,
        )

        self.addSubInterface(
            self.setting_interface, FIF.SETTING, tr("设置"),
            NavigationItemPosition.BOTTOM,
        )

        self.splashScreen.finish()

    def _init_window(self):
        self.resize(1500, 900)
        self.setMinimumSize(1000, 600)
        self.setWindowTitle(APP_NAME)

        _ico = Path(__file__).resolve().parent.parent.parent / "logo.png"
        if _ico.exists():
            self.setWindowIcon(QIcon(str(_ico)))

        self.setCustomBackgroundColor(QColor(240, 244, 249), QColor(32, 32, 32))
        self.setMicaEffectEnabled(isWin11() and cfg.get(cfg.micaEnabled))

        self.splashScreen = SplashScreen(self.windowIcon(), self)
        self.splashScreen.setIconSize(QSize(106, 106))
        self.splashScreen.raise_()

        desktop = QApplication.primaryScreen().availableGeometry()
        self.resize(min(self.width(), desktop.width()),
                    min(self.height(), desktop.height()))
        self.move(desktop.center() - self.rect().center())
        self.show()
        QApplication.processEvents()

    def _update_title(self):
        dirty = " •" if self._project_mgr.is_dirty else ""
        self.setWindowTitle(f"{_project_name(self._project_mgr.current.file_path)}{dirty} — {APP_NAME}")

    # --- Project operations ---

    def _confirm_unsaved_changes(self):
        """Whether the current project may be replaced or closed: Save saves it first (and fails if
        the save does), Don't Save drops the changes, Cancel and Esc keep everything as it is."""
        if not self._project_mgr.is_dirty:
            return True
        name = _project_name(self._project_mgr.current.file_path)
        box = MessageBox(tr("保存更改？"), tr("“%1”有未保存的更改。", name), self)
        box.yesButton.setText(tr("保存"))
        box.cancelButton.setText(tr("取消"))
        discard = PushButton(tr("不保存"), box.buttonGroup)
        # Stretch 1, like the box's own buttons, so the three share the row evenly.
        box.buttonLayout.insertWidget(1, discard, 1, Qt.AlignVCenter)
        discarded = []
        discard.clicked.connect(lambda: (discarded.append(True), box.reject()))
        saving = box.exec()
        box.deleteLater()
        if saving:
            return self._save_project()
        return bool(discarded)

    def _new_project(self):
        if not self._confirm_unsaved_changes():
            return
        with QSignalBlocker(signalBus):
            self.designer_interface.scene.clear_all()
            self.designer_interface.scene.set_canvas_size(1200, 800)
            self.designer_interface.scene.set_grid_size(10)
            self.designer_interface.app_name = tr("上位机")
            self.designer_interface.canvas_size = (1200, 800)
        self._project_mgr.new_project()
        if hasattr(self, "preview_interface"):
            self.preview_interface.invalidate_project(disconnect=True)
            self.preview_interface.set_project_data(self._project_mgr.current)
        signalBus.widgetDeselected.emit()
        self._update_title()
        InfoBar.success(tr("成功"), tr("已新建项目"), parent=self, position=InfoBarPosition.TOP, duration=2000)

    def _open_project(self):
        if not self._confirm_unsaved_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("打开项目"), "", "UI Designer Project (*.uidp);;All Files (*)"
        )
        if not path:
            return
        try:
            self._project_mgr.load_to_scene(self.designer_interface.scene, path)
            if hasattr(self, "preview_interface"):
                self.preview_interface.invalidate_project(disconnect=True)
                self.preview_interface.set_project_data(self._project_mgr.current)
            with QSignalBlocker(signalBus):
                self.designer_interface.app_name = self._project_mgr.current.app_name
                self.designer_interface.canvas_size = (
                    self._project_mgr.current.canvas_width,
                    self._project_mgr.current.canvas_height,
                )
            self._update_title()
            InfoBar.success(tr("成功"), tr("已加载: %1", path), parent=self, position=InfoBarPosition.TOP, duration=2000)
        except Exception as e:
            InfoBar.error(tr("错误"), tr("加载失败: %1", e), parent=self, position=InfoBarPosition.TOP, duration=5000)

    def _save_project_as(self):
        return self._save_project(choose_path=True)

    def _save_project(self, choose_path=False):
        path = self._project_mgr.current.file_path
        if choose_path or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("另存为") if choose_path else tr("保存项目"), path or "project.uidp",
                "UI Designer Project (*.uidp);;All Files (*)"
            )
        if not path:
            return False
        try:
            self._project_mgr.save_from_scene(self.designer_interface.scene, path, self.designer_interface.app_name)
            self.designer_interface.mark_saved(path)
            self._update_title()
            InfoBar.success(tr("成功"), tr("已保存: %1", path), parent=self, position=InfoBarPosition.TOP, duration=2000)
            return True
        except Exception as e:
            InfoBar.error(tr("错误"), tr("保存失败: %1", e), parent=self, position=InfoBarPosition.TOP, duration=5000)
            return False

    def _export_code(self):
        directory = QFileDialog.getExistingDirectory(self, tr("选择导出目录"))
        if not directory:
            return
        try:
            from app.core.code_generator import generate_project
            data = self._project_mgr.export_scene_data(self.designer_interface.scene, self.designer_interface.app_name)
            generate_project(data, directory)
            InfoBar.success(
                tr("导出成功"), tr("代码已导出到: %1", directory),
                parent=self, position=InfoBarPosition.TOP, duration=3000,
            )
        except Exception as e:
            InfoBar.error(
                tr("导出失败"), str(e),
                parent=self, position=InfoBarPosition.TOP, duration=5000,
            )

    def _sync_preview(self):
        """Push current design data to preview interface."""
        data = self._project_mgr.export_scene_data(self.designer_interface.scene, self.designer_interface.app_name)
        self.preview_interface.set_project_data(data)

    def _on_page_changed(self, index):
        """Sync preview data when switching to preview page."""
        if hasattr(self, 'preview_interface'):
            current = self.stackedWidget.currentWidget()
            if current is self.preview_interface:
                self._sync_preview()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "splashScreen"):
            self.splashScreen.resize(self.size())

    def closeEvent(self, event):
        if not self._confirm_unsaved_changes():
            event.ignore()
            return
        self.preview_interface._stop_preview()
        self.setting_interface.shutdown_update_check()
        super().closeEvent(event)
