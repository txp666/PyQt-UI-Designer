"""Run the exported application with an in-memory serial device."""
import json
import math
from pathlib import Path
import runpy
import threading
import time


class SimulatedPort:
    """Small pyserial-compatible device used only by this demo entry point."""

    def __init__(self, port, **kwargs):
        if port != "DEMO":
            raise ValueError("模拟模式只支持 DEMO 端口")
        self.is_open = True
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._commands = bytearray()
        self._next_sample = 0.0
        self._sample = 0
        self._running = True
        self._temperature = 25.0
        self._pressure = 50.0
        self._setpoint = 50

    def _enqueue_sample(self):
        if self._running:
            self._sample += 1
            self._temperature = round(25 + 3 * math.sin(self._sample / 15), 2)
            self._pressure = round(self._setpoint + 18 * math.sin(self._sample / 10), 2)
        self._buffer.extend((json.dumps({
            "temperature": self._temperature,
            "pressure": self._pressure,
            "running": int(self._running),
            "setpoint": self._setpoint,
        }) + "\n").encode("utf-8"))
        self._next_sample = time.monotonic() + 0.2

    @property
    def in_waiting(self):
        with self._lock:
            if self.is_open and time.monotonic() >= self._next_sample:
                self._enqueue_sample()
            return len(self._buffer)

    def read(self, size=1):
        with self._lock:
            data = bytes(self._buffer[:size])
            del self._buffer[:size]
            return data

    def write(self, data):
        with self._lock:
            if not self.is_open:
                raise OSError("模拟串口已关闭")
            self._commands.extend(data)
            while b"\n" in self._commands:
                line, _, tail = self._commands.partition(b"\n")
                self._commands = bytearray(tail)
                command = line.strip().upper()
                if command == b"START":
                    self._running = True
                elif command == b"STOP":
                    self._running = False
                elif command != b"READ":
                    try:
                        value = float(command)
                        if not 20 <= value <= 80 or not value.is_integer():
                            raise ValueError
                    except ValueError:
                        self._buffer.extend(b'{"error":"Use START, STOP, READ or an integer from 20 to 80"}\n')
                        continue
                    self._setpoint = int(value)
                self._enqueue_sample()
            return len(data)

    def close(self):
        with self._lock:
            self.is_open = False
            self._buffer.clear()
            self._commands.clear()


def main():
    # Only the transport is replaced. The exported UI, reader thread, parser,
    # command generation and data binding all run unchanged.
    import serial_handler

    serial_handler.serial.Serial = SimulatedPort
    serial_handler._list_all_ports = lambda: [
        {"port": "DEMO", "description": "模拟设备（不连接硬件）"},
    ]
    runpy.run_path(str(Path(__file__).with_name("main.py")), run_name="__main__")


if __name__ == "__main__":
    main()
