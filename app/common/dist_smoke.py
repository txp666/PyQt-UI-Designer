"""Opt-in lifecycle checks executed by the actual packaged application."""
import argparse
import json
from pathlib import Path
import platform
import sys
import time
import traceback

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QTimer, QtCriticalMsg, QtFatalMsg, qInstallMessageHandler
from app.common.metadata import APP_VERSION


class _MemoryPort:
    def __init__(self):
        self.is_open = True
        self.sent = []

    def write(self, data):
        self.sent.append(data)
        return len(data)

    def close(self):
        self.is_open = False


class DistributionSmokeTest:
    """Keep the test inside Nuitka's runtime; an external Python cannot import it."""

    @classmethod
    def from_arguments(cls, arguments):
        if not any(arg.startswith("--smoke-test-") for arg in arguments[1:]):
            return None
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--smoke-test-project", type=Path, required=True)
        parser.add_argument("--smoke-test-report", type=Path, required=True)
        options = parser.parse_args(arguments[1:])
        # Do not pass our diagnostic options on to QApplication.
        arguments[1:] = []
        return cls(options.smoke_test_project, options.smoke_test_report)

    def __init__(self, project, report):
        self.project = project.resolve()
        self.report = report.resolve()
        self.result = {"status": "running", "steps": [], "errors": [],
                       "cycles": 0, "preview_cycles": 0, "widget_count": 0,
                       "widget_types": [], "exception_count": 0,
                       "compiled_runtime": "__compiled__" in globals(),
                       "version": APP_VERSION, "platform": sys.platform,
                       "architecture": platform.machine()}
        self._closed = False
        self._old_exception_hook = sys.excepthook
        self._old_unraisable_hook = sys.unraisablehook
        sys.excepthook = self._exception
        sys.unraisablehook = self._unraisable
        self._old_message_handler = qInstallMessageHandler(self._qt_message)
        self._write_report()

    def _write_report(self):
        self.result["exception_count"] = len(self.result["errors"])
        self.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.report.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.result, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        temporary.replace(self.report)

    def _exception(self, kind, value, trace):
        self.result["errors"].append("".join(traceback.format_exception(kind, value, trace)))
        self._write_report()

    def _unraisable(self, event):
        self._exception(event.exc_type, event.exc_value, event.exc_traceback)

    def _qt_message(self, kind, context, message):
        if kind in (QtCriticalMsg, QtFatalMsg) or any(fragment in message for fragment in (
            "QObject::", "QThread: Destroyed", "QBasicTimer::", "QTimer::",
            "wrapped C/C++ object", "has been deleted",
        )):
            self.result["errors"].append(f"Qt: {message}")
            self._write_report()
        if self._old_message_handler is not None:
            self._old_message_handler(kind, context, message)
        elif sys.stderr is not None:
            print(message, file=sys.stderr, flush=True)

    def start(self, app, window):
        self.app, self.window = app, window
        app.setQuitOnLastWindowClosed(False)
        self._deadline = QTimer(app)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._timed_out)
        self._deadline.start(45000)
        self._steps = [("load_demo", self._load_demo)]
        for fixture in ("demo", "registry"):
            if fixture == "registry":
                self._steps.append(("load_registry", self._load_registry))
            for cycle in range(1, 4):
                self._steps.append((f"{fixture}_start_{cycle}", self._start_preview))
                if fixture == "registry" and cycle == 1:
                    # Real sockets inside the compiled runtime: QtNetwork must be bundled.
                    self._steps.extend([
                        ("tcp_loopback_listen", self._tcp_loopback_listen),
                        ("tcp_loopback_exchange", self._tcp_loopback_exchange),
                        ("tcp_loopback_close", self._tcp_loopback_close),
                    ])
                self._steps.extend([
                    (f"{fixture}_receive_and_send_{cycle}", self._exercise_preview),
                    (f"{fixture}_theme_and_title_{cycle}", self._change_theme_and_title),
                    (f"{fixture}_stop_{cycle}", self._stop_preview),
                    (f"{fixture}_retired_signals_{cycle}", self._exercise_retired_widgets),
                ])
            self._steps.append((f"{fixture}_export", self._export))
        self._steps.extend([
            ("start_before_close", self._start_preview),
            ("receive_before_close", self._exercise_preview),
            ("select_canvas_item", self._select_canvas_item),
            ("close_window", self._close_window),
        ])
        QTimer.singleShot(100, self._advance)

    def _timed_out(self):
        self.result["errors"].append("Application lifecycle smoke test timed out")
        self._write_report()
        self.app.exit(1)

    def _advance(self):
        if self.result["errors"]:
            self.app.exit(1)
            return
        if not self._steps:
            self.app.exit(0)
            return
        name, action = self._steps.pop(0)
        try:
            action()
            if not self.result["errors"]:
                self.result["steps"].append(name)
            self._write_report()
        except BaseException:
            self._exception(*sys.exc_info())
        # Give paint events, queued slots and deferred deletes a real event-loop turn.
        QTimer.singleShot(100, self._advance)

    def _load_demo(self):
        from app.core.data_binding import bindingEngine
        from app.core.serial_manager import serialManager
        self.engine, self.serial = bindingEngine, serialManager
        self._mode = "demo"
        self.window._project_mgr.load_to_scene(self.window.designer_interface.scene,
                                               str(self.project))
        self.window.designer_interface.app_name = self.window._project_mgr.current.app_name
        self.window._update_title()
        self.window.switchTo(self.window.preview_interface)
        self.preview = self.window.preview_interface

    def _load_registry(self):
        from app.core.project import ProjectData
        from app.core.widget_registry import registry
        project = ProjectData()
        project.canvas_height = 1600
        for index, meta in enumerate(registry.all()):
            project.widgets.append({
                "id": f"all_{meta.type_name}", "type": meta.type_name,
                "properties": meta.get_default_props(),
                "geometry": {"x": 10 + (index % 4) * 280, "y": 10 + (index // 4) * 200,
                             "w": 260, "h": 180},
            })
        self.result["widget_types"] = sorted(meta.type_name for meta in registry.all())
        assert len(self.result["widget_types"]) == 28
        path = self.report.with_suffix(".uidp")
        path.write_text(json.dumps(project.to_dict(), ensure_ascii=False), encoding="utf-8")
        self.window._project_mgr.load_to_scene(self.window.designer_interface.scene, str(path))
        self.window.designer_interface.app_name = project.app_name
        self._mode = "registry"

    def _start_preview(self):
        self.preview._start_preview()
        assert self.preview._running and self.engine._active
        self.widgets = dict(self.engine._widget_map)
        required = ({"serial", "temperature", "receive", "live_table", "event_log", "start"}
                    if self._mode == "demo"
                    else {f"all_{name}" for name in self.result["widget_types"]})
        assert required <= self.widgets.keys(), f"Demo missing widgets: {required - self.widgets.keys()}"
        self.result["widget_count"] = len(self.widgets)
        self.result["preview_cycles"] += 1
        self.port = _MemoryPort()
        self.serial._port = self.port
        self.serial.connected.emit("PACKAGED_SMOKE")
        self.serial.connectionChanged.emit(True)

    def _emit_serial_events(self):
        self.serial.connected.emit("PACKAGED_SMOKE")
        self.serial.connectionChanged.emit(True)
        self.serial.rawReceived.emit(b"temperature=26.5,pressure=42,running=1,setpoint=60\n")
        self.serial.dataReceived.emit(
            {"temperature": 26.5, "pressure": 42, "running": 1, "setpoint": 60})
        self.serial.dataSent.emit(b"PACKAGED_SMOKE_TX\n")
        self.serial.error.emit("PACKAGED_SMOKE_ERROR")

    def _exercise_preview(self):
        self._emit_serial_events()
        receive, log, table = (("receive", "event_log", "live_table") if self._mode == "demo"
                               else ("all_DataRecvCard", "all_LogBox", "all_DataTable"))
        assert "temperature=26.5" in self.widgets[receive]._output.toPlainText()
        assert "temperature=26.5" in self.widgets[log]._output.toPlainText()
        assert self.widgets[table]._table.rowCount() >= 4
        assert self.port.sent == [], "Receiving bound data must not transmit commands"
        if self._mode == "demo":
            assert self.widgets["temperature"]._value_label.text() == "26.5"
            self.widgets["start"].click()
            assert self.port.sent == [b"START\r\n"], self.port.sent

    def _wait_for(self, predicate, what):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        assert predicate(), f"Timed out waiting for {what}"

    def _tcp_loopback_listen(self):
        from app.core.comm_manager import commHub
        from app.core.tcp_runtime import TcpHandler
        self.hub = commHub
        card = self.widgets["all_TcpConfigCard"]
        assert card._handler is commHub.tcp
        assert commHub.tcp.connect("127.0.0.1", 0, mode="服务端")
        assert "监听中" in card._status.text(), card._status.text()
        self.tcp_received = []
        self.tcp_client = TcpHandler()
        self.tcp_client.rawReceived.connect(self.tcp_received.append)
        assert self.tcp_client.connect("127.0.0.1", commHub.tcp.port)

    def _tcp_loopback_exchange(self):
        card = self.widgets["all_TcpConfigCard"]
        self._wait_for(lambda: self.tcp_client.is_connected and self.hub.tcp.peer_count == 1,
                       "the loopback TCP client")
        assert "1 客户端" in card._status.text(), card._status.text()
        assert card._connect_btn.isEnabled() and card._connect_btn.text() == "断开"
        assert self.tcp_client.send(b"tcp_temperature=31.5\n")
        receive, log = self.widgets["all_DataRecvCard"], self.widgets["all_LogBox"]
        self._wait_for(lambda: "tcp_temperature=31.5" in receive._output.toPlainText(),
                       "a TCP frame to reach the receive card")
        assert "tcp_temperature=31.5" in log._output.toPlainText()
        # One command goes out over every connected link: the serial port and TCP.
        assert self.hub.send(b"PING\n")
        self._wait_for(lambda: b"".join(self.tcp_received).endswith(b"PING\n"),
                       "the command to reach the TCP client")
        assert self.port.sent == [b"PING\n"], self.port.sent
        self.port.sent.clear()
        self.result["tcp_loopback"] = True

    def _tcp_loopback_close(self):
        card = self.widgets["all_TcpConfigCard"]
        self.tcp_client.disconnect()
        self.tcp_client.deleteLater()
        self.hub.tcp.disconnect()
        assert not self.hub.tcp.is_active and self.hub.is_connected
        assert card._connect_btn.isEnabled() and card._connect_btn.text() == "连接"
        assert card._status.text() == "未连接", card._status.text()

    def _change_theme_and_title(self):
        from PyQt5.QtGui import QIcon
        from qfluentwidgets import Theme, setTheme
        setTheme(Theme.DARK, save=False)
        setTheme(Theme.LIGHT, save=False)
        self.window._update_title()
        self.window.setWindowTitle(f"Packaged preview lifecycle {self.result['cycles'] + 1}")
        self.window.setWindowIcon(QIcon(self.window.windowIcon().pixmap(32, 32)))
        assert not self.window.grab().isNull()

    def _stop_preview(self):
        self.retired = tuple(self.preview._preview_canvas._widgets)
        self.preview._stop_preview()
        assert not self.port.is_open and not self.serial.is_connected
        assert not self.preview._running and not self.engine._active
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def _exercise_retired_widgets(self):
        assert all(sip.isdeleted(widget) for widget in self.retired)
        assert not self.engine._widget_map
        self._emit_serial_events()
        self.serial.disconnect()
        self.preview._stop_preview()
        self._change_theme_and_title()
        self.result["cycles"] += 1

    def _export(self):
        from app.core.code_generator import generate_project
        project = self.window._project_mgr.export_scene_data(
            self.window.designer_interface.scene, self.window.designer_interface.app_name)
        output = self.report.parent / (self.report.stem + f"-{self._mode}-export")
        generate_project(project, str(output))
        for source in output.glob("*.py"):
            compile(source.read_text(encoding="utf-8"), str(source), "exec")
        assert (output / "main.py").is_file() and (output / "ui.py").is_file()
        self.result["exported"] = True

    def _close_window(self):
        import threading
        import time
        from PyQt5.QtCore import QThread
        from app.common import update_checker

        entered, cancelled = threading.Event(), threading.Event()

        class DelayedResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self):
                entered.set()
                deadline = time.monotonic() + 5
                while not QThread.currentThread().isInterruptionRequested():
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Update check was not cancelled during window close")
                    time.sleep(0.01)
                cancelled.set()
                time.sleep(0.05)
                return b'{"tag_name": "v0.0.0"}'

        self.window.grab().save(str(self.report.with_suffix(".png")))
        original_urlopen, thread = update_checker.urlopen, None
        contexts = []

        def delayed_urlopen(*_args, **kwargs):
            contexts.append(kwargs.get("context"))
            return DelayedResponse()

        try:
            update_checker.urlopen = delayed_urlopen
            self.window.setting_interface._check_update()
            thread = self.window.setting_interface._update_thread
            assert entered.wait(5) and thread.isRunning(), "Update worker did not start"
            # The bundled OpenSSL cannot find the build machine's CA files on a user's computer.
            assert type(contexts[0]).__module__.startswith("truststore"), contexts
            self.result["system_trust_store"] = True
            assert self.window.close(), "Normal window close was rejected"
            assert cancelled.is_set() and not thread.isRunning(), "Update worker survived window close"
            self.result["cancelled_update_check"] = True
            self.result["steps"].append("cancelled_update_check")
        finally:
            if thread is not None and not sip.isdeleted(thread) and thread.isRunning():
                thread.requestInterruption()
                thread.wait(5000)
            update_checker.urlopen = original_urlopen
        assert not self.window.isVisible() and not self.preview._running
        assert not self.port.is_open and not self.serial.is_connected
        self._closed = True

    def _select_canvas_item(self):
        # DesignScene intentionally has no QObject parent and can outlive its
        # view. Keep that ordering and a real selection through window teardown.
        designer = self.window.designer_interface
        self.scene, self.design_view = designer.scene, designer._view
        self.window.switchTo(designer)
        self.scene.clearSelection()
        item = self.scene.get_item_by_id("all_Label")
        assert item is not None
        item.setSelected(True)
        assert item in self.scene.selectedItems()
        assert designer._prop_editor._current_item is item
        assert self.preview._running
        self.result["selected_widget"] = item.widget_id

    def finish(self, exit_code):
        """Called after main.py has destroyed the window and drained Qt deletes."""
        self._deadline.stop()
        try:
            assert self._closed and sip.isdeleted(self.window), "Window was not normally closed and destroyed"
            assert sip.isdeleted(self.design_view) and not sip.isdeleted(self.scene)
            assert self.scene.selectedItems(), "Scene selection was lost before teardown"
            self.scene.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            assert sip.isdeleted(self.scene)
            if not self.result["errors"]:
                self.result["steps"].append("destroyed_selected_scene")
            self._emit_serial_events()
            self.serial.disconnect()
            from qfluentwidgets import Theme, setTheme
            setTheme(Theme.DARK, save=False)
            setTheme(Theme.LIGHT, save=False)
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
            if not self.result["errors"]:
                self.result["steps"].append("destroyed_window_signals")
        except BaseException:
            self._exception(*sys.exc_info())
        passed = exit_code == 0 and self._closed and not self.result["errors"]
        self.result["status"] = "passed" if passed else "failed"
        self.result["exit_code"] = 0 if passed else 1
        self._write_report()
        sys.excepthook = self._old_exception_hook
        sys.unraisablehook = self._old_unraisable_hook
        qInstallMessageHandler(self._old_message_handler)
        return self.result["exit_code"]
