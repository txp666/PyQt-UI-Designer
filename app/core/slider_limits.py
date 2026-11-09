"""A slider with its minimum and maximum at its ends (the showRange property), shared by preview and exported
apps. Code that wires or binds a slider goes through slider_of(), which gives the Slider in both cases."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QHBoxLayout
from qfluentwidgets import CaptionLabel, Slider


class SliderWithLimits(QWidget):
    """A Slider in a row with its minimum on the left and its maximum on the right, both as captions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.slider = Slider(Qt.Horizontal, self)
        self._min_label = CaptionLabel(self)
        self._max_label = CaptionLabel(self)
        # Hidden labels take no room in the row, so with the limits off the slider fills the widget.
        self._min_label.hide()
        self._max_label.hide()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self._min_label, 0, Qt.AlignVCenter)
        row.addWidget(self.slider, 1)
        row.addWidget(self._max_label, 0, Qt.AlignVCenter)
        # The labels follow the range however it is set: the slider emits rangeChanged on every change.
        self.slider.rangeChanged.connect(self._show_limits)
        self._show_limits(self.slider.minimum(), self.slider.maximum())

    def set_show_range(self, shown):
        self._min_label.setVisible(bool(shown))
        self._max_label.setVisible(bool(shown))

    def _show_limits(self, low, high):
        self._min_label.setText(str(low))
        self._max_label.setText(str(high))


def slider_of(widget):
    """The Slider a designed slider widget is: the widget itself, or the one inside SliderWithLimits."""
    return widget.slider if isinstance(widget, SliderWithLimits) else widget
