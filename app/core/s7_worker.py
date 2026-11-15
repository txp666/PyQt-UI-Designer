"""One serial native-I/O worker per S7 connection, with no Qt dependency."""
from collections import deque
import threading
import time
from itertools import count

from .s7_native import NativeS7Client, S7Error

_SESSIONS = count(1)


def new_session_generation():
    return next(_SESSIONS)


def transport_error(error):
    return (not isinstance(error, S7Error) or bool(error.code & 0x000fffff)
            or error.code in (0x00800000, 0x01600000, 0x02000000))


class S7Worker(threading.Thread):
    """Only this thread touches its client. Failed writes are never retried."""
    def __init__(self, source_id, generation, config, publish, client_factory=NativeS7Client):
        super().__init__(name="S7-" + source_id, daemon=False)
        self.source_id, self.generation, self.config = source_id, generation, dict(config)
        self.session_generation = new_session_generation()
        self._publish, self._factory = publish, client_factory
        self._stop_requested = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._needs = ()
        self._writes = deque()
        self.connected = False

    def emit(self, kind, **payload):
        payload.update(sourceCardId=self.source_id, sessionGeneration=self.session_generation,
                       _workerGeneration=self.generation)
        self._publish(kind, payload)

    def set_needs(self, points):
        with self._lock:
            self._needs = tuple(dict(point) for point in points)
        self._wake.set()

    def write(self, request_id, point, value):
        with self._lock:
            if not self.connected or self._stop_requested.is_set():
                return False
            self._writes.append((request_id, dict(point), value))
        self._wake.set()
        return True

    def request_stop(self):
        self._stop_requested.set()
        self._wake.set()
        self._discard_writes()

    def _discard_writes(self):
        with self._lock:
            pending = list(self._writes)
            self._writes.clear()
        for request_id, _point, _value in pending:
            self.emit("write", requestId=request_id, status="disconnected", error="S7 connection closed")

    def _sample(self, point, quality, value=None, error=""):
        self.emit("sample", address=point["address"], dataType=point["dataType"], value=value,
                  quality=quality, timestamp=time.time(), error=error)

    def run(self):
        client = None
        due = {}
        try:
            while not self._stop_requested.is_set():
                self._wake.clear()
                if client is None:
                    try:
                        client = self._factory()
                        client.connect(self.config)
                        if self._stop_requested.is_set():
                            break
                        self.connected = True
                        self.session_generation = new_session_generation()
                        due.clear()
                        self.emit("state", connected=True, active=True, error="")
                    except (OSError, RuntimeError, ValueError) as error:
                        if client is not None:
                            client.close()
                            client = None
                        self.emit("state", connected=False, active=self.config["autoReconnect"], error=str(error))
                        if not self.config["autoReconnect"]:
                            break
                        self._stop_requested.wait(self.config["reconnectInterval"] / 1000)
                        continue
                with self._lock:
                    points = self._needs
                    write = self._writes.popleft() if self._writes else None
                now = time.monotonic()
                if write is not None:
                    request_id, point, value = write
                    try:
                        client.write(point, value)
                        self.emit("write", requestId=request_id, status="good", error="")
                        due = {key: 0 if key[:2] == (point["address"], point["dataType"]) else deadline
                               for key, deadline in due.items()}
                    except (OSError, RuntimeError, ValueError) as error:
                        lost = transport_error(error)
                        self.emit("write", requestId=request_id, status="unknown" if lost else "bad", error=str(error))
                        if lost:
                            self.connected = False
                            self._discard_writes()
                            client.close()
                            client = None
                            self.emit("state", connected=False, active=self.config["autoReconnect"], error=str(error))
                            if not self.config["autoReconnect"]:
                                break
                            self._stop_requested.wait(self.config["reconnectInterval"] / 1000)
                    continue
                live_keys = {(p["address"], p["dataType"], p["period"]) for p in points}
                due = {key: deadline for key, deadline in due.items() if key in live_keys}
                point = min((p for p in points if due.get((p["address"], p["dataType"], p["period"]), 0) <= now),
                            key=lambda p: due.get((p["address"], p["dataType"], p["period"]), 0), default=None)
                if point is None:
                    delay = min((max(0, deadline - now) for deadline in due.values()), default=0.2)
                    self._wake.wait(min(delay, 0.2))
                    continue
                key = point["address"], point["dataType"], point["period"]
                due[key] = now + (point["period"] or self.config["period"]) / 1000
                try:
                    value = client.read(point)
                    self._sample(point, "good", value)
                except (OSError, RuntimeError, ValueError) as error:
                    lost = transport_error(error)
                    self._sample(point, "disconnected" if lost else "bad", error=str(error))
                    if lost:
                        self.connected = False
                        self._discard_writes()
                        client.close()
                        client = None
                        self.emit("state", connected=False, active=self.config["autoReconnect"], error=str(error))
                        if not self.config["autoReconnect"]:
                            break
                        self._stop_requested.wait(self.config["reconnectInterval"] / 1000)
        finally:
            self.connected = False
            self._discard_writes()
            if client is not None:
                client.close()
            self.emit("state", connected=False, active=False, error="")
