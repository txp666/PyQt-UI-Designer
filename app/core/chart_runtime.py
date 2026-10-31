# coding: utf-8
"""Chart widgets: real-time line chart (pyqtgraph) and gauge meter."""
import csv
import json
import struct
from itertools import zip_longest
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel

from qfluentwidgets import (
    LineEdit as FluentLineEdit, PushButton as FluentPushButton,
    BodyLabel, isDarkTheme, qconfig, setCustomStyleSheet,
)


from .chart_history import ChartHistory
from .protocol_parser import RawFrameBuffer
from .binding_values import modbus_need, modbus_value
from .signal_lifetime import SignalConnections

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

_CURVE_COLORS = [
    (0, 120, 212), (244, 67, 54), (76, 175, 80), (255, 152, 0),
    (156, 39, 176), (0, 188, 212), (121, 85, 72), (96, 125, 139),
]

_DARK_CURVE_COLORS = [
    (74, 163, 223), (255, 112, 105), (129, 199, 132), (255, 183, 77),
    (206, 147, 216), (77, 208, 225), (188, 170, 164), (176, 190, 197),
]

_STRUCT_FMT = {
    "uint8": ("B", 1), "int8": ("b", 1),
    "uint16": ("H", 2), "int16": ("h", 2),
    "uint32": ("I", 4), "int32": ("i", 4),
    "float32": ("f", 4),
}


# ---------------------------------------------------------------------------
# Real-time line chart — multi-curve with built-in parsing
# ---------------------------------------------------------------------------

_DEFAULT_CURVE_CFG = {
    "name": "曲线1", "parseMode": "键值匹配",
    "key": "", "jsonPath": "",
    "byteOffset": 0, "dataType": "float32", "byteOrder": "大端(BE)",
    "frameHeader": "", "frameTail": "",
    "regIndex": 0, "mbDataType": "uint16", "mbRegOrder": "大端(AB CD)",
    "mbFcFilter": -1, "mbSlaveFilter": -1, "mbArea": "保持寄存器",
}

# Virtual prop name -> per-curve storage suffix
_CURVE_FIELD_MAP = {
    "curveName": "name", "curveParseMode": "parseMode",
    "curveKey": "key", "curveJsonPath": "jsonPath",
    "curveByteOffset": "byteOffset", "curveDataType": "dataType",
    "curveByteOrder": "byteOrder", "curveFrameHeader": "frameHeader",
    "curveFrameTail": "frameTail", "curveRegIndex": "regIndex",
    "curveMbDataType": "mbDataType", "curveMbRegOrder": "mbRegOrder",
    "curveMbFcFilter": "mbFcFilter", "curveMbSlaveFilter": "mbSlaveFilter",
    "curveMbArea": "mbArea",
}


class _HistoryObjectPairs(list):
    """Distinguish legacy JSON objects while preserving duplicate channel keys."""


def _history_json_channels(document):
    if isinstance(document, _HistoryObjectPairs):
        channels = list(document)
    elif isinstance(document, list):
        channels = []
        for entry in document:
            if not isinstance(entry, _HistoryObjectPairs):
                raise ValueError("曲线 JSON 通道必须包含 name 和 values")
            entry = dict(entry)
            if set(entry) != {"name", "values"}:
                raise ValueError("曲线 JSON 通道必须包含 name 和 values")
            channels.append((entry["name"], entry["values"]))
    else:
        raise ValueError("曲线 JSON 必须是对象或通道数组")
    for name, values in channels:
        if not isinstance(name, str) or not isinstance(values, list) or isinstance(values, _HistoryObjectPairs):
            raise ValueError("曲线 JSON 通道名称必须是文本，样本必须是数组")
    return channels


def build_cfgs_from_props(props: dict) -> list:
    """Build per-curve config list from flat ``_curve_{i}_{field}`` properties."""
    count = max(1, min(8, int(props.get("curveCount", 1))))
    cfgs = []
    for i in range(count):
        cfg = dict(_DEFAULT_CURVE_CFG)
        cfg["name"] = props.get(f"_curve_{i}_name", f"曲线{i + 1}")
        for field in _DEFAULT_CURVE_CFG:
            stored = props.get(f"_curve_{i}_{field}")
            if stored is not None:
                cfg[field] = stored
        cfgs.append(cfg)
    return cfgs


