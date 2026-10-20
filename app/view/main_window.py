# coding: utf-8
"""Main application window using FluentWindow with navigation."""
from pathlib import Path

from PyQt5.QtCore import QSize, Qt, QSignalBlocker
from PyQt5.QtGui import QIcon, QColor, QKeySequence
from PyQt5.QtWidgets import QApplication, QFileDialog, QShortcut, QMessageBox

from qfluentwidgets import (
    NavigationItemPosition, FluentWindow, SplashScreen,
    FluentIcon as FIF, InfoBar, InfoBarPosition, MessageBox, qconfig,
)

from app.common.config import cfg, APP_NAME, isWin11
from app.common.signal_bus import signalBus
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

        self.preview_interface = PreviewInterface(self)
        self.setting_interface = SettingInterface(self)

    def _connect_signals(self):
        self._external_connections = SignalConnections(self)
        self._external_connections.connect(
            signalBus.micaEnableChanged, self.setMicaEffectEnabled)
        self._external_connections.connect(
            signalBus.canvasChanged, self._on_canvas_changed)
        self._external_connections.connect(
            qconfig.themeChangedFinished, self._on_theme_changed)
        self.stackedWidget.currentChanged.connect(self._on_page_changed)
        self.preview_interface.projectDataRequested.connect(self._sync_preview)

        QShortcut(QKeySequence.Save, self, self._save_project)
        QShortcut(QKeySequence.New, self, self._new_project)
        QShortcut(QKeySequence.Open, self, self._open_project)
        QShortcut(QKeySequence("Ctrl+Shift+E"), self, self._export_code)

    def _on_canvas_changed(self):
        self._project_mgr.mark_dirty()
        if hasattr(self, "preview_interface"):
            self.preview_interface.invalidate_project("设计已更改，请重新运行预览")
        self._update_title()

    def _on_theme_changed(self):
        self.designer_interface.on_theme_changed()
        self.preview_interface.on_theme_changed()

    def _init_navigation(self):
        self.addSubInterface(
            self.designer_interface, FIF.EDIT, "设计器",
            NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.preview_interface, FIF.PLAY, "预览运行",
            NavigationItemPosition.TOP,
        )

        self.navigationInterface.addSeparator()

        # project actions in navigation
        self.navigationInterface.addItem(
            "nav_new", FIF.ADD, "新建项目",
            onClick=lambda: self._new_project(),
            position=NavigationItemPosition.BOTTOM,
        )
        self.navigationInterface.addItem(
            "nav_open", FIF.FOLDER, "打开项目",
            onClick=lambda: self._open_project(),
            position=NavigationItemPosition.BOTTOM,
        )
        self.navigationInterface.addItem(
            "nav_save", FIF.SAVE, "保存项目",
            onClick=lambda: self._save_project(),
            position=NavigationItemPosition.BOTTOM,
        )
        self.navigationInterface.addItem(
            "nav_export", FIF.CODE, "导出代码",
            onClick=lambda: self._export_code(),
            position=NavigationItemPosition.BOTTOM,
        )

        self.addSubInterface(
            self.setting_interface, FIF.SETTING, "设置",
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
        path = self._project_mgr.current.file_path
        dirty = " •" if self._project_mgr.is_dirty else ""
        name = path.split("/")[-1].split("\\")[-1] if path else "未保存项目"
        self.setWindowTitle(f"{name}{dirty} — {APP_NAME}")

    # --- Project operations ---

    def _confirm_unsaved_changes(self):
        if not self._project_mgr.is_dirty:
            return True
        choice = QMessageBox.question(
            self, "保存项目", "当前项目有未保存的修改，是否保存？",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if choice == QMessageBox.Save:
            return self._save_project()
        return choice == QMessageBox.Discard

    def _new_project(self):
        if not self._confirm_unsaved_changes():
            return
        with QSignalBlocker(signalBus):
            self.designer_interface.scene.clear_all()
            self.designer_interface.scene.set_canvas_size(1200, 800)
            self.designer_interface.scene.set_grid_size(10)
            self.designer_interface.app_name = "上位机"
            self.designer_interface.canvas_size = (1200, 800)
        self._project_mgr.new_project()
        if hasattr(self, "preview_interface"):
            self.preview_interface.invalidate_project(disconnect=True)
            self.preview_interface.set_project_data(self._project_mgr.current)
        signalBus.widgetDeselected.emit()
        self._update_title()
        InfoBar.success("成功", "已新建项目", parent=self, position=InfoBarPosition.TOP, duration=2000)

    def _open_project(self):
        if not self._confirm_unsaved_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "打开项目", "", "UI Designer Project (*.uidp);;All Files (*)"
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
            InfoBar.success("成功", f"已加载: {path}", parent=self, position=InfoBarPosition.TOP, duration=2000)
        except Exception as e:
            InfoBar.error("错误", f"加载失败: {e}", parent=self, position=InfoBarPosition.TOP, duration=5000)

    def _save_project(self):
        path = self._project_mgr.current.file_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "保存项目", "project.uidp",
                "UI Designer Project (*.uidp);;All Files (*)"
            )
        if not path:
            return False
        try:
            self._project_mgr.save_from_scene(self.designer_interface.scene, path, self.designer_interface.app_name)
            self._update_title()
            InfoBar.success("成功", f"已保存: {path}", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return True
        except Exception as e:
            InfoBar.error("错误", f"保存失败: {e}", parent=self, position=InfoBarPosition.TOP, duration=5000)
            return False

    def _export_code(self):
        directory = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not directory:
            return
        try:
            from app.core.code_generator import generate_project
            data = self._project_mgr.export_scene_data(self.designer_interface.scene, self.designer_interface.app_name)
            generate_project(data, directory)
            InfoBar.success(
                "导出成功", f"代码已导出到: {directory}",
                parent=self, position=InfoBarPosition.TOP, duration=3000,
            )
        except Exception as e:
            InfoBar.error(
                "导出失败", str(e),
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
