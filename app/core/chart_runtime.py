# coding: utf-8
"""Chart widgets: real-time line chart (pyqtgraph) and gauge meter."""
import csv
import json
import struct
from itertools import zip_longest

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel

from qfluentwidgets import (
    LineEdit as FluentLineEdit, PushButton as FluentPushButton,
    CheckBox as FluentCheckBox, BodyLabel, isDarkTheme, qconfig,
    setCustomStyleSheet,
)


from .chart_history import ChartHistory
from .protocol_parser import RawFrameBuffer
from .binding_values import binding_register

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
    "mbFcFilter": -1, "mbSlaveFilter": -1,
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

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self._checkboxes: list = []
        self._listening = False
        self._cursor_mode = False

        # ---- main area: plot (left) + value table (right) ----
        main_h = QHBoxLayout()
        main_h.setSpacing(4)
        self._missing_label = None

        if HAS_PYQTGRAPH:
            self._plot = pg.PlotWidget()
            self._plot.showGrid(x=True, y=True, alpha=0.3)
            main_h.addWidget(self._plot, 1)

            self._cursor_line = pg.InfiniteLine(
                angle=90, movable=True,
                pen=pg.mkPen(color=(255, 0, 0, 180), width=1, style=Qt.DashLine))
            self._cursor_line.setVisible(False)
            self._plot.addItem(self._cursor_line)
            self._cursor_line.sigPositionChanged.connect(self._on_cursor_moved)
            self._plot.scene().sigMouseClicked.connect(self._on_plot_clicked)
        else:
            self._missing_label = BodyLabel("需要安装 pyqtgraph")
            self._missing_label.setAlignment(Qt.AlignCenter)
            main_h.addWidget(self._missing_label, 1)
            self._plot = None
            self._cursor_line = None

        # right panel: mode label + value labels
        right_panel = QVBoxLayout()
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
        main_h.addLayout(right_panel)

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
        self._root.addLayout(tb)

        self._cb_row = QHBoxLayout()
        self._cb_row.setContentsMargins(4, 0, 4, 2)
        self._root.addLayout(self._cb_row)

        self._rebuild_curves()
        qconfig.themeChangedFinished.connect(self.apply_theme)

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
            for index, curve in enumerate(self._curves):
                if curve:
                    curve.setPen(pg.mkPen(self._curve_color(index), width=2))
        elif self._missing_label is not None:
            setCustomStyleSheet(
                self._missing_label,
                "FluentLabelBase { color: #606060; border: 1px dashed #ccc; background: #fafafa; }",
                "FluentLabelBase { color: #c0c0c0; border: 1px dashed #555; background: #252525; }",
            )
        self._mode_label.setStyleSheet(
            f"font-size: 10px; color: {accent}; padding: 1px 0;")
        for label in self._val_labels:
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
        if self._cursor_mode and self._cursor_line:
            self._update_table_at_cursor(self._cursor_line.value())
        else:
            self._update_table_realtime()

    def _rebuild_curves(self):
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

        while self._cb_row.count():
            item = self._cb_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()

        while self._val_panel.count():
            it = self._val_panel.takeAt(0)
            if it.widget():
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

            cb = FluentCheckBox(name)
            cb.setChecked(True)
            light_color = _CURVE_COLORS[i % len(_CURVE_COLORS)]
            dark_color = _DARK_CURVE_COLORS[i % len(_DARK_CURVE_COLORS)]
            setCustomStyleSheet(
                cb,
                f"QCheckBox {{ color: rgb{light_color}; font-size: 11px; }}",
                f"QCheckBox {{ color: rgb{dark_color}; font-size: 11px; }}",
            )
            idx = i
            cb.toggled.connect(lambda checked, ci=idx: self._toggle(ci, checked))
            self._checkboxes.append(cb)
            self._cb_row.addWidget(cb)

            vl = QLabel(f"<b style='color:rgb{color}'>{name}</b>  --")
            vl.setStyleSheet("font-size: 11px; padding: 1px 2px;")
            self._val_panel.addWidget(vl)
            self._val_labels.append(vl)

        self._cb_row.addStretch()
        self._cursor_mode = False
        self._mode_label.setText("实时")
        self.apply_theme()

    def _toggle(self, index: int, visible: bool):
        if index < len(self._curves) and self._curves[index]:
            self._curves[index].setVisible(visible)

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

    def _on_cursor_moved(self):
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

    def _update_table_realtime(self):
        for i, lbl in enumerate(self._val_labels):
            color = self._curve_color(i)
            name = self._cfgs[i].get("name", f"曲线{i+1}") if i < len(self._cfgs) else ""
            if i < len(self._data) and self._data[i]:
                val = f"{self._data[i][-1]:.4g}"
            else:
                val = "--"
            lbl.setText(f"<b style='color:rgb{color}'>{name}</b>  {val}")

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
        histories = []
        adopt_channels = (self._cfgs == [_DEFAULT_CURVE_CFG]
                          and not any(history.count for history in self._data))
        try:
            with open(path, "r", encoding="utf-8") as source:
                if str(path).lower().endswith(".json"):
                    # JSON is a document format; CSV is streamed for large captures.
                    obj = json.load(source, object_pairs_hook=_HistoryObjectPairs)
                    channels = _history_json_channels(obj)
                    names = [name for name, _ in channels]
                    channel_order = self._history_channel_order(names, adopt_channels)
                    for name, values in channels:
                        history = ChartHistory(self.HISTORY_LIMIT)
                        histories.append(history)
                        for value in values:
                            if value is not None:
                                history.append(float(value))
                else:
                    rows = csv.reader(source)
                    names = next(rows, [])
                    channel_order = self._history_channel_order(names, adopt_channels)
                    histories = [ChartHistory(self.HISTORY_LIMIT) for _ in names]
                    for row in rows:
                        for index, history in enumerate(histories):
                            if index < len(row) and row[index].strip():
                                history.append(float(row[index]))
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
            self, "加载曲线数据", "", "CSV文件 (*.csv);;JSON文件 (*.json)")
        if path:
            try:
                self.load_data(path)
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

    @staticmethod
    def _extract_modbus(cfg: dict, data: dict):
        sf = int(cfg.get("mbSlaveFilter", -1))
        if sf >= 0 and data.get("slave") != sf:
            return None
        fc = data.get("fc", 0)
        fcf = int(cfg.get("mbFcFilter", -1))
        if fcf >= 0 and fc != fcf:
            return None
        idx = int(cfg.get("regIndex", 0))
        if fc in (0x01, 0x02):
            return data.get(f"coil{idx}")
        r0 = data.get(f"reg{idx}")
        if r0 is None:
            return None
        r0 = binding_register(r0)
        dt = cfg.get("mbDataType", "uint16")
        if dt == "uint16":
            return r0
        if dt == "int16":
            return r0 - 65536 if r0 > 32767 else r0
        r1 = data.get(f"reg{idx + 1}")
        if r1 is None:
            return None
        r1 = binding_register(r1)
        if cfg.get("mbRegOrder", "大端(AB CD)") == "大端(AB CD)":
            hi, lo = r0, r1
        else:
            hi, lo = r1, r0
        raw_b = hi.to_bytes(2, "big") + lo.to_bytes(2, "big")
        if dt == "uint32":
            return int.from_bytes(raw_b, "big")
        if dt == "int32":
            return int.from_bytes(raw_b, "big", signed=True)
        if dt == "float32":
            return struct.unpack(">f", raw_b)[0]
        return r0

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
