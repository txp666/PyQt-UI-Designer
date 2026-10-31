"""External Qt subscriptions must end explicitly, including opaque compiled slots."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from app.core.code_generator import generate_project
from app.core.project import ProjectData

ROOT = Path(__file__).resolve().parent.parent


class SignalLifetimeTests(unittest.TestCase):
    def run_script(self, code, cwd=ROOT):
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(code)], cwd=cwd,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": ""},
            capture_output=True, text=True, encoding="utf-8", timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("LIFETIME_OK", result.stdout)

    def test_opaque_slots_release_receivers_and_cancel_queued_deliveries(self):
        self.run_script('''
            import gc
            import weakref
            from PyQt5.QtCore import QObject, QEvent, Qt, pyqtSignal
            from PyQt5.QtWidgets import QApplication
            from app.core.signal_lifetime import SignalConnections
            app = QApplication([])
            class Sender(QObject):
                changed = pyqtSignal(int)
            sender = Sender()
            calls = []
            for queued in (False, True):
                owner = QObject()
                group = SignalConnections(owner)
                group.connect(sender.changed, calls.append,
                              Qt.QueuedConnection if queued else Qt.AutoConnection)
                assert sender.receivers(sender.changed) == 1
                sender.changed.emit(7)
                owner.deleteLater()
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                assert not group._connections
                assert sender.receivers(sender.changed) == 0
                app.processEvents()
                sender.changed.emit(9)
                assert calls == ([] if queued else [7]), calls
                calls.clear()
                group.clear()
            owner = QObject()
            group = SignalConnections(owner)
            group.connect(sender.changed, calls.append)
            group.clear()
            group.connect(sender.changed, calls.append)
            sender.changed.emit(3)
            assert calls == [3]
            sender.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            owner.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            assert not group._connections
            class Target(QObject):
                def changed(self, value): pass
            sender = Sender()
            target = Target()
            ref = weakref.ref(target)
            group = SignalConnections(target)
            group.connect(sender.changed, target.changed)
            target.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            del target
            gc.collect()
            assert ref() is None
            print("LIFETIME_OK")
        ''')

    def test_all_host_widgets_release_serial_and_theme_subscriptions(self):
        self.run_script('''
            import sys
            from PyQt5.QtCore import QEvent
            from PyQt5.QtWidgets import QApplication
            from qfluentwidgets import qconfig
            from app.common.signal_bus import signalBus
            from app.core.serial_manager import serialManager
            from app.widgets.composite import DataRecvCard, LogDisplayBox, ModbusConfigCard
            from app.widgets.comm import DataTableWidget
            from app.widgets.chart import RealtimeLineChart, GaugeMeter
            from app.widgets.display import LEDIndicator, NumericDisplay, ImageDisplay
            from app.widgets.layout import (HBoxContainer, VBoxContainer, FlexContainer,
                                             GroupBoxContainer, TabContainer, CardContainer)
            from app.core.comm_manager import commHub
            from app.core.mqtt_card import MqttConfigCard
            from app.core.serial_card import SerialConfigCard
            from app.core.tcp_card import TcpConfigCard
            from app.core.theme_runtime import ThemeController
            app = QApplication([])
            errors = []
            sys.excepthook = lambda kind, value, tb: errors.append(str(value))
            kinds = [DataRecvCard, LogDisplayBox, ModbusConfigCard, DataTableWidget,
                     RealtimeLineChart, GaugeMeter, LEDIndicator, NumericDisplay,
                     ImageDisplay, HBoxContainer, VBoxContainer, FlexContainer,
                     GroupBoxContainer, TabContainer, CardContainer, SerialConfigCard,
                     TcpConfigCard, MqttConfigCard]
            signals = [signalBus.serialConnected, signalBus.serialDisconnected,
                       signalBus.serialDataReceived, signalBus.serialRawReceived,
                       signalBus.serialDataSent, signalBus.serialError]
            baseline = [signalBus.receivers(signal) for signal in signals]
            for cycle in range(3):
                widgets = [kind() for kind in kinds]
                chart = next(w for w in widgets if isinstance(w, RealtimeLineChart))
                chart.start_listening()
                chart._cursor_line.setPos(1)
                for card in widgets[-3:]:
                    card.set_serial_handler(commHub)
                    assert card._handler is getattr(commHub, card.LINK)
                controller = ThemeController(app, "Light")
                groups = [group for w in widgets + [controller] for name, group in vars(w).items()
                          if name.endswith("_connections")]
                assert len(groups) >= len(widgets)
                for w in widgets + [controller]:
                    w.deleteLater()
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                assert all(not group._connections for group in groups)
                assert [signalBus.receivers(s) for s in signals] == baseline
                signalBus.serialConnected.emit("TEST")
                signalBus.serialDisconnected.emit()
                signalBus.serialDataReceived.emit({"value": 1})
                signalBus.serialRawReceived.emit(b"value=1\\n")
                signalBus.serialDataSent.emit(b"READ")
                signalBus.serialError.emit("after destruction")
                qconfig.themeChangedFinished.emit()
                app.aboutToQuit.emit()
                app.processEvents()
                assert not errors, errors
            print("LIFETIME_OK")
        ''')

    def test_real_preview_rebuild_returns_global_receiver_counts_to_baseline(self):
        self.run_script('''
            import sys
            from PyQt5.QtCore import QEvent, Qt
            from PyQt5.QtTest import QTest
            from PyQt5.QtWidgets import QApplication
            from qfluentwidgets import qconfig
            from app.common.signal_bus import signalBus
            from app.core.serial_manager import serialManager
            from app.core.project import ProjectData
            from app.view.preview_interface import PreviewInterface
            app = QApplication([])
            errors = []
            sys.excepthook = lambda kind, value, tb: errors.append(str(value))
            project = ProjectData()
            project.widgets = [{"id": kind, "type": kind, "properties": {},
                                "geometry": {"x": 0, "y": 0, "w": 500, "h": 200}}
                               for kind in ("DataRecvCard", "LogBox", "ModbusConfigCard",
                                            "SerialConfigCard", "TcpConfigCard", "MqttConfigCard",
                                            "DataTable", "RealtimeChart")]
            preview = PreviewInterface()
            preview.set_project_data(project)
            signals = [signalBus.serialConnected, signalBus.serialDisconnected,
                       signalBus.serialDataReceived, signalBus.serialRawReceived,
                       signalBus.serialDataSent, signalBus.serialError]
            baseline = [signalBus.receivers(s) for s in signals]
            serial_baseline = serialManager.receivers(serialManager.connected)
            for cycle in range(4):
                QTest.mouseClick(preview._run_btn, Qt.LeftButton)
                app.processEvents()
                assert preview._running
                serialManager.connected.emit("TEST")
                serialManager.dataReceived.emit({"value": cycle})
                serialManager.rawReceived.emit(b"value=1\\n")
                serialManager.dataSent.emit(b"READ")
                qconfig.themeChangedFinished.emit()
                QTest.mouseClick(preview._stop_btn, Qt.LeftButton)
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                assert [signalBus.receivers(s) for s in signals] == baseline
                assert serialManager.receivers(serialManager.connected) == serial_baseline
                serialManager.disconnected.emit()
                serialManager.error.emit("after stop")
                qconfig.themeChangedFinished.emit()
                app.processEvents()
                assert not errors, errors
            preview.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            print("LIFETIME_OK")
        ''')

    def test_standalone_export_releases_cards_charts_and_data_bindings(self):
        project = ProjectData()
        project.widgets = [
            {"id": kind, "type": kind, "properties": {},
             "geometry": {"x": 0, "y": 0, "w": 300, "h": 150}}
            for kind in ("DataRecvCard", "LogBox", "ModbusConfigCard", "SerialConfigCard",
                         "TcpConfigCard", "MqttConfigCard",
                         "DataTable", "RealtimeChart", "LEDIndicator", "NumericDisplay",
                         "GaugeMeter", "ImageDisplay", "CardContainer", "HBoxLayout")
        ]
        project.widgets += [{"id": "bound", "type": "Label", "binding": {"key": "value"}},
                            {"id": "raw", "type": "Label", "binding": {
                                "parseMode": "HEX字节提取", "frameHeader": "AA", "frameTail": "BB",
                                "dataType": "uint8"}}]
        with tempfile.TemporaryDirectory() as folder:
            generate_project(project, folder)
            self.run_script('''
                import sys
                from contextlib import ExitStack
                from unittest.mock import patch
                from PyQt5.QtCore import QEvent
                from PyQt5.QtWidgets import QApplication
                from qfluentwidgets import qconfig
                errors = []
                sys.excepthook = lambda kind, value, tb: errors.append(str(value))
                def exercise():
                    app = QApplication.instance()
                    window = next(w for w in app.topLevelWidgets() if hasattr(w, "widgets"))
                    handler = window._comm_hub
                    signals = [handler.connected, handler.disconnected, handler.error,
                               handler.dataReceived, handler.rawReceived, handler.dataSent]
                    handler.dataReceived.emit({"value": 42})
                    assert window.widgets["bound"].text() == "42"
                    for widget in window.widgets.values():
                        if hasattr(widget, "set_serial_handler"):
                            widget.set_serial_handler(handler)
                            widget.set_serial_handler(handler)
                    # DataTable plus chart, log, Modbus card and binding each subscribe exactly once.
                    assert handler.receivers(handler.dataReceived) == 5
                    window.deleteLater()
                    app.sendPostedEvents(None, QEvent.DeferredDelete)
                    assert [handler.receivers(s) for s in signals] == [0] * len(signals)
                    handler.connected.emit("TEST")
                    handler.disconnected.emit()
                    handler.error.emit("after destruction")
                    handler.dataReceived.emit({"value": 7})
                    handler.rawReceived.emit(bytes.fromhex("AA01BB"))
                    handler.dataSent.emit(b"READ")
                    qconfig.themeChangedFinished.emit()
                    app.processEvents()
                    assert not errors, errors
                    assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
                    print("LIFETIME_OK")
                    return 0
                with ExitStack() as stack:
                    if sys.platform == "darwin":
                        from qframelesswindow.mac import MacFramelessWindow
                        for name in ("updateFrameless", "_hideSystemTitleBar",
                                     "setSystemTitleBarButtonVisible"):
                            stack.enter_context(patch.object(MacFramelessWindow, name,
                                                             lambda *args, **kwargs: None))
                    from ui import MainUI
                    from comm_hub import CommHub
                    from data_binding import DataBinding
                    from theme_support import ThemeController
                    app = QApplication([])
                    theme = ThemeController(app, "Light")
                    window = MainUI()
                    handler = CommHub()  # as the generated main.py does
                    binding = DataBinding(window, handler)
                    exercise()
                    theme.deleteLater()
                    app.sendPostedEvents(None, QEvent.DeferredDelete)
                    app.aboutToQuit.emit()
                    assert not errors, errors
            ''', cwd=folder)
