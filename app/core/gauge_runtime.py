"""Gauge meter shared by the designer preview and exported applications."""
import math

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QFontMetricsF
from PyQt5.QtWidgets import QWidget
from qfluentwidgets import isDarkTheme, qconfig

from .signal_lifetime import SignalConnections


class GaugeMeter(QWidget):
    """A 270° dial: value and unit in the middle, title below, range at the two ends."""

    START, SPAN = 225.0, -270.0  # degrees, counter-clockwise from 3 o'clock
    MARGIN = 4.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._min_val = 0.0
        self._max_val = 100.0
        self._title = "仪表"
        self._unit = ""
        self.setMinimumSize(80, 80)
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self.update)

    def set_value(self, v):
        self._value = max(self._min_val, min(self._max_val, v))
        self.update()

    def set_range(self, lo, hi):
        self._min_val = lo
        self._max_val = max(lo, hi)
        self.set_value(self._value)

    def set_title(self, t):
        self._title = t
        self.update()

    def set_unit(self, u):
        self._unit = u
        self.update()

    def _font(self, px, weight=QFont.Normal):
        font = QFont(self.font().family())
        font.setPixelSize(max(1, int(px)))
        font.setWeight(weight)
        return font

    @staticmethod
    def _number(v):
        return f"{v:g}" if float(v).is_integer() else f"{v:.1f}"

    def _geometry(self):
        """Radius, pen width, centre and range-label size that fit the whole dial in the widget.
        The open bottom of the arc is shorter than the top, so the dial is centred on its own
        height (top of the ring to the range labels), not on the circle."""
        w, h, m = self.width(), self.height(), self.MARGIN
        low = math.sin(math.radians(45))  # how far below the centre the arc ends reach, per radius
        # pen = 0.11 r, range label = 0.12 r but at least 10 px, 2 px gap: the largest r that fits
        r_h = (h - 2 * m - 2) / (1 + low + 0.11 + 0.12)
        if 0.12 * r_h < 10:
            r_h = (h - 2 * m - 2 - 10) / (1 + low + 0.11)
        r = max(8.0, min((w - 2 * m) / 2.11, r_h))
        pen = max(4.0, 0.11 * r)
        label = max(10.0, 0.12 * r)
        height = pen / 2 + r + r * low + pen / 2 + 2 + label
        cy = (h - height) / 2 + pen / 2 + r
        return r, pen, QPointF(w / 2, cy), label

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        dark = isDarkTheme()
        text_c = QColor("#f3f3f3" if dark else "#1e1e1e")
        sub_c = QColor("#b3b3b3" if dark else "#606060")
        r, pen_w, c, label_px = self._geometry()
        arc = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)

        track = QPen(QColor("#4a4a4a" if dark else "#e3e3e3"), pen_w, Qt.SolidLine, Qt.RoundCap)
        p.setPen(track)
        p.drawArc(arc, int(self.START * 16), int(self.SPAN * 16))
        rng = self._max_val - self._min_val
        ratio = (self._value - self._min_val) / rng if rng > 0 else 0.0
        if ratio > 0:
            fill = QPen(QColor("#4cc2ff" if dark else "#0078d4"), pen_w, Qt.SolidLine, Qt.RoundCap)
            p.setPen(fill)
            p.drawArc(arc, int(self.START * 16), int(self.SPAN * ratio * 16))

        # value with its unit on one baseline, shrunk to fit inside the ring
        inner = 2 * (r - pen_w) * 0.86
        value_px = 0.42 * r
        value_txt, unit_txt = f"{self._value:.1f}", self._unit
        while True:
            vf, uf = self._font(value_px, QFont.Bold), self._font(value_px * 0.45, QFont.Medium)
            vm, um = QFontMetricsF(vf), QFontMetricsF(uf)
            gap = value_px * 0.12 if unit_txt else 0.0
            total = vm.horizontalAdvance(value_txt) + gap + (um.horizontalAdvance(unit_txt) if unit_txt else 0.0)
            if total <= inner or value_px <= 8:
                break
            value_px *= 0.92
        baseline = c.y() + vm.capHeight() / 2
        x = c.x() - total / 2
        p.setFont(vf)
        p.setPen(text_c)
        p.drawText(QPointF(x, baseline), value_txt)
        if unit_txt:
            p.setFont(uf)
            p.setPen(sub_c)
            p.drawText(QPointF(x + vm.horizontalAdvance(value_txt) + gap, baseline), unit_txt)

        if self._title:
            tf = self._font(max(10.0, 0.16 * r), QFont.Medium)
            p.setFont(tf)
            p.setPen(sub_c)
            tm = QFontMetricsF(tf)
            title = tm.elidedText(self._title, Qt.ElideRight, inner)
            top = baseline + vm.descent() + 0.08 * r
            p.drawText(QRectF(c.x() - inner / 2, top, inner, tm.height()), Qt.AlignHCenter | Qt.AlignTop, title)

        # range at the two open ends of the ring
        lf = self._font(label_px)
        p.setFont(lf)
        p.setPen(sub_c)
        lm = QFontMetricsF(lf)
        low = math.sin(math.radians(45))
        y = c.y() + r * low + pen_w / 2 + 2
        for v, dx in ((self._min_val, -r * low), (self._max_val, r * low)):
            txt = self._number(v)
            wd = lm.horizontalAdvance(txt) + 4
            p.drawText(QRectF(c.x() + dx - wd / 2, y, wd, lm.height()), Qt.AlignHCenter | Qt.AlignTop, txt)
        p.end()
