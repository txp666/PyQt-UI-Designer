# coding: utf-8
from PyQt5.QtCore import QObject, pyqtSignal


class SignalBus(QObject):

    # designer signals
    widgetSelected = pyqtSignal(str)          # widget_id
    widgetDeselected = pyqtSignal()
    widgetPropertyChanged = pyqtSignal(str, str, object)  # widget_id, prop_name, value
    widgetAdded = pyqtSignal(str)             # widget_id
    widgetRemoved = pyqtSignal(str)           # widget_id
    canvasChanged = pyqtSignal()

    # project signals
    projectLoaded = pyqtSignal(str)           # project_path
    projectSaved = pyqtSignal(str)
    projectNew = pyqtSignal()

    # serial signals
    serialConnected = pyqtSignal(str)         # port_name
    serialDisconnected = pyqtSignal()
    serialDataReceived = pyqtSignal(dict)     # parsed data dict
    serialRawReceived = pyqtSignal(bytes)     # raw bytes
    serialDataSent = pyqtSignal(bytes)        # data that was sent
    serialError = pyqtSignal(str)

    # preview signals
    previewStarted = pyqtSignal()
    previewStopped = pyqtSignal()

    # notification signals
    showNotification = pyqtSignal(str, str, str, int)  # title, content, type, duration

    # app signals
    micaEnableChanged = pyqtSignal(bool)
    themeChanged = pyqtSignal()


signalBus = SignalBus()
