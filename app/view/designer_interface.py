# coding: utf-8
"""Designer interface — three-column layout with toolbar."""
import copy
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QMimeData, QPoint, QPointF, QRectF, QSignalBlocker, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QCursor, QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QFileDialog, QShortcut,
)
from qfluentwidgets import (
    CommandBar, Action, FluentIcon as FIF, InfoBar, InfoBarPosition,
    BodyLabel, LineEdit, RoundMenu, ToolButton, Theme, HorizontalSeparator,
    ToolTipFilter, ToolTipPosition,
)
from qfluentwidgets.common.icon import FluentIconBase

from app.designer.canvas import DesignScene, DesignView
from app.designer.canvas_item import CanvasItem
from app.designer.clipboard import (
    CLIPBOARD_MIME, assign_ids, clipboard_text, container_positions, copied_items, image_base,
    pasted_widgets, top_level_offset,
)
from app.designer.history import DesignHistory
from app.designer.palette import WidgetPalette
from app.designer.property_editor import PropertyEditor
from app.designer import selection_manager as sel
from app.common.config import cfg
from app.common.icon import WidgetIcon
from app.common.signal_bus import signalBus
from app.core.project import ProjectManager, rebased_asset_path
from app.core.signal_lifetime import SignalConnections

_DEFAULT_ICON = Path(__file__).resolve().parent.parent.parent / "logo.png"
_REDO_KEYS = ("Ctrl+Shift+Z",) if sys.platform == "darwin" else ("Ctrl+Y", "Ctrl+Shift+Z")


class _MirroredIcon(FluentIconBase):
    """A Fluent icon turned left to right: 重做 is 撤销's arrow pointing the other way."""

    def __init__(self, icon):
        self._icon = icon

    def path(self, theme=Theme.AUTO):
        return self._icon.path(theme)

    def render(self, painter, rect, theme=Theme.AUTO, indexes=None, **attributes):
        rect = QRectF(rect)
        painter.save()
        painter.translate(rect.left() + rect.right(), 0)
        painter.scale(-1, 1)
        self._icon.render(painter, rect, theme, indexes, **attributes)
        painter.restore()


