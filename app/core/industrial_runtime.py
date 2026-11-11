"""Shared SVG industrial widgets for the designer, preview and standalone export."""
import json
import math
import re
from html import escape
from PyQt5.QtCore import QByteArray, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QFontMetricsF
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QWidget
from qfluentwidgets import isDarkTheme, qconfig
from app.common.runtime_sources import runtime_source
from .bit_profiles import BIT_PROFILE_TYPES, normalize_bit_profiles, resolve_bit_profile
from .signal_lifetime import SignalConnections
from .i18n import language, tr

INDUSTRIAL_CATALOG = json.loads(runtime_source("industrial_catalog.json"))
INDUSTRIAL_TYPES = {item["type"] for item in INDUSTRIAL_CATALOG}


def _svg_tokens(template, tokens):
    """Interpolate the template once; inserted labels remain literal user text."""
    return re.sub(r"\{\{([A-Za-z0-9_]+)\}\}",
                  lambda match: str(tokens.get(match.group(1), match.group(0))), template)


def _bit_name_size(name, room, base):
    units = sum(1 if ord(char) > 127 or char in "MW@%" else .68 for char in name)
    return min(base, room / max(1, units))


def binding_has_path(data, path):
    """Distinguish an explicitly supplied null sample from a missing JSON path."""
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(data, (list, tuple)):
            try:
                data = data[int(part)]
            except (ValueError, IndexError):
                return False
        else:
            return False
    return True


