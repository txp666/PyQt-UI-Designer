# coding: utf-8
"""Chart widgets: real-time line chart (pyqtgraph) and gauge meter."""
import csv
import json
import struct
import math

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QConicalGradient
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel

from qfluentwidgets import (
    LineEdit as FluentLineEdit, PushButton as FluentPushButton,
    CheckBox as FluentCheckBox, BodyLabel,
)

from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.widget_registry import registry

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

_CURVE_COLORS = [
    (0, 120, 212), (244, 67, 54), (76, 175, 80), (255, 152, 0),
    (156, 39, 176), (0, 188, 212), (121, 85, 72), (96, 125, 139),
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
        self._checkboxes: list = []
        self._listening = False
        self._cursor_mode = False

        # ---- main area: plot (left) + value table (right) ----
        main_h = QHBoxLayout()
        main_h.setSpacing(4)

        if HAS_PYQTGRAPH:
            self._plot = pg.PlotWidget()
            self._plot.setBackground("w")
            self._plot.setTitle(self._title, color="k", size="10pt")
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
            lbl = BodyLabel("需要安装 pyqtgraph")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #999; border: 1px dashed #ccc; background: #fafafa;")
            main_h.addWidget(lbl, 1)
            self._plot = None
            self._cursor_line = None

        # right panel: mode label + value labels
        right_panel = QVBoxLayout()
        right_panel.setContentsMargins(2, 0, 2, 0)
        right_panel.setSpacing(0)
        self._mode_label = QLabel("实时")
        self._mode_label.setAlignment(Qt.AlignCenter)
        self._mode_label.setStyleSheet(
            "font-size: 10px; color: #0078d4; padding: 1px 0;")
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

    # -- public configuration -------------------------------------------------

    def set_title(self, title: str):
        self._title = title
        if self._plot:
            self._plot.setTitle(title, color="k", size="10pt")

    def set_display_points(self, n: int):
        self._display_points = max(10, n)
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
        for i in range(len(self._data)):
            if i < len(self._curves) and self._curves[i]:
                self._curves[i].setData(self._data[i][-self._display_points:])

    def _rebuild_curves(self):
        for c in self._curves:
            if self._plot and c:
                self._plot.removeItem(c)
        self._curves.clear()

        count = len(self._cfgs)
        while self._data and len(self._data) > count:
            self._data.pop()
        while len(self._data) < count:
            self._data.append([])

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
            color = _CURVE_COLORS[i % len(_CURVE_COLORS)]
            name = cfg.get("name", f"曲线{i + 1}")

            if self._plot:
                pen = pg.mkPen(color=color, width=2)
                curve = self._plot.plot(pen=pen, name=name)
                self._curves.append(curve)
            else:
                self._curves.append(None)

            cb = FluentCheckBox(name)
            cb.setChecked(True)
            cb.setStyleSheet(
                f"FluentCheckBox, QCheckBox {{ color: rgb{color}; font-size: 11px; }}"
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
            color = _CURVE_COLORS[i % len(_CURVE_COLORS)]
            name = self._cfgs[i].get("name", f"曲线{i+1}") if i < len(self._cfgs) else ""
            visible = self._data[i][-self._display_points:] if i < len(self._data) else []
            val = f"{visible[idx]:.4g}" if 0 <= idx < len(visible) else "--"
            lbl.setText(f"<b style='color:rgb{color}'>{name}</b>  {val}")

    def _update_table_realtime(self):
        for i, lbl in enumerate(self._val_labels):
            color = _CURVE_COLORS[i % len(_CURVE_COLORS)]
            name = self._cfgs[i].get("name", f"曲线{i+1}") if i < len(self._cfgs) else ""
            if i < len(self._data) and self._data[i]:
                val = f"{self._data[i][-1]:.4g}"
            else:
                val = "--"
            lbl.setText(f"<b style='color:rgb{color}'>{name}</b>  {val}")

    # -- data input -----------------------------------------------------------

    def append_value(self, channel: int, value: float):
        if 0 <= channel < len(self._data):
            self._data[channel].append(value)
            if channel < len(self._curves) and self._curves[channel]:
                self._curves[channel].setData(
                    self._data[channel][-self._display_points:])
            if not self._cursor_mode and channel < len(self._val_labels):
                color = _CURVE_COLORS[channel % len(_CURVE_COLORS)]
                name = self._cfgs[channel].get("name", f"曲线{channel+1}") if channel < len(self._cfgs) else ""
                self._val_labels[channel].setText(
                    f"<b style='color:rgb{color}'>{name}</b>  {value:.4g}")

    def clear_data(self):
        for i in range(len(self._data)):
            self._data[i].clear()
            if i < len(self._curves) and self._curves[i]:
                self._curves[i].setData([])

    # -- save / load ----------------------------------------------------------

    def _save_data(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存曲线数据", "", "CSV文件 (*.csv);;JSON文件 (*.json)")
        if not path:
            return
        names = [c.get("name", f"曲线{i+1}") for i, c in enumerate(self._cfgs)]
        if path.lower().endswith(".json"):
            obj = {names[i]: list(self._data[i]) if i < len(self._data) else []
                   for i in range(len(self._cfgs))}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
        else:
            mx = max((len(d) for d in self._data), default=0)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(names)
                for r in range(mx):
                    w.writerow([
                        self._data[ch][r] if ch < len(self._data)
                        and r < len(self._data[ch]) else ""
                        for ch in range(len(self._cfgs))])

    def _load_data(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载曲线数据", "", "CSV文件 (*.csv);;JSON文件 (*.json)")
        if not path:
            return
        try:
            if path.lower().endswith(".json"):
                with open(path, "r", encoding="utf-8") as f:
                    obj = json.load(f)
                if not isinstance(obj, dict):
                    return
                nms = list(obj.keys())[:8]
                self._cfgs = [{**_DEFAULT_CURVE_CFG, "name": n} for n in nms]
                self._rebuild_curves()
                for i, n in enumerate(nms):
                    vs = obj[n]
                    if isinstance(vs, list):
                        self._data[i] = [float(v) for v in vs if v is not None]
            else:
                with open(path, "r", encoding="utf-8") as f:
                    rd = csv.reader(f)
                    hdr = next(rd, None)
                    if not hdr:
                        return
                    cols = min(8, len(hdr))
                    loaded = [[] for _ in range(cols)]
                    for row in rd:
                        for ci in range(cols):
                            try:
                                loaded[ci].append(float(row[ci]) if ci < len(row) else 0.0)
                            except (ValueError, TypeError):
                                loaded[ci].append(0.0)
                self._cfgs = [{**_DEFAULT_CURVE_CFG, "name": hdr[i]} for i in range(cols)]
                self._rebuild_curves()
                for i in range(cols):
                    self._data[i] = loaded[i]
        except Exception:
            return
        self._refresh_all()

    # -- self-parsing (per-curve) ---------------------------------------------

    def start_listening(self):
        if self._listening:
            return
        self._listening = True
        from app.common.signal_bus import signalBus
        signalBus.serialDataReceived.connect(self._on_parsed_data)
        signalBus.serialRawReceived.connect(self._on_raw_data)

    def stop_listening(self):
        if not self._listening:
            return
        self._listening = False
        from app.common.signal_bus import signalBus
        try:
            signalBus.serialDataReceived.disconnect(self._on_parsed_data)
            signalBus.serialRawReceived.disconnect(self._on_raw_data)
        except TypeError:
            pass

    def _on_parsed_data(self, data: dict):
        for i, cfg in enumerate(self._cfgs):
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
                try:
                    self.append_value(i, float(val))
                except (ValueError, TypeError):
                    pass

    def _on_raw_data(self, raw: bytes):
        for i, cfg in enumerate(self._cfgs):
            if cfg.get("parseMode") != "HEX字节提取":
                continue
            payload = self._strip_frame(raw, cfg)
            if payload is None:
                continue
            fi = _STRUCT_FMT.get(cfg.get("dataType", "float32"))
            if not fi:
                continue
            fmt_c, sz = fi
            bo = ">" if cfg.get("byteOrder", "大端(BE)") == "大端(BE)" else "<"
            off = int(cfg.get("byteOffset", 0))
            if off + sz <= len(payload):
                try:
                    val = struct.unpack(bo + fmt_c, payload[off:off + sz])[0]
                    self.append_value(i, float(val))
                except struct.error:
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
        dt = cfg.get("mbDataType", "uint16")
        if dt == "uint16":
            return r0
        if dt == "int16":
            return r0 - 65536 if r0 > 32767 else r0
        r1 = data.get(f"reg{idx + 1}")
        if r1 is None:
            return None
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


# ---------------------------------------------------------------------------
# Gauge meter
# ---------------------------------------------------------------------------

class GaugeMeter(QWidget):
    """Analog gauge / dial meter display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._min_val = 0.0
        self._max_val = 100.0
        self._title = "仪表"
        self._unit = ""
        self.setMinimumSize(80, 80)

    def set_value(self, v: float):
        self._value = max(self._min_val, min(self._max_val, v))
        self.update()

    def set_range(self, lo: float, hi: float):
        self._min_val = lo
        self._max_val = hi
        self.update()

    def set_title(self, t: str):
        self._title = t
        self.update()

    def set_unit(self, u: str):
        self._unit = u
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        side = min(w, h) - 10
        cx, cy = w / 2, h / 2
        radius = side / 2

        # arc background
        arc_rect = QRectF(cx - radius, cy - radius, side, side)
        start_angle = 225  # degrees
        span_angle = -270

        bg_pen = QPen(QColor(220, 220, 220), max(6, side / 12))
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(arc_rect, int(start_angle * 16), int(span_angle * 16))

        # value arc
        rng = self._max_val - self._min_val
        ratio = (self._value - self._min_val) / rng if rng > 0 else 0
        val_span = span_angle * ratio

        val_pen = QPen(QColor(0, 120, 212), max(6, side / 12))
        val_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(val_pen)
        painter.drawArc(arc_rect, int(start_angle * 16), int(val_span * 16))

        # value text
        painter.setPen(QColor(30, 30, 30))
        font_size = max(10, int(side / 6))
        painter.setFont(QFont("Microsoft YaHei", font_size, QFont.Bold))
        val_text = f"{self._value:.1f}"
        painter.drawText(self.rect(), Qt.AlignCenter, val_text)

        # unit text below
        painter.setFont(QFont("Microsoft YaHei", max(8, int(font_size * 0.6))))
        painter.setPen(QColor(120, 120, 120))
        unit_rect = self.rect().adjusted(0, int(font_size * 1.5), 0, 0)
        painter.drawText(unit_rect, Qt.AlignHCenter | Qt.AlignTop, self._unit)

        # title text above
        painter.setFont(QFont("Microsoft YaHei", max(8, int(font_size * 0.5))))
        painter.setPen(QColor(160, 160, 160))
        title_rect = self.rect().adjusted(0, 0, 0, -int(font_size * 1.5))
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignBottom, self._title)

        painter.end()


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

_PARSE_MODES = ["键值匹配", "JSON路径", "HEX字节提取", "Modbus"]
_HEX_DTYPES = ["uint8", "int8", "uint16", "int16", "uint32", "int32", "float32"]
_HEX_BORDER = ["大端(BE)", "小端(LE)"]
_MB_DTYPES = ["uint16", "int16", "uint32", "int32", "float32"]
_MB_REGORD = ["大端(AB CD)", "小端(CD AB)"]

REALTIME_CHART_META = WidgetMeta(
    type_name="RealtimeChart",
    display_name="实时曲线",
    category=WidgetCategory.CHART,
    icon="HISTORY",
    default_width=400, default_height=280,
    min_width=200, min_height=150,
    properties=[
        PropDef("title", "标题", PropType.STRING, "实时曲线"),
        PropDef("displayPoints", "显示点数", PropType.INT, 200,
                min_val=10, max_val=999999),
        PropDef("curveCount", "曲线数量", PropType.INT, 1,
                min_val=1, max_val=8),
        PropDef("currentCurve", "当前编辑曲线", PropType.INT, 0,
                min_val=0, max_val=7),
        # ---- per-curve virtual (stored as _curve_{i}_{field}) ----
        PropDef("curveName", "曲线名称", PropType.STRING, "曲线1"),
        PropDef("curveParseMode", "解析模式", PropType.ENUM, "键值匹配",
                options=_PARSE_MODES),
        PropDef("curveKey", "匹配键", PropType.STRING, ""),
        PropDef("curveJsonPath", "JSON路径", PropType.STRING, ""),
        PropDef("curveByteOffset", "字节偏移", PropType.INT, 0,
                min_val=0, max_val=9999),
        PropDef("curveDataType", "数据类型(HEX)", PropType.ENUM, "float32",
                options=_HEX_DTYPES),
        PropDef("curveByteOrder", "字节序(HEX)", PropType.ENUM, "大端(BE)",
                options=_HEX_BORDER),
        PropDef("curveFrameHeader", "帧头(HEX)", PropType.STRING, ""),
        PropDef("curveFrameTail", "帧尾(HEX)", PropType.STRING, ""),
        PropDef("curveRegIndex", "寄存器索引", PropType.INT, 0,
                min_val=0, max_val=65535),
        PropDef("curveMbDataType", "数据类型(MB)", PropType.ENUM, "uint16",
                options=_MB_DTYPES),
        PropDef("curveMbRegOrder", "寄存器序(MB)", PropType.ENUM, "大端(AB CD)",
                options=_MB_REGORD),
        PropDef("curveMbFcFilter", "功能码过滤", PropType.INT, -1,
                min_val=-1, max_val=255),
        PropDef("curveMbSlaveFilter", "从站过滤", PropType.INT, -1,
                min_val=-1, max_val=255),
    ],
)

GAUGE_META = WidgetMeta(
    type_name="GaugeMeter",
    display_name="仪表盘",
    category=WidgetCategory.CHART,
    icon="SPEED_HIGH",
    default_width=180, default_height=180,
    min_width=80, min_height=80,
    properties=[
        PropDef("title", "标题", PropType.STRING, "仪表"),
        PropDef("unit", "单位", PropType.STRING, ""),
        PropDef("value", "当前值", PropType.FLOAT, 0.0, min_val=-99999, max_val=99999, bindable=True),
        PropDef("minimum", "最小值", PropType.FLOAT, 0.0, min_val=-99999, max_val=99999),
        PropDef("maximum", "最大值", PropType.FLOAT, 100.0, min_val=-99999, max_val=99999),
    ],
)

ALL_CHART = [REALTIME_CHART_META, GAUGE_META]


def register_chart_widgets():
    for meta in ALL_CHART:
        registry.register(meta)


def create_chart_widget(type_name: str, props: dict, parent=None) -> QWidget:
    if type_name == "RealtimeChart":
        w = RealtimeLineChart(parent)
        w.set_title(props.get("title", "实时曲线"))
        w.set_display_points(props.get("displayPoints", 200))
        w.load_from_props(props)
        return w

    if type_name == "GaugeMeter":
        w = GaugeMeter(parent)
        w.set_title(props.get("title", "仪表"))
        w.set_unit(props.get("unit", ""))
        w.set_range(props.get("minimum", 0), props.get("maximum", 100))
        w.set_value(props.get("value", 0))
        return w

    return None


def apply_chart_property(widget, type_name: str, prop_name: str, value):
    if type_name == "RealtimeChart":
        if prop_name == "title":
            widget.set_title(value)
        elif prop_name == "displayPoints":
            widget.set_display_points(value)

    elif type_name == "GaugeMeter":
        if prop_name == "title":
            widget.set_title(value)
        elif prop_name == "unit":
            widget.set_unit(value)
        elif prop_name == "value":
            widget.set_value(value)
        elif prop_name == "minimum":
            widget.set_range(value, widget._max_val)
        elif prop_name == "maximum":
            widget.set_range(widget._min_val, value)