class DesignerInterface(QWidget):
    """Main designer page combining palette, canvas, and property editor."""

    historyChanged = pyqtSignal()  # undo or redo became (un)available, or the saved state was reached or left
    # The toolbar's file buttons; the main window owns the project.
    newRequested = pyqtSignal()
    openRequested = pyqtSignal()
    saveRequested = pyqtSignal()
    saveAsRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("designerInterface")
        self._project_source = None
        self._history = DesignHistory()
        self._history_base = Path.cwd()  # the folder the history's relative image paths start from
        self._merge_key = None  # the property panel field behind the change about to be recorded
        self._paste_key, self._paste_count = None, 0
        # Record once an action is over: a drop into a container signals before the container adopts the widget.
        self._record_timer = QTimer(self)
        self._record_timer.setSingleShot(True)
        self._record_timer.setInterval(0)
        self._record_timer.timeout.connect(self._record)
        self._init_ui()
        self._add_shortcuts()

        self._external_connections = SignalConnections(self)
        self._external_connections.connect(signalBus.canvasChanged, self._record_timer.start)
        self._external_connections.connect(cfg.showGrid.valueChanged, self._on_grid_setting)
        for replaced in (signalBus.projectNew, signalBus.projectLoaded):
            self._external_connections.connect(replaced, self._on_project_replaced)
        self._external_connections.connect(self._scene.selectionChanged, self._update_actions)
        self._prop_editor.edited.connect(self._on_field_edited)
        self._update_actions()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # toolbar row: CommandBar + app icon and name input
        toolbar_row = QHBoxLayout()
        toolbar_row.setContentsMargins(0, 0, 8, 0)
        toolbar_row.setSpacing(6)
        self._toolbar = self._create_toolbar()
        toolbar_row.addWidget(self._toolbar, 1)

        self._icon_button = ToolButton()
        self._icon_button.setFixedSize(32, 32)
        self._icon_button.setIconSize(QSize(20, 20))
        self._icon_button.setToolTip("应用图标")
        self._icon_button.installEventFilter(ToolTipFilter(self._icon_button, 300, ToolTipPosition.TOP))
        self._icon_button.clicked.connect(self._show_icon_menu)
        toolbar_row.addWidget(self._icon_button)

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
        layout.addWidget(HorizontalSeparator())

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
        self._update_icon_button()

    def _create_toolbar(self) -> CommandBar:
        # The same buttons in the same order as FluentHMI Studio's; icons only, the tooltip names each and its keys.
        bar = CommandBar(self)
        bar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        bar.setButtonTight(True)

        def add(icon, text, slot, key=None):
            action = Action(icon, text, triggered=slot)
            action.setToolTip(f"{text} ({QKeySequence(key).toString(QKeySequence.NativeText)})" if key else text)
            bar.addAction(action)
            return action

        # The side panels' switches sit at the two ends of the bar; the canvas takes a hidden panel's room.
        self._palette_action = add(WidgetIcon.PANEL_LEFT_ON, "隐藏控件库", lambda: self._toggle_panel(
            self._palette, self._palette_action, "控件库", WidgetIcon.PANEL_LEFT, WidgetIcon.PANEL_LEFT_ON))
        bar.addSeparator()
        add(FIF.ADD, "新建", self.newRequested.emit, QKeySequence.New)
        add(FIF.FOLDER, "打开", self.openRequested.emit, QKeySequence.Open)
        add(FIF.SAVE, "保存", self.saveRequested.emit, QKeySequence.Save)
        add(FIF.SAVE_AS, "另存为", self.saveAsRequested.emit, QKeySequence.SaveAs)
        bar.addSeparator()
        self._undo_action = add(FIF.CANCEL, "撤销", self.undo, QKeySequence.Undo)
        self._redo_action = add(_MirroredIcon(FIF.CANCEL), "重做", self.redo, _REDO_KEYS[0])
        bar.addSeparator()
        self._copy_action = add(FIF.COPY, "复制", self.copy_selection, QKeySequence.Copy)
        self._paste_action = add(FIF.PASTE, "粘贴", self.paste, QKeySequence.Paste)
        add(FIF.DELETE, "删除", self._delete_selected)
        bar.addSeparator()
        menu = self._align_menu = RoundMenu(parent=self)
        for text, align in (("左对齐", sel.align_left), ("右对齐", sel.align_right),
                            ("顶对齐", sel.align_top), ("底对齐", sel.align_bottom),
                            ("水平居中", sel.align_horizontal_center), ("垂直居中", sel.align_vertical_center),
                            ("横向等距分布", sel.distribute_horizontal), ("纵向等距分布", sel.distribute_vertical)):
            menu.addAction(Action(text, triggered=lambda _=False, align=align: align(self._scene)))
        add(FIF.ALIGNMENT, "对齐", lambda: menu.exec(QCursor.pos()))
        bar.addSeparator()
        # The same switch as 设置 › 显示网格.
        self._grid_action = add(FIF.TILES, "网格", lambda: None)
        self._grid_action.setCheckable(True)
        self._grid_action.setChecked(cfg.get(cfg.showGrid))
        self._grid_action.toggled.connect(lambda shown: cfg.set(cfg.showGrid, shown))
        add(FIF.ZOOM_IN, "放大", lambda: self._view.zoom_by(1.15), QKeySequence.ZoomIn)
        add(FIF.ZOOM_OUT, "缩小", lambda: self._view.zoom_by(1 / 1.15), QKeySequence.ZoomOut)
        add(FIF.FIT_PAGE, "适应窗口", lambda: self._view.fit_canvas(), "Ctrl+0")
        add(FIF.ZOOM, "实际大小", lambda: self._view.reset_zoom())
        bar.addSeparator()
        self._properties_action = add(WidgetIcon.PANEL_RIGHT_ON, "隐藏属性", lambda: self._toggle_panel(
            self._prop_editor, self._properties_action, "属性", WidgetIcon.PANEL_RIGHT, WidgetIcon.PANEL_RIGHT_ON))

        return bar

    @staticmethod
    def _toggle_panel(panel, action, title, hidden_icon, shown_icon):
        shown = panel.isHidden()
        panel.setVisible(shown)
        action.setIcon(shown_icon if shown else hidden_icon)
        action.setText(("隐藏" if shown else "显示") + title)
        action.setToolTip(action.text())

    def _on_grid_setting(self, shown):
        self._grid_action.setChecked(shown)
        self._scene.set_show_grid(shown)

    def _add_shortcuts(self):
        # Active while this page shows; a focused text field takes these keys for its own undo, copy and paste.
        for keys, slot in (((QKeySequence.Undo,), self.undo), (_REDO_KEYS, self.redo),
                           ((QKeySequence.Copy,), self.copy_selection), ((QKeySequence.Paste,), self.paste),
                           ((QKeySequence.ZoomIn,), lambda: self._view.zoom_by(1.15)),
                           ((QKeySequence.ZoomOut,), lambda: self._view.zoom_by(1 / 1.15)),
                           (("Ctrl+0",), lambda: self._view.fit_canvas())):
            for key in keys:
                QShortcut(QKeySequence(key), self, slot)

    def _delete_selected(self):
        for item in self._scene.selectedItems():
            if isinstance(item, CanvasItem):
                self._scene.remove_canvas_item(item)

    def populate_palette(self):
        self._palette.populate()

    def set_project_source(self, source):
        """Where the designer finds the open project: for the property panel's 默认帧格式 and the app icon."""
        self._project_source = source
        self._prop_editor.set_project_source(source)
        self._on_project_replaced()

    def _project(self):
        return self._project_source() if self._project_source is not None else None

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

    def on_theme_changed(self):
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

    # ------------------------------------------------------------------
    # App icon
    # ------------------------------------------------------------------

    def _update_icon_button(self):
        project = self._project()
        icon = QIcon(project.icon_file()) if project is not None and project.icon else QIcon()
        self._icon_button.setIcon(icon if not icon.isNull() else QIcon(str(_DEFAULT_ICON)))

    def _show_icon_menu(self):
        project = self._project()
        if project is None:
            return
        menu = RoundMenu(parent=self)
        menu.addAction(Action("选择图标…", triggered=self._choose_icon))
        default = Action("使用默认图标", triggered=lambda: self._set_icon(""))
        default.setEnabled(bool(project.icon))
        menu.addAction(default)
        menu.exec(self._icon_button.mapToGlobal(QPoint(0, self._icon_button.height())))

    def _choose_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择应用图标", "", "图片 (*.png *.jpg *.jpeg *.ico)")
        if path:
            self._set_icon(path)

    def _set_icon(self, path):
        project = self._project()
        if project is None or project.icon == path:
            return
        project.icon = path
        self._update_icon_button()
        signalBus.canvasChanged.emit()

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------

    def _document(self):
        """The design as Save writes it, as the undo history keeps it."""
        project = self._project()
        rect = self._scene.sceneRect()
        return copy.deepcopy({
            "appName": self.app_name,
            "canvas": {"width": int(rect.width()), "height": int(rect.height()),
                       "gridSize": self._scene.grid_size},
            "widgets": [item.to_dict() for item in self._scene.top_level_canvas_items()],
            "serial": project.serial if project is not None else {},
            "icon": project.icon if project is not None else "",
        })

    def _on_field_edited(self, key):
        self._merge_key = key

    def _record(self):
        self._record_timer.stop()
        key, self._merge_key = self._merge_key, None
        if self._history.record(self._document(), key):
            self._history_changed()

    def _history_changed(self):
        self._update_actions()
        self.historyChanged.emit()

    def is_saved_state(self) -> bool:
        """Whether the design is as last saved or opened, by the undo history."""
        return self._history.is_clean()

    def _on_project_replaced(self, *_args):
        project = self._project()
        if project is not None:
            self.app_name = project.app_name
            self.canvas_size = (project.canvas_width, project.canvas_height)
        self._update_icon_button()
        self._record_timer.stop()
        self._merge_key = None
        self._paste_key = None
        self._history.reset(self._document())
        self._history_base = project.base_dir() if project is not None else Path.cwd()
        self._history_changed()
        self._view.fit_canvas_soon()  # a canvas larger than the view opens whole, not cut off

    def mark_saved(self, path):
        """The design as just saved to ``path`` is the one without the unsaved mark."""
        base = Path(path).expanduser().resolve().parent
        if base != self._history_base:
            # Saving elsewhere rebased the relative image paths; earlier states must name the same files.
            for state in self._history.states():
                ProjectManager._rebase_image_paths(state["widgets"], self._history_base, base)
                state["icon"] = rebased_asset_path(state["icon"], self._history_base, base)
            self._history_base = base
        self._record()  # what saving committed, such as tab names still being typed
        self._history.mark_saved()
        self._update_icon_button()
        self._history_changed()

    def undo(self):
        self._step(self._history.undo)

    def redo(self):
        self._step(self._history.redo)

    def _step(self, move):
        self._prop_editor.commit_pending_edits()
        self._record()  # a change not yet recorded is the first one an undo takes back
        state = move()
        if state is not None:
            self._restore(state)
        self._history_changed()

    def _restore(self, document):
        """Rebuild the canvas and the project settings from ``document``, keeping the selection by id."""
        document = copy.deepcopy(document)
        scene = self._scene
        selected = [it.widget_id for it in scene.selectedItems() if isinstance(it, CanvasItem)]
        base = getattr(scene, "_asset_base_dir", None)
        canvas = document["canvas"]
        with QSignalBlocker(signalBus):
            scene.clearSelection()
            for item in scene.top_level_canvas_items():
                scene.removeItem(item)
            scene.set_canvas_size(canvas["width"], canvas["height"])
            scene.set_grid_size(canvas["gridSize"])
            for data in document["widgets"]:
                scene.add_canvas_item(CanvasItem.from_dict(data, asset_base_dir=base))
            self.app_name = document["appName"]
            self.canvas_size = (canvas["width"], canvas["height"])
            project = self._project()
            if project is not None:
                project.serial = document["serial"]
                project.icon = document["icon"]
            self._update_icon_button()
            for wid in selected:
                item = scene.get_item_by_id(wid)
                if item is not None:
                    item.setSelected(True)
        self._record_timer.stop()
        self._merge_key = None
        self._history.replace_current(self._document())
        self._view._on_selection_changed()  # the property panel shows the restored widget or project
        signalBus.canvasChanged.emit()  # the preview and the title take an undo like any other change

    # ------------------------------------------------------------------
    # Copy / paste
    # ------------------------------------------------------------------

    def _update_actions(self):
        self._undo_action.setEnabled(self._history.can_undo())
        self._redo_action.setEnabled(self._history.can_redo())
        self._copy_action.setEnabled(
            any(isinstance(it, CanvasItem) for it in self._scene.selectedItems()))

    def copy_selection(self):
        items = copied_items(self._scene)
        if not items:
            return
        text = clipboard_text(items, image_base(self._scene))
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME, text.encode("utf-8"))
        mime.setText(text)
        QApplication.clipboard().setMimeData(mime)

    def _paste_target(self):
        """The container a paste goes into: the one selected widget, when it can hold others."""
        selected = [it for it in self._scene.selectedItems() if isinstance(it, CanvasItem)]
        return selected[0] if len(selected) == 1 and selected[0].is_container() else None

    @staticmethod
    def _paste_area(container):
        """Where pasted widgets go in ``container``, in its coordinates: a tab widget's current page."""
        if container.type_name == "TabWidget":
            page = container._inner_widget.currentWidget()
            if page is not None:
                corner = page.mapTo(container._inner_widget, QPoint())
                return corner.x(), corner.y(), page.width(), page.height()
        rect = container.rect()
        return 0, 0, rect.width(), rect.height()

    def paste(self):
        project = self._project()
        found = pasted_widgets(QApplication.clipboard().mimeData(),
                               project.serial if project is not None else {})
        items = []
        if found is not None:
            text, widgets = found
            assign_ids(widgets, {it.widget_id for it in self._scene.all_canvas_items()})
            base = getattr(self._scene, "_asset_base_dir", None)
            try:
                items = [CanvasItem.from_dict(data, asset_base_dir=base) for data in widgets]
            except Exception:  # values opening would also choke on; nothing is added
                items = []
        if not items:
            InfoBar.warning("提示", "剪贴板里没有可粘贴的控件",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        target = self._paste_target()
        key = (text, target.widget_id if target is not None else None)
        self._paste_count = self._paste_count + 1 if key == self._paste_key else 1
        self._paste_key = key
        step = self._scene.grid_size * self._paste_count
        if target is None:
            canvas = self._scene.sceneRect()
            dx, dy = top_level_offset(widgets, step, canvas.width(), canvas.height())
            positions = [(item.pos().x() + dx, item.pos().y() + dy) for item in items]
        else:
            positions = container_positions(widgets, step, self._paste_area(target))

        self._scene.clearSelection()
        for item, (x, y) in zip(items, positions):
            item.setPos(x, y)
            self._scene.add_canvas_item(item)
            if target is not None:
                target.add_child(item, local_pos=QPointF(x, y))
            item.setSelected(True)
