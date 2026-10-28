"""A slider's command, sent once when a drag lets go: shared by preview and standalone applications."""
from PyQt5.QtCore import QEvent, QObject, Qt


class SendOnRelease(QObject):
    """Calls send(value) whenever a qfluentwidgets Slider's value changes, except while the mouse is down on
    it: a drag sends once, when it lets go, instead of a command for every value the handle passes. Keys and
    the wheel move in steps and send each one.

    That Slider never sets QSlider.isSliderDown(), and a drag that starts on the groove emits no
    pressed/released signals, so the mouse is watched on the slider and its handle."""

    def __init__(self, slider, send):
        super().__init__(slider)
        self._slider, self._send = slider, send
        self._held = False
        self._press_value = slider.value()
        slider.installEventFilter(self)
        slider.handle.installEventFilter(self)
        slider.valueChanged.connect(self._value_changed)

    def _value_changed(self, value):
        if not self._held:
            self._send(value)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease) and event.button() == Qt.LeftButton:
            if kind == QEvent.MouseButtonPress:
                self._held = True
                self._press_value = self._slider.value()  # before a press on the groove moves it
            elif self._held:
                self._held = False
                if self._slider.value() != self._press_value:
                    self._send(self._slider.value())
        return False
