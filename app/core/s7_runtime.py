"""Queued Qt bridge and demand collection for the shared native S7 worker."""
import time
import uuid
import weakref

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal

from .s7_values import encode_s7, s7_config, s7_point
from .s7_worker import S7Worker, new_session_generation
from .i18n import tr


def _stop_workers(workers, *_):
    for worker in workers:
        worker.request_stop()


class S7Link(QObject):
    sampleReceived = pyqtSignal(dict)
    writeCompleted = pyqtSignal(dict)
    stateChanged = pyqtSignal(bool, bool, str)  # connected, active/reconnecting, error
    _event = pyqtSignal(str, dict)

    def __init__(self, source_id, parent=None):
        super().__init__(parent)
        self.source_id = source_id
        self._generation = 0
        self._session_generation = 0
        self._worker = None
        self._workers = []
        self._needs = []
        self.is_connected = False
        self.is_active = False
        self.poll_period = 500
        self._event.connect(self._receive, Qt.QueuedConnection)
        self.destroyed.connect(lambda *_: _stop_workers(self._workers))

    @property
    def generation(self):
        return self._session_generation

    def connect(self, config):
        config = s7_config(config)
        self.disconnect()
        self.poll_period = config["period"]
        self._workers[:] = [worker for worker in self._workers if worker.is_alive()]
        self._generation += 1
        generation = self._generation
        reference = weakref.ref(self)

        def publish(kind, payload):
            link = reference()
            if link is not None:
                try:
                    link._event.emit(kind, payload)
                except RuntimeError:
                    pass  # the card was deleted while the last native operation finished

        self._worker = S7Worker(self.source_id, generation, config, publish)
        self._workers.append(self._worker)
        self._worker.set_needs(self._needs)
        self.is_active = True
        self.stateChanged.emit(False, True, "")
        self._worker.start()

    def disconnect(self):
        self._generation += 1
        self._session_generation = new_session_generation()
        if self._worker is not None:
            self._worker.request_stop()
            self._worker = None
        was_active = self.is_active or self.is_connected
        self.is_connected = self.is_active = False
        if was_active:
            self.stateChanged.emit(False, False, "")
        for point in self._needs:
            self.sampleReceived.emit({"sourceCardId": self.source_id, "address": point["address"],
                                      "dataType": point["dataType"], "value": None, "quality": "disconnected",
                                      "timestamp": time.time(), "sessionGeneration": self._session_generation})

    def set_needs(self, points):
        points = [s7_point(point) for point in points]
        if points == self._needs:
            return
        self._needs = points
        if self._worker is not None:
            self._worker.set_needs(points)

    def write(self, point, value):
        point = s7_point(point)
        encode_s7(value, point["dataType"])  # validate before accepting a user's write
        if not self.is_connected or self._worker is None:
            raise ValueError(tr("S7 未连接，命令未发送"))
        request_id = uuid.uuid4().hex
        if not self._worker.write(request_id, point, value):
            raise ValueError(tr("S7 未连接，命令未发送"))
        return request_id

    def _receive(self, kind, payload):
        if payload.pop("_workerGeneration", None) != self._generation:
            return
        if payload.get("sessionGeneration", 0) < self._session_generation:
            return
        self._session_generation = payload["sessionGeneration"]
        if kind == "sample":
            self.sampleReceived.emit(payload)
        elif kind == "write":
            self.writeCompleted.emit(payload)
        else:
            self.is_connected, self.is_active = payload["connected"], payload["active"]
            self.stateChanged.emit(self.is_connected, self.is_active, payload.get("error", ""))


class S7Poller(QObject):
    """Refresh visible binding/curve demands; the worker keeps the actual clock."""
    def __init__(self, hub, needs, parent=None):
        super().__init__(parent)
        self._hub, self._needs = hub, needs
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.refresh)

    def start(self):
        self.refresh()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        for link in self._hub.s7_links.values():
            link.set_needs([])

    def refresh(self):
        grouped = {}
        links = self._hub.s7_links
        if not links:
            return
        for source_id, point in self._needs():
            try:
                point = s7_point(point)
            except (TypeError, ValueError):
                continue
            key = point["address"], point["dataType"]
            existing = grouped.setdefault(source_id, {}).get(key)
            default_period = links[source_id].poll_period if source_id in links else 500
            if existing is None or (point["period"] or default_period) < (existing["period"] or default_period):
                grouped[source_id][key] = point
        for source_id, link in links.items():
            link.set_needs(list(grouped.get(source_id, {}).values()))


def wire_s7_commands(widget, type_name, props, hub, report_error):
    """Shared command wiring in preview and generated apps. Binding signals are blocked by their engines."""
    from .slider_limits import slider_of
    from .slider_release import SendOnRelease
    command = dict(props.get("s7Command") or {})

    def send(value):
        try:
            hub.write_s7(props.get("commandTargetId", ""), command, value)
        except (RuntimeError, ValueError) as error:
            report_error(error)

    if type_name == "PushButton":
        widget.clicked.connect(lambda *_: send(command.get("value", "1")))
    elif type_name == "ToggleSwitch":
        widget._switch.checkedChanged.connect(lambda checked: send(command.get("onValue", "1") if checked else command.get("offValue", "0")))
    elif type_name == "LineEdit":
        widget.returnPressed.connect(lambda: send(widget.text().strip()))
    elif type_name == "ComboBox":
        values = [line.strip() for line in props.get("commands", "").split("\n")]
        widget.currentIndexChanged.connect(lambda index: send(values[index] if 0 <= index < len(values) and values[index] else widget.currentText()) if index >= 0 else None)
    elif type_name == "Slider":
        SendOnRelease(slider_of(widget), send)
    elif type_name == "SpinBox":
        widget.valueChanged.connect(send)
