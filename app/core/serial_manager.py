# coding: utf-8
"""Designer adapter for the shared serial runtime."""
from app.common.signal_bus import signalBus
from app.core.serial_runtime import (
    SerialHandler, SerialReaderThread, _list_all_ports, HAS_SERIAL,
)


class SerialManager(SerialHandler):
    def __init__(self):
        super().__init__()
        self.rawReceived.connect(signalBus.serialRawReceived)
        self.dataReceived.connect(signalBus.serialDataReceived)
        self.dataSent.connect(signalBus.serialDataSent)
        self.connected.connect(signalBus.serialConnected)
        self.disconnected.connect(signalBus.serialDisconnected)
        self.error.connect(signalBus.serialError)


serialManager = SerialManager()