class IndustrialWidget(QWidget):
    """A measured value and its original engineering symbol; animation follows valid feedback."""
    def __init__(self, type_name, properties=None, parent=None):
        super().__init__(parent)
        self.spec = next(item for item in INDUSTRIAL_CATALOG if item["type"] == type_name)
        self.properties = {key: self.spec.get(key, default) for key, default in (
            ("title", self.spec["name"]), ("unit", ""), ("value", 0),
            ("minimum", 0), ("maximum", 100), ("decimals", 1))}
        if "limits" in self.spec:
            self.properties.update(showLimits=self.spec.get("limitsOn", False),
                                   lowLimit=self.spec["limits"][0], highLimit=self.spec["limits"][1])
        if type_name == "FlowPipe":
            self.properties.update(pipeShape="弯管", pipeDirection="正向布局", pipeWidth=16)  # i18n: value
        if type_name in ("Motor", "Cylinder"):
            self.properties["feedbackMode"] = "转速" if type_name == "Motor" else "行程"  # i18n: value
        self.properties.update(properties or {})
        self.properties.setdefault("bitProfile", "default")
        self.properties.setdefault("pulsesPerTurn", 1024)
        self._bit_profiles = {}
        self._history = []
        self._encoder_previous = None
        self._encoder_direction = None
        self._bound = False
        self._runtime = False
        self._value = None
        self._feedback = "pending"
        self._phase = 0.0
        self._renderer = QSvgRenderer(self)
        self._renderer.setAspectRatioMode(Qt.KeepAspectRatio)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._animate)
        self._connections = SignalConnections(self)
        self._connections.connect(qconfig.themeChangedFinished, self._refresh)
        self.setMinimumSize(80, 72)
        self.set_value(self.properties["value"])

    def set_bound(self, bound=True):
        self._bound = bool(bound)
        self._runtime = True
        if bound:
            self._history = []
            self._encoder_previous = None
            self._encoder_direction = None
            self._value = None
            self._feedback = "pending"
            self._refresh()

    def set_bit_profiles(self, profiles):
        self._bit_profiles = normalize_bit_profiles(profiles)
        if self.spec["type"] in BIT_PROFILE_TYPES and (self._value is not None or not self._runtime):
            try:
                self._value = self._validate_value(self._value if self._runtime else self.properties["value"])
                self._feedback = "normal"
            except (TypeError, ValueError, OverflowError):
                self._value = None
                self._feedback = "abnormal"
        self._refresh()

    def _profile(self):
        return resolve_bit_profile(self._bit_profiles, self.properties.get("bitProfile", "default"))

    def _validate_value(self, value):
        mode = self.spec["mode"]
        if mode == "cells":
            if not isinstance(value, list) or not value:
                raise ValueError("Expected cell voltages")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
                raise ValueError("Expected finite cell voltages")
            return list(value)
        if mode == "supply":
            if not isinstance(value, dict) or any(
                type(value.get(key)) not in (int, float) or not math.isfinite(value[key])
                for key in ("voltage", "current")
            ):
                raise ValueError("Expected supply feedback")
            feedback_mode = value.get("mode")
            if not isinstance(feedback_mode, str) or feedback_mode.strip().upper() not in ("CV", "CC"):
                raise ValueError("Expected CV or CC")
            return {"voltage": value["voltage"], "current": value["current"], "mode": feedback_mode.strip().upper()}
        if mode in ("word", "timing", "encoder"):
            if type(value) not in (int, float) or not math.isfinite(value) or int(value) != value:
                raise ValueError("Expected an integer")
            number = int(value)
            if mode == "encoder":
                ppr = self.properties["pulsesPerTurn"]
                if type(ppr) not in (int, float) or not math.isfinite(ppr) or ppr <= 0 or int(ppr) != ppr or abs(number) > 2**53-1:
                    raise ValueError("Invalid encoder count or pulses per turn")
            elif not 0 <= number < 2**self._profile()["width"]:
                raise ValueError("Status word exceeds profile width")
            return number
        number = float(value)
        if not math.isfinite(number):
            raise ValueError()
        if mode in ("state", "bits", "byte", "flags"):
            upper = self.spec["maximum"] + 1 if mode in ("byte", "flags") else 8 if mode == "bits" else len(self.spec["states"])
            if not number.is_integer() or not 0 <= number < upper:
                raise ValueError()
        if self.spec["type"] == "Motor" and self.properties.get("feedbackMode") == "运行位" and number not in (0, 1):  # i18n: value
            raise ValueError()
        if self.spec["type"] == "Cylinder" and self.properties.get("feedbackMode") == "端位状态" and number not in (0, 1, 2):  # i18n: value
            raise ValueError()
        return number

    def set_value(self, value):
        try:
            self._value = self._validate_value(value)
            self._feedback = "normal"
            if self.spec["mode"] == "encoder":
                previous = self._encoder_previous
                self._encoder_direction = None if previous is None else (1 if self._value > previous else -1 if self._value < previous else 0)
                self._encoder_previous = self._value
        except (TypeError, ValueError, OverflowError):
            self._value = None
            self._feedback = "abnormal"
            if self.spec["mode"] == "encoder":
                self._encoder_previous = self._encoder_direction = None
        if self.spec["mode"] == "timing" and self._runtime:
            self._history.append(self._value)
            self._history = self._history[-32:]
        self._refresh()

    def set_property(self, name, value):
        if name == "pulsesPerTurn" and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0 or int(value) != value):
            raise ValueError("pulsesPerTurn must be a positive integer")
        self.properties[name] = value
        if name == "value":
            self.set_value(value)
        elif name == "bitProfile":
            self.set_bit_profiles(self._bit_profiles)
        elif name in ("minimum", "maximum", "feedbackMode") and self._value is not None:
            self.set_value(self._value)
        else:
            self._refresh()

    def _drivers(self):
        names = ["level", "partial", "meniscus", "magnitude", "known", "active", "positive", "negative", "zero"]
        result = dict.fromkeys(names + [f"state{i}" for i in range(8)] +
                               [f"bit{i}" for i in range(8)] + [f"seg{i}" for i in range(1, 13)], 0)
        result.update(phase=self._phase, limitsOn=0, lowMark=0, highMark=0, lowAlarm=0, highAlarm=0,
                      straight=int(self.properties.get("pipeShape", "弯管") == "直管"),  # i18n: value
                      elbow=int(self.properties.get("pipeShape", "弯管") != "直管"),  # i18n: value
                      mirrored=int(self.properties.get("pipeDirection", "正向布局") == "镜像布局"),  # i18n: value
                      thickness=(max(8, min(26, float(self.properties.get("pipeWidth", 16)))) - 8) / 18,
                      pistonKnown=0)
        lo, hi = float(self.properties["minimum"]), float(self.properties["maximum"])
        if self.properties.get("showLimits") and hi > lo:
            low, high = float(self.properties.get("lowLimit", lo)), float(self.properties.get("highLimit", hi))
            if math.isfinite(low) and math.isfinite(high) and low < high:
                result.update(limitsOn=1, lowMark=max(0, min(1, (low-lo)/(hi-lo))),
                              highMark=max(0, min(1, (high-lo)/(hi-lo))))
                if self._value is not None:
                    result.update(lowAlarm=int(self._value <= low), highAlarm=int(self._value >= high))
        if self._value is None:
            return result
        if self.spec["mode"] in ("cells", "supply"):
            result["known"] = 1
            return result
        value = self._value
        lo, hi = float(self.properties["minimum"]), float(self.properties["maximum"])
        level = max(0, min(1, (value - lo) / (hi - lo))) if hi > lo else 0
        if self.spec["type"] == "Cylinder" and self.properties.get("feedbackMode") == "端位状态":  # i18n: value
            level = int(value == 2)
            result["pistonKnown"] = int(value in (1, 2))
        else:
            result["pistonKnown"] = 1
        result.update(level=level, partial=int(0 < level < 1), meniscus=min(1, 8 * level), magnitude=min(1, abs(value) / max(abs(lo), abs(hi), 1e-30)),
                      known=1, positive=int(value > 0), negative=int(value < 0), zero=int(value == 0))
        kind = self.spec["type"]
        result["active"] = int(value in (1, 3) if kind == "AirCompressor" else
                               value == 1 if kind == "Pump" else value != 0)
        for index in range(8):
            result[f"state{index}"] = int(value == index)
        for index in range(8):
            result[f"bit{index}"] = (int(value) >> index) & 1
        for index in range(1, 13):
            result[f"seg{index}"] = int(level >= index / 12)
        return result

    def _moving(self):
        return (self._runtime and self.isVisible() and not self.visibleRegion().isEmpty() and self._feedback == "normal" and
                self.spec.get("motion", "none") != "none" and self._drivers()["active"])

    def _animate(self):
        if not self._moving():
            self._timer.stop()
            return
        direction = -1 if self.spec.get("motion") == "signed" and self._value < 0 else 1
        motion = self.spec.get("motion")
        magnitude = self._drivers()["magnitude"]
        speed = .15 + .75 * magnitude if motion == "signed" else .3 if motion == "compressor" and self._value == 3 else .55
        if self.spec["type"] == "Motor" and self.properties.get("feedbackMode") == "运行位":  # i18n: value
            speed = .55
        self._phase = (self._phase + direction * speed * .05) % 1
        self._refresh()

    def _refresh(self):
        if self._moving():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self._render_svg()
        if self.spec["type"] == "PressureGauge":
            caption, _ = self._footer()
            detail = (self._reading() + " " + str(self.properties["unit"])).strip() if self._value is not None else caption
            if self._value is not None and caption:
                detail += " " + caption
            title = tr(str(self.properties["title"]))
            self.setToolTip(title + ": " + detail)
            self.setAccessibleName(title)
            self.setAccessibleDescription(detail)
        self.update()

    def _reading(self):
        if self._value is None:
            return "—"
        if self.spec["mode"] in ("word", "timing"):
            return f"0x{self._value:0{self._profile()['width']//4}X}"
        if self.spec["mode"] == "encoder":
            direction = tr("方向未知") if self._encoder_direction is None else tr("正向") if self._encoder_direction > 0 else tr("反向") if self._encoder_direction < 0 else tr("已停止")
            return tr("%1 计数 · %2 圈 · %3", self._value, f"{self._value / self.properties['pulsesPerTurn']:.3f}", direction)
        if self.spec["mode"] == "cells":
            low, high = min(self._value), max(self._value)
            return tr("最低 C%1 %2 V · 最高 C%3 %4 V · Δ %5 mV", self._value.index(low)+1, f"{low:.3f}", self._value.index(high)+1, f"{high:.3f}", f"{(high-low)*1000:.1f}")
        if self.spec["mode"] == "supply":
            return f"{self._value['voltage']:.2f} V · {self._value['current']:.3f} A · {self._value['mode']}"
        if self.spec["type"] == "Motor" and self.properties.get("feedbackMode") == "运行位":  # i18n: value
            return tr("运行") if self._value else tr("已停止")
        if self.spec["type"] == "Cylinder" and self.properties.get("feedbackMode") == "端位状态":  # i18n: value
            return (tr("两端未到位"), tr("缩回"), tr("伸出"))[int(self._value)]
        if self.spec["mode"] == "flags":
            english = language() == "en_US"
            if self._value == 0:
                return self.spec["clearLabelEn"] if english else self.spec["clearLabel"]
            labels = self.spec["flagsEn"] if english else self.spec["flags"]
            return (", " if english else "、").join(label for bit, label in enumerate(labels) if int(self._value) & (1 << bit))  # i18n: ignore (localized separator)
        states = self.spec.get("statesEn" if language() == "en_US" else "states", [])
        if self.spec["mode"] in ("state", "bits") and 0 <= self._value < len(states):
            return states[int(self._value)]
        if self.spec["mode"] == "byte":
            return f"0x{int(self._value):02X}"
        places = max(0, min(6, int(self.properties["decimals"])))
        return f"{self._value:.{places}f}"

    def _render_svg(self):
        dark = isDarkTheme()
        colors = dict(ink="#e7eef7" if dark else "#23364b", edge="#73889e", muted="#94a3b8",
                      body="#273b50" if dark else "#e2eaf2", surface="#172637" if dark else "#ffffff",
                      accent="#38a9ee", liquid="#29b9dc", warm="#f59e0b", danger="#ef5350",
                      green="#35bd86", yellow="#f2cf52", grain="#c99857")
        svg = self.spec["svg"]
        reading = self._reading()
        tokens = {**colors, "reading": escape(reading), "unit": escape(str(self.properties["unit"])),
                  "degrees": str(self._value if isinstance(self._value, (int, float)) else 0),
                  "minLabel": f'{float(self.properties["minimum"]):g}',
                  "maxLabel": f'{float(self.properties["maximum"]):g}'}
        if self.spec["type"] == "PressureGauge":
            tokens["readingSize"] = format(min(28, 180 / len(reading)), ".8g")
        if self.spec["mode"] == "supply":
            tokens.update(voltageText=f"{self._value['voltage']:.2f}" if self._value else "—", currentText=f"{self._value['current']:.3f}" if self._value else "—",
                          cvOn=int(bool(self._value) and self._value['mode']=='CV'), ccOn=int(bool(self._value) and self._value['mode']=='CC'))
        if self.spec["mode"] == "encoder":
            tokens.update(encoderAngle=(self._value % self.properties['pulsesPerTurn']) / self.properties['pulsesPerTurn'] * 360 if self._value is not None else 0,
                          forwardOn=int(self._encoder_direction == 1), reverseOn=int(self._encoder_direction == -1))
        if self.spec["mode"] in ("word", "timing", "cells"):
            tokens["items"] = self._render_items(tokens)
        drivers = self._drivers()
        for name, (driver, start, end) in self.spec.get("slots", {}).items():
            tokens[name] = format(start + (end - start) * drivers.get(driver, 0), ".8g")
        self._renderer.load(QByteArray(_svg_tokens(svg, tokens).encode("utf-8")))

    def _render_items(self, theme):
        items = []
        mode = self.spec["mode"]
        if mode in ("word", "timing"):
            profile = self._profile()
            width = profile["width"]
            for index, bit in enumerate(profile["bits"]):
                local = dict(theme, name=escape(bit["name"]), color=bit["color"])
                if mode == "word":
                    columns = 4 if width == 16 else 2
                    column_width = 304 / columns
                    local.update(
                        x=8 + (index % columns) * column_width,
                        y=8 + (index // columns) * 36,
                        w=column_width - 4,
                        nameSize=_bit_name_size(bit["name"], column_width - 4 - 28, 11),
                        lit=int(self._value is not None and bool(self._value & (1 << index))),
                    )
                else:
                    height = 144 / width
                    trace = []
                    previous = None
                    samples = self._history
                    if not self._runtime:
                        samples = [self._value] if self._value is not None else []
                    offset = 32 - len(samples)
                    step = 228 / 32
                    for sample_index, sample in enumerate(samples):
                        if sample is None:
                            previous = None
                            continue
                        x = 82 + (offset + sample_index) * step
                        y = height * (.2 if sample & (1 << index) else .8)
                        if previous is None:
                            trace.append(f"M{x:.6g},{y:.6g}")
                        else:
                            trace.append(f"H{x:.6g}V{y:.6g}")
                        trace.append(f"H{x + step:.6g}")
                        previous = sample
                    local.update(
                        y=8 + index * height,
                        h=height,
                        labelY=.70 * height,
                        fontSize=_bit_name_size(bit["name"], 70, min(11, .77 * height)),
                        trace=" ".join(trace),
                    )
                items.append(_svg_tokens(self.spec["itemSvg"], local))
        elif self._value is not None:
            count = len(self._value)
            columns = min(count, math.ceil(math.sqrt(2 * count)))
            rows = math.ceil(count / columns)
            low, high = min(self._value), max(self._value)
            for index, value in enumerate(self._value):
                column_width = 304 / columns
                row_height = 144 / rows
                width = column_width - min(2, column_width * .1)
                height = row_height - min(2, row_height * .1)
                outline = theme["muted"]
                if low != high:
                    if value == low:
                        outline = theme["accent"]
                    elif value == high:
                        outline = theme["warm"]
                local = dict(
                    theme,
                    x=8 + (index % columns) * column_width,
                    y=8 + (index // columns) * row_height,
                    w=width,
                    h=height,
                    cx=width / 2,
                    nameY=.39 * height,
                    valueY=.79 * height,
                    nameSize=min(11, .30 * height, .20 * width),
                    valueSize=min(16, .33 * height, .23 * width),
                    name=f"C{index + 1}",
                    valueText=f"{value:.3f}",
                    outline=outline,
                )
                items.append(_svg_tokens(self.spec["itemSvg"], local))
        return "".join(items)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    @staticmethod
    def _caption(painter, rect, text):
        painter.save()
        width = QFontMetricsF(painter.font()).horizontalAdvance(text)
        if width > rect.width():
            font = painter.font()
            font.setPointSizeF(max(6, font.pointSizeF() * rect.width() / width))
            painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()

    def _footer(self):
        status = {"normal": tr("正常"), "pending": tr("待数据"), "abnormal": tr("数据异常")}[self._feedback]
        reading = self._reading()
        state_feedback = ((self.spec["type"] == "Motor" and self.properties.get("feedbackMode") == "运行位") or  # i18n: value
                          (self.spec["type"] == "Cylinder" and self.properties.get("feedbackMode") == "端位状态"))  # i18n: value
        if self.spec["mode"] == "number" and not state_feedback and self._value is not None:
            reading += " " + str(self.properties["unit"])
        kind = self.spec["type"]
        if self._value is not None:
            if kind in ("FlowMeter", "FlowPipe", "Tachometer", "Motor", "Mixer", "BeltConveyor", "ScrewConveyor") and self.properties.get("feedbackMode") != "运行位":  # i18n: value
                reading += " " + (tr("正向") if self._value > 0 else tr("反向") if self._value < 0 else tr("零流量") if kind in ("FlowMeter", "FlowPipe") else tr("已停止"))
            elif kind == "PowerMeter":
                reading += " " + (tr("输入") if self._value >= 0 else tr("输出"))
            drivers = self._drivers()
            if drivers["lowAlarm"] or drivers["highAlarm"]:
                reading += " " + (tr("低限报警") if drivers["lowAlarm"] else tr("高限报警"))
        alarm = self._value is not None and bool(drivers["lowAlarm"] or drivers["highAlarm"])
        state = self._reading()
        warning = alarm or state in (tr("故障"), tr("跳闸"))
        color = "#ef5350" if self._feedback == "abnormal" or warning else (
            "#94a3b8" if self._feedback == "pending" else "#e7eef7" if isDarkTheme() else "#23364b")
        if kind == "PressureGauge" and self._feedback == "normal":
            return ((tr("低限报警") if drivers["lowAlarm"] else tr("高限报警")) if alarm else ""), color
        return (reading if self._feedback == "normal" else status), color

    def paintEvent(self, event):
        if self._moving() and not self._timer.isActive():
            self._timer.start()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#e7eef7" if isDarkTheme() else "#23364b"))
        self._caption(painter, QRectF(2, 1, self.width()-4, 20), tr(str(self.properties["title"])))
        area = QRectF(2, 23, self.width()-4, max(1, self.height()-48))
        view = self._renderer.viewBoxF()
        scale = min(area.width() / max(1, view.width()), area.height() / max(1, view.height()))
        size = QRectF(0, 0, view.width() * scale, view.height() * scale)
        size.moveCenter(area.center())
        self._renderer.render(painter, size)
        caption, color = self._footer()
        painter.setPen(QColor(color))
        self._caption(painter, QRectF(2, self.height()-23, self.width()-4, 22), caption)