class RealtimeLineChart(QWidget):
    """Multi-curve scrolling real-time chart with right-side value table
    and draggable cursor. Each curve has independent parse configuration."""

    HISTORY_LIMIT = 10000
    REFRESH_MS = 33
    # the value table starts wide enough for these, so typical readings never resize the plot
    _SAMPLE_READING = "-0000.00"
    _SAMPLE_MODE = "游标: x=00000"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial_connections = SignalConnections(self)
        self._external_connections = SignalConnections(self)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(2)

        self._display_points = 200
        self._title = "实时曲线"
        self._cfgs: list = [dict(_DEFAULT_CURVE_CFG)]
        self._curves = []
        self._data: list = []
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(self.REFRESH_MS)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh_all)
        self.destroyed.connect(lambda _=None, histories=self._data: [h.close() for h in histories])
        # a loaded recording laid over the live curves: [(name, values)], their dashed curves and table rows
        self._refs: list = []
        self._ref_curves: list = []
        self._ref_labels: list = []
        self._listening = False
        self._cursor_mode = False

        # ---- main area: plot (left) + value table (right) ----
        main_h = QHBoxLayout()
        main_h.setSpacing(4)
        self._missing_label = None

        if HAS_PYQTGRAPH:
            self._plot = pg.PlotWidget()
            self._plot.showGrid(x=True, y=True, alpha=0.3)
            # One row across the top of the plot; clicking a curve's sample hides or shows that curve.
            self._legend = self._plot.addLegend(offset=None, labelTextSize="9pt")
            self._legend.anchor(itemPos=(0.5, 0), parentPos=(0.5, 0), offset=(0, 2))
            # The plot area gets its size after this widget does, so follow the view box itself.
            self._plot.getViewBox().sigResized.connect(self._fit_legend)
            main_h.addWidget(self._plot, 1)

            self._cursor_line = pg.InfiniteLine(
                angle=90, movable=True,
                pen=pg.mkPen(color=(255, 0, 0, 180), width=1, style=Qt.DashLine))
            self._cursor_line.setVisible(False)
            self._plot.addItem(self._cursor_line)
            self._external_connections.connect(
                self._cursor_line.sigPositionChanged, self._on_cursor_moved)
            self._external_connections.connect(
                self._plot.scene().sigMouseClicked, self._on_plot_clicked)
        else:
            self._missing_label = BodyLabel("需要安装 pyqtgraph")
            self._missing_label.setAlignment(Qt.AlignCenter)
            main_h.addWidget(self._missing_label, 1)
            self._plot = None
            self._legend = None
            self._cursor_line = None

        # right panel: mode label + value labels
        self._side = QWidget()
        right_panel = QVBoxLayout(self._side)
        right_panel.setContentsMargins(2, 0, 2, 0)
        right_panel.setSpacing(0)
        self._mode_label = QLabel("实时")
        self._mode_label.setAlignment(Qt.AlignCenter)
        right_panel.addWidget(self._mode_label)

        self._val_panel = QVBoxLayout()
        self._val_panel.setContentsMargins(0, 0, 0, 0)
        self._val_panel.setSpacing(0)
        right_panel.addLayout(self._val_panel)
        right_panel.addStretch()
        self._val_labels: list = []
        main_h.addWidget(self._side)

        self._root.addLayout(main_h, 1)

        # ---- toolbar ----
        tb = QHBoxLayout()
        tb.setContentsMargins(4, 2, 4, 0)
        tb.setSpacing(6)
        tb.addWidget(BodyLabel("显示点数"))
        self._disp_edit = FluentLineEdit()
        self._disp_edit.setText(str(self._display_points))
        self._disp_edit.setFixedWidth(80)
        self._disp_edit.editingFinished.connect(self._on_disp_changed)
        tb.addWidget(self._disp_edit)
        tb.addStretch()
        self._save_btn = FluentPushButton("保存")
        self._save_btn.setFixedWidth(64)
        self._save_btn.clicked.connect(self._save_data)
        tb.addWidget(self._save_btn)
        self._load_btn = FluentPushButton("加载")
        self._load_btn.setFixedWidth(64)
        self._load_btn.clicked.connect(self._load_data)
        tb.addWidget(self._load_btn)
        self._clear_ref_btn = FluentPushButton("清除对比")
        self._clear_ref_btn.clicked.connect(self.clear_reference)
        self._clear_ref_btn.hide()
        tb.addWidget(self._clear_ref_btn)
        self._root.addLayout(tb)

        self._rebuild_curves()
        self._external_connections.connect(qconfig.themeChangedFinished, self.apply_theme)

    # -- public configuration -------------------------------------------------

    @staticmethod
    def _curve_color(index):
        colors = _DARK_CURVE_COLORS if isDarkTheme() else _CURVE_COLORS
        return colors[index % len(colors)]

    def apply_theme(self):
        """Update appearance without rebuilding curves, histories or controls."""
        dark = isDarkTheme()
        foreground = "#e5e5e5" if dark else "#202020"
        muted = "#b0b0b0" if dark else "#606060"
        accent = "#4aa3df" if dark else "#0078d4"
        if self._plot:
            self._plot.setBackground("#252525" if dark else "#ffffff")
            self._plot.setTitle(self._title, color=foreground, size="10pt")
            for name in ("left", "bottom", "right", "top"):
                axis = self._plot.getAxis(name)
                axis.setPen(pg.mkPen(muted))
                axis.setTextPen(pg.mkPen(foreground))
            self._legend.setLabelTextColor(foreground)
            # A backing in the plot's colour keeps the names readable where a curve runs under them.
            self._legend.setBrush((37, 37, 37, 210) if dark else (255, 255, 255, 210))
            for _, label in self._legend.items:
                label.setText(label.text)  # the new color only reaches a label when it is drawn again
            for index, curve in enumerate(self._curves):
                if curve:
                    curve.setPen(pg.mkPen(self._curve_color(index), width=2))
            for index, curve in enumerate(self._ref_curves):
                if curve:
                    curve.setPen(self._ref_pen(index))
        elif self._missing_label is not None:
            setCustomStyleSheet(
                self._missing_label,
                "FluentLabelBase { color: #606060; border: 1px dashed #ccc; background: #fafafa; }",
                "FluentLabelBase { color: #c0c0c0; border: 1px dashed #555; background: #252525; }",
            )
        self._mode_label.setStyleSheet(
            f"font-size: 10px; color: {accent}; padding: 1px 0;")
        for label in self._val_labels + self._ref_labels:
            label.setStyleSheet(
                f"font-size: 11px; padding: 1px 2px; color: {foreground};")
        if self._cursor_mode and self._cursor_line:
            self._update_table_at_cursor(self._cursor_line.value())
        else:
            self._update_table_realtime()
        self.update()

    def set_title(self, title: str):
        self._title = title
        if self._plot:
            self._plot.setTitle(title, color="#e5e5e5" if isDarkTheme() else "#202020", size="10pt")

    def set_display_points(self, n: int):
        self._display_points = max(10, min(self.HISTORY_LIMIT, n))
        self._disp_edit.blockSignals(True)
        self._disp_edit.setText(str(self._display_points))
        self._disp_edit.blockSignals(False)
        self._refresh_all()

    def load_from_props(self, props: dict):
        """Build curve configs from flat properties and rebuild."""
        self._cfgs = build_cfgs_from_props(props)
        self._rebuild_curves()

    def set_curve_count(self, n: int):
        old = len(self._cfgs)
        n = max(1, min(8, n))
        while len(self._cfgs) > n:
            self._cfgs.pop()
        while len(self._cfgs) < n:
            idx = len(self._cfgs)
            cfg = dict(_DEFAULT_CURVE_CFG)
            cfg["name"] = f"曲线{idx + 1}"
            self._cfgs.append(cfg)
        if len(self._cfgs) != old:
            self._rebuild_curves()

    # -- internal -------------------------------------------------------------

    def _on_disp_changed(self):
        try:
            v = int(self._disp_edit.text())
        except (ValueError, TypeError):
            v = self._display_points
        self._display_points = max(10, v)
        self._disp_edit.setText(str(self._display_points))
        self._refresh_all()

    def _refresh_all(self):
        self._refresh_timer.stop()
        for i in range(len(self._data)):
            if i < len(self._curves) and self._curves[i]:
                self._curves[i].setData(self._data[i].tail(self._display_points))
        start = self._window_start()
        for curve, (_, values) in zip(self._ref_curves, self._refs):
            if curve:
                curve.setData(values[start:start + self._display_points])
        if self._cursor_mode and self._cursor_line:
            self._update_table_at_cursor(self._cursor_line.value())
        else:
            self._update_table_realtime()

    def _rebuild_curves(self):
        self.clear_reference()  # its rows live in the value table rebuilt below
        self._raw_frames = [
            RawFrameBuffer(_hex_to_bytes(cfg.get("frameHeader", "")),
                           _hex_to_bytes(cfg.get("frameTail", ""))) for cfg in self._cfgs
        ]
        for c in self._curves:
            if self._plot and c:
                self._plot.removeItem(c)
        self._curves.clear()

        count = len(self._cfgs)
        while self._data and len(self._data) > count:
            self._data.pop().close()
        while len(self._data) < count:
            self._data.append(ChartHistory(self.HISTORY_LIMIT))

        while self._val_panel.count():
            it = self._val_panel.takeAt(0)
            if it.widget():
                it.widget().hide()  # gone at once: a snapshot taken before the deletion runs must not show it
                it.widget().deleteLater()
        self._val_labels.clear()

        for i, cfg in enumerate(self._cfgs):
            color = self._curve_color(i)
            name = cfg.get("name", f"曲线{i + 1}")

            if self._plot:
                pen = pg.mkPen(color=color, width=2)
                curve = self._plot.plot(pen=pen, name=name)
                self._curves.append(curve)
            else:
                self._curves.append(None)

            # sized for a typical reading up front; apply_theme then shows the real values
            vl = QLabel(f"<b style='color:rgb{color}'>{name}</b>  {self._SAMPLE_READING}")
            vl.setStyleSheet("font-size: 11px; padding: 1px 2px;")
            self._val_panel.addWidget(vl)
            self._val_labels.append(vl)

        self._fit_legend()
        self._cursor_mode = False
        self._mode_label.setText("实时")
        self._side.setMinimumWidth(0)
        self._hold_side_width()
        self.apply_theme()

    def _fit_legend(self, *_):
        """One row of curve names across the top of the plot, or as many columns as fit when
        the names are wider than the plot, so none is cut off."""
        if self._legend is None or not self._curves:
            return
        count = len(self._curves)
        self._legend.setColumnCount(count)
        self._legend.updateSize()
        available = self._plot.getViewBox().width()
        width = self._legend.boundingRect().width()
        if available > 0 and width > available:
            self._legend.setColumnCount(max(1, int(count * available / width)))
            self._legend.updateSize()

    def _hold_side_width(self):
        """Let the value table widen but never narrow back. A reading that gets shorter (99.82 -> 100) would
        otherwise hand its space to the plot, and the whole curve would shift sideways with every sample."""
        for label in (self._mode_label, *self._val_labels, *self._ref_labels):
            label.ensurePolished()
        margins = self._side.layout().contentsMargins()
        need = max([self._mode_label.fontMetrics().horizontalAdvance(self._SAMPLE_MODE)]
                   + [label.sizeHint().width() for label in self._val_labels + self._ref_labels])
        need += margins.left() + margins.right()
        if need > self._side.minimumWidth():
            self._side.setMinimumWidth(need)

    # -- comparison overlay ---------------------------------------------------

    def load_reference(self, path):
        """Lay a saved recording over the live curves as dashed curves, to compare runs. The live curves and
        their history stay as they are; the two line up sample for sample from the start of each."""
        names, histories = self._read_history(path)
        try:
            refs = [(f"{name}（{Path(path).stem}）", list(history.values()))
                    for name, history in zip(names, histories)]
        finally:
            for history in histories:
                history.close()
        self.clear_reference()
        self._refs = refs
        for index in range(len(refs)):
            self._ref_curves.append(self._plot.plot(pen=self._ref_pen(index)) if self._plot else None)
            label = QLabel()
            self._val_panel.addWidget(label)
            self._ref_labels.append(label)
        self._clear_ref_btn.show()
        self.apply_theme()
        self._refresh_all()

    def clear_reference(self):
        for curve in self._ref_curves:
            if self._plot and curve:
                self._plot.removeItem(curve)
        for label in self._ref_labels:
            self._val_panel.removeWidget(label)
            label.hide()
            label.deleteLater()
        self._refs, self._ref_curves, self._ref_labels = [], [], []
        self._clear_ref_btn.hide()

    def _ref_color(self, index):
        """A recording takes the palette colours after the live curves', so it stands apart even where it
        crosses the curve it is compared with; the value table names which is which."""
        return self._curve_color(len(self._cfgs) + index)

    def _ref_pen(self, index):
        return pg.mkPen(self._ref_color(index), width=2, style=Qt.DashLine)

    def _window_start(self):
        """Sample number of the first point the live window shows."""
        return max(0, max((h.count for h in self._data), default=0) - self._display_points)

    def _update_reference_rows(self, sample):
        for index, (label, (name, values)) in enumerate(zip(self._ref_labels, self._refs)):
            val = f"{values[sample]:.4g}" if 0 <= sample < len(values) else "--"
            label.setText(f"<b style='color:rgb{self._ref_color(index)}'>{name}</b>  {val}")

    # -- cursor ---------------------------------------------------------------

    def _on_plot_clicked(self, evt):
        if evt.double():
            self._cursor_mode = False
            self._mode_label.setText("实时")
            if self._cursor_line:
                self._cursor_line.setVisible(False)
            self._update_table_realtime()
            return
        if not self._plot:
            return
        scene_pos = evt.scenePos()
        vb = self._plot.plotItem.vb
        mouse_point = vb.mapSceneToView(scene_pos)
        x = mouse_point.x()
        self._cursor_mode = True
        if self._cursor_line:
            self._cursor_line.setVisible(True)
            self._cursor_line.blockSignals(True)
            self._cursor_line.setValue(x)
            self._cursor_line.blockSignals(False)
        self._update_table_at_cursor(x)

    def _on_cursor_moved(self, *_):
        if not self._cursor_line:
            return
        self._cursor_mode = True
        x = self._cursor_line.value()
        self._update_table_at_cursor(x)

    def _update_table_at_cursor(self, x: float):
        idx = int(round(x))
        self._mode_label.setText(f"游标: x={idx}")
        for i, lbl in enumerate(self._val_labels):
            color = self._curve_color(i)
            name = self._cfgs[i].get("name", f"曲线{i+1}") if i < len(self._cfgs) else ""
            visible = self._data[i].tail(self._display_points) if i < len(self._data) else []
            val = f"{visible[idx]:.4g}" if 0 <= idx < len(visible) else "--"
            lbl.setText(f"<b style='color:rgb{color}'>{name}</b>  {val}")
        self._update_reference_rows(self._window_start() + idx)
        self._hold_side_width()

    def _update_table_realtime(self):
        for i, lbl in enumerate(self._val_labels):
            color = self._curve_color(i)
            name = self._cfgs[i].get("name", f"曲线{i+1}") if i < len(self._cfgs) else ""
            if i < len(self._data) and self._data[i]:
                val = f"{self._data[i][-1]:.4g}"
            else:
                val = "--"
            lbl.setText(f"<b style='color:rgb{color}'>{name}</b>  {val}")
        # the recording at the point the live run has reached
        self._update_reference_rows(max((h.count for h in self._data), default=0) - 1)
        self._hold_side_width()

    # -- data input -----------------------------------------------------------

    def append_value(self, channel: int, value: float):
        if 0 <= channel < len(self._data):
            try:
                self._data[channel].append(value)
            except OSError as error:
                self._mode_label.setText(f"记录失败: {error}")
                return
            if not self._refresh_timer.isActive():
                self._refresh_timer.start()

    def clear_data(self):
        self._refresh_timer.stop()
        for i in range(len(self._data)):
            self._data[i].clear()
            if i < len(self._curves) and self._curves[i]:
                self._curves[i].setData([])
        self._update_table_realtime()

    # -- save / load ----------------------------------------------------------

    def save_data(self, path):
        """Stream the complete history, including samples evicted from display."""
        names = [c.get("name", f"曲线{i+1}") for i, c in enumerate(self._cfgs)]
        with open(path, "w", newline="", encoding="utf-8") as output:
            if str(path).lower().endswith(".json"):
                # Objects retain the original format for unique names. Ordered
                # channel records keep duplicate names lossless in other JSON readers.
                duplicate_names = len(set(names)) != len(names)
                output.write("[" if duplicate_names else "{")
                for i, name in enumerate(names):
                    if i:
                        output.write(",")
                    encoded_name = json.dumps(name, ensure_ascii=False)
                    output.write(('{"name":' + encoded_name + ',"values":[')
                                 if duplicate_names else encoded_name + ":[")
                    for index, value in enumerate(self._data[i].values()):
                        if index:
                            output.write(",")
                        output.write(json.dumps(value, allow_nan=False))
                    output.write("]}" if duplicate_names else "]")
                output.write("]" if duplicate_names else "}")
            else:
                writer = csv.writer(output)
                writer.writerow(names)
                writer.writerows(zip_longest(*(h.values() for h in self._data), fillvalue=""))

    def _save_data(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存完整曲线数据", "", "CSV文件 (*.csv);;JSON文件 (*.json)")
        if path:
            try:
                self.save_data(path)
            except OSError as error:
                self._mode_label.setText(f"保存失败: {error}")

    def load_data(self, path):
        """Replace samples for existing channels without changing live parsing.

        Identical channel lists retain their order (including duplicate names).
        Unique names may be reordered in a file. Other channel changes are
        rejected instead of silently associating samples with another parser.
        An empty, unconfigured default chart can adopt the file's channels.
        """
        adopt_channels = (self._cfgs == [_DEFAULT_CURVE_CFG]
                          and not any(history.count for history in self._data))
        names, histories = self._read_history(path)
        try:
            channel_order = self._history_channel_order(names, adopt_channels)
        except Exception:
            for history in histories:
                history.close()
            raise
        self._refresh_timer.stop()
        for history in self._data:
            history.close()
        self._data[:] = [histories[index] for index in channel_order]
        if adopt_channels:
            self._cfgs = [{**_DEFAULT_CURVE_CFG, "name": name} for name in names]
            self._rebuild_curves()
        self._refresh_all()

    def _read_history(self, path):
        """Channel names and their samples from a saved CSV or JSON file; the caller closes the histories."""
        histories = []
        try:
            with open(path, "r", encoding="utf-8") as source:
                if str(path).lower().endswith(".json"):
                    # JSON is a document format; CSV is streamed for large captures.
                    obj = json.load(source, object_pairs_hook=_HistoryObjectPairs)
                    channels = _history_json_channels(obj)
                    names = [name for name, _ in channels]
                    for name, values in channels:
                        history = ChartHistory(self.HISTORY_LIMIT)
                        histories.append(history)
                        for value in values:
                            if value is not None:
                                history.append(float(value))
                else:
                    rows = csv.reader(source)
                    names = next(rows, [])
                    histories = [ChartHistory(self.HISTORY_LIMIT) for _ in names]
                    for row in rows:
                        for index, history in enumerate(histories):
                            if index < len(row) and row[index].strip():
                                history.append(float(row[index]))
        except Exception:
            for history in histories:
                history.close()
            raise
        return names, histories

    def _history_channel_order(self, names, adopt_channels=False):
        expected = [cfg.get("name", f"曲线{i+1}") for i, cfg in enumerate(self._cfgs)]
        if not names:
            raise ValueError("曲线文件没有通道")
        if len(names) > 8:
            raise ValueError("曲线文件最多支持 8 个通道")
        if adopt_channels:
            return list(range(len(names)))
        if names == expected:
            return list(range(len(expected)))
        if (len(names) == len(expected) and len(set(names)) == len(names)
                and set(names) == set(expected)):
            return [names.index(name) for name in expected]
        raise ValueError("曲线文件通道名称或数量与当前配置不一致，请加载对应通道的历史文件")

    def _load_data(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载对比曲线", "", "CSV文件 (*.csv);;JSON文件 (*.json)")
        if path:
            try:
                self.load_reference(path)
            except (OSError, ValueError, TypeError, OverflowError) as error:
                self._mode_label.setText(f"加载失败: {error}")

    def configure(self, cfgs, disp_pts=200):
        if isinstance(cfgs, str):
            cfgs = json.loads(cfgs)
        self._cfgs = list(cfgs)[:8]
        self._rebuild_curves()
        self.set_display_points(disp_pts)

    def on_parsed(self, data):
        self._on_parsed_data(data)

    def on_raw(self, data):
        self._on_raw_data(data)

    def reset_stream(self):
        for frames in self._raw_frames:
            frames.reset()

    # -- self-parsing (per-curve) ---------------------------------------------

    def _on_parsed_data(self, data: dict):
        for i, cfg in enumerate(self._cfgs):
            try:
                pm = cfg.get("parseMode", "键值匹配")
                val = None
                if pm == "键值匹配":
                    key = cfg.get("key") or cfg.get("name", "")
                    if key and key in data:
                        val = data[key]
                elif pm == "JSON路径":
                    jp = cfg.get("jsonPath", "")
                    if jp:
                        val = self._resolve_path(data, jp)
                elif pm == "Modbus":
                    val = self._extract_modbus(cfg, data)
                if val is not None:
                    self.append_value(i, val)
            except (ValueError, TypeError, OverflowError, struct.error):
                # Reject a bad sample without losing the other channels in this frame.
                continue

    def _on_raw_data(self, raw: bytes):
        for i, cfg in enumerate(self._cfgs):
            if cfg.get("parseMode") != "HEX字节提取":
                continue
            fi = _STRUCT_FMT.get(cfg.get("dataType", "float32"))
            if not fi:
                continue
            fmt_c, sz = fi
            bo = ">" if cfg.get("byteOrder", "大端(BE)") == "大端(BE)" else "<"
            off = int(cfg.get("byteOffset", 0))
            for frame in self._raw_frames[i].feed(raw):
                payload = self._strip_frame(frame, cfg)
                if payload is not None and off >= 0 and off + sz <= len(payload):
                    try:
                        val = struct.unpack(bo + fmt_c, payload[off:off + sz])[0]
                        self.append_value(i, float(val))
                    except (ValueError, TypeError, OverflowError, struct.error):
                        pass

    def modbus_needs(self):
        """What the Modbus curves read, for the Modbus poller: (slave, table, address, count,
        period) each, read at the poller's default period. A curve counts whether or not it is on screen."""
        needs = []
        for cfg in self._cfgs:
            if cfg.get("parseMode") != "Modbus":
                continue
            try:
                need = modbus_need(cfg.get("mbArea", "保持寄存器"), int(cfg.get("regIndex", 0)),
                                   cfg.get("mbDataType", "uint16"), int(cfg.get("mbSlaveFilter", -1)))
            except (TypeError, ValueError):
                continue
            if need is not None:
                needs.append(need)
        return needs

    @staticmethod
    def _extract_modbus(cfg: dict, data: dict):
        return modbus_value(
            data, int(cfg.get("regIndex", 0)), cfg.get("mbDataType", "uint16"),
            cfg.get("mbRegOrder", "大端(AB CD)"), int(cfg.get("mbFcFilter", -1)),
            int(cfg.get("mbSlaveFilter", -1)), cfg.get("mbArea", "保持寄存器"))

    @staticmethod
    def _strip_frame(raw: bytes, cfg: dict):
        data = raw
        fh = cfg.get("frameHeader", "")
        ft = cfg.get("frameTail", "")
        if fh:
            hdr = _hex_to_bytes(fh)
            if hdr:
                idx = data.find(hdr)
                if idx < 0:
                    return None
                data = data[idx + len(hdr):]
        if ft:
            tlr = _hex_to_bytes(ft)
            if tlr:
                idx = data.find(tlr)
                if idx < 0:
                    return None
                data = data[:idx]
        return data

    @staticmethod
    def _resolve_path(data, path: str):
        for part in path.split("."):
            if data is None:
                return None
            if isinstance(data, dict):
                data = data.get(part)
            elif isinstance(data, (list, tuple)):
                try:
                    data = data[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return data


def _hex_to_bytes(s: str) -> bytes:
    s = s.replace(" ", "")
    if not s:
        return b""
    if len(s) % 2 != 0:
        s = "0" + s
    try:
        return bytes.fromhex(s)
    except ValueError:
        return b""
