# coding: utf-8
"""Designer adapter for the shared communication hub.

Every link (serial, TCP, MQTT) reports through the hub, and the hub publishes on the
signal bus, so designer widgets keep listening to one set of signals.
"""
from app.common.signal_bus import signalBus
from app.core.comm_runtime import CommHub


class CommManager(CommHub):
    def __init__(self):
        super().__init__()
        self.rawReceived.connect(signalBus.serialRawReceived)
        self.dataReceived.connect(signalBus.serialDataReceived)
        self.dataSent.connect(signalBus.serialDataSent)
        self.connected.connect(signalBus.serialConnected)
        self.disconnected.connect(signalBus.serialDisconnected)
        self.error.connect(signalBus.serialError)


commHub = CommManager()
