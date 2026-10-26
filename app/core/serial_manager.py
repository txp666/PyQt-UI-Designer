# coding: utf-8
"""The designer's serial link: the serial handler owned by the shared communication hub."""
from app.core.comm_manager import commHub
from app.core.serial_runtime import (  # noqa: F401  (re-exported for callers of this module)
    SerialHandler, SerialReaderThread, _list_all_ports, HAS_SERIAL,
)

serialManager = commHub.serial
