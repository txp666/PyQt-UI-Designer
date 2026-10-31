# coding: utf-8
"""Designer interface — three-column layout with toolbar."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QFrame,
)
from qfluentwidgets import (
    CommandBar, Action, FluentIcon as FIF, InfoBar, InfoBarPosition,
    BodyLabel, LineEdit,
)

from qfluentwidgets import isDarkTheme

from app.designer.canvas import DesignScene, DesignView
from app.designer.palette import WidgetPalette
from app.designer.property_editor import PropertyEditor
from app.designer import selection_manager as sel
from app.common.signal_bus import signalBus


class DesignerInterface(QWidget):
    """Main designer page combining palette, canvas, and property editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("designerInterface")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # toolbar row: CommandBar + app name input
        toolbar_row = QHBoxLayout()
        toolbar_row.setContentsMargins(0, 0, 8, 0)
        toolbar_row.setSpacing(6)
        self._toolbar = self._create_toolbar()
        toolbar_row.addWidget(self._toolbar, 1)

        lbl_name = BodyLabel("名称:")
        self._app_name_edit = LineEdit()
        self._app_name_edit.setText("上位机")
        self._app_name_edit.setPlaceholderText("上位机名称")
        self._app_name_edit.setFixedWidth(120)
        self._app_name_edit.editingFinished.connect(self._on_app_name_changed)
        toolbar_row.addWidget(lbl_name)
        toolbar_row.addWidget(self._app_name_edit)

        lbl_w = BodyLabel("宽:")
        self._canvas_w_edit = LineEdit()
        self._canvas_w_edit.setText("1200")
        self._canvas_w_edit.setFixedWidth(60)
        self._canvas_w_edit.editingFinished.connect(self._on_canvas_size_changed)
        lbl_h = BodyLabel("高:")
        self._canvas_h_edit = LineEdit()
        self._canvas_h_edit.setText("800")
        self._canvas_h_edit.setFixedWidth(60)
        self._canvas_h_edit.editingFinished.connect(self._on_canvas_size_changed)
        toolbar_row.addWidget(lbl_w)
        toolbar_row.addWidget(self._canvas_w_edit)
        toolbar_row.addWidget(lbl_h)
        toolbar_row.addWidget(self._canvas_h_edit)

        layout.addLayout(toolbar_row)

        # separator
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.HLine)
        self._update_separator_style()
        layout.addWidget(self._sep)

        # three-column splitter
        splitter = QSplitter(Qt.Horizontal)

        self._palette = WidgetPalette()
        self._scene = DesignScene()
        self._view = DesignView(self._scene)
        self._prop_editor = PropertyEditor()
        self._prop_editor.set_scene(self._scene)

        splitter.addWidget(self._palette)
        splitter.addWidget(self._view)
        splitter.addWidget(self._prop_editor)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([220, 700, 280])

        layout.addWidget(splitter, 1)

    def _create_toolbar(self) -> CommandBar:
        bar = CommandBar(self)
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        bar.addAction(Action(FIF.ALIGNMENT, "左对齐", triggered=lambda: sel.align_left(self._scene)))
        bar.addAction(Action(FIF.RIGHT_ARROW, "右对齐", triggered=lambda: sel.align_right(self._scene)))
        bar.addAction(Action(FIF.UP, "顶对齐", triggered=lambda: sel.align_top(self._scene)))
        bar.addAction(Action(FIF.DOWN, "底对齐", triggered=lambda: sel.align_bottom(self._scene)))
        bar.addSeparator()
        bar.addAction(Action(FIF.ALIGNMENT, "横向分布", triggered=lambda: sel.distribute_horizontal(self._scene)))
        bar.addAction(Action(FIF.MENU, "纵向分布", triggered=lambda: sel.distribute_vertical(self._scene)))
        bar.addSeparator()
        bar.addAction(Action(FIF.DELETE, "删除", triggered=self._delete_selected))
        bar.addSeparator()
        bar.addAction(Action(FIF.ZOOM_IN, "放大", triggered=lambda: self._zoom(1.25)))
        bar.addAction(Action(FIF.ZOOM_OUT, "缩小", triggered=lambda: self._zoom(0.8)))

        return bar

    def _delete_selected(self):
        for item in self._scene.selectedItems():
            from app.designer.canvas_item import CanvasItem
            if isinstance(item, CanvasItem):
                self._scene.remove_canvas_item(item)

    def _zoom(self, factor: float):
        self._view.scale(factor, factor)

    def populate_palette(self):
        self._palette.populate()

    def set_project_source(self, source):
        """Where the property panel finds the open project, for its 默认帧格式 section."""
        self._prop_editor.set_project_source(source)

    @property
    def scene(self) -> DesignScene:
        return self._scene

    @property
    def app_name(self) -> str:
        return self._app_name_edit.text().strip() or "上位机"

    @app_name.setter
    def app_name(self, value: str):
        self._app_name_edit.setText(value or "上位机")

    def _on_app_name_changed(self):
        signalBus.canvasChanged.emit()

    def _update_separator_style(self):
        color = "#444" if isDarkTheme() else "#e0e0e0"
        self._sep.setStyleSheet(f"background: {color}; max-height: 1px;")

    def on_theme_changed(self):
        self._update_separator_style()
        self._view._apply_view_style()
        self._scene.refresh_all_widgets()
        self._palette.refresh_icons()

    def _on_canvas_size_changed(self):
        try:
            w = int(self._canvas_w_edit.text())
            h = int(self._canvas_h_edit.text())
        except ValueError:
            return
        w = max(200, min(w, 9999))
        h = max(200, min(h, 9999))
        self._scene.set_canvas_size(w, h)
        signalBus.canvasChanged.emit()

    @property
    def canvas_size(self) -> tuple:
        try:
            w = int(self._canvas_w_edit.text())
            h = int(self._canvas_h_edit.text())
        except ValueError:
            w, h = 1200, 800
        return w, h

    @canvas_size.setter
    def canvas_size(self, size: tuple):
        w, h = size
        self._canvas_w_edit.setText(str(int(w)))
        self._canvas_h_edit.setText(str(int(h)))
