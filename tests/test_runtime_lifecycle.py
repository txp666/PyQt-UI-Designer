"""Real Qt queued serial events must stay with the connection that read them."""
from collections import deque
import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.core import serial_runtime
from app.core.code_generator import _gen_serial_handler


class MemoryPort:
    def __init__(self, packets=(), failure=None):
        self.packets = deque(packets)
        self.failure = failure
        self.is_open = True
        self.close_count = 0

    @property
    def in_waiting(self):
        if self.packets:
            return len(self.packets[0])
        if self.failure:
            raise OSError(self.failure)
        return 0

    def read(self, count):
        return self.packets.popleft()

    def close(self):
        self.is_open = False
        self.close_count += 1


class SerialLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def runtimes(self):
        exported = {}
        exec(_gen_serial_handler({}), exported)
        return vars(serial_runtime), exported

    def make_handler(self, namespace):
        handler = namespace["SerialHandler"]()

        def cleanup():
            handler.disconnect()
            handler.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

        self.addCleanup(cleanup)
        return handler

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate(), "Timed out waiting for a queued Qt signal")

    def test_queued_old_error_and_samples_cannot_affect_replacement_connection(self):
        for namespace in self.runtimes():
            handler = self.make_handler(namespace)
            old = MemoryPort([b"temp=11\n"], "old reader failed")
            current = MemoryPort()
            raw, parsed, errors, states = [], [], [], []
            handler.rawReceived.connect(raw.append)
            handler.dataReceived.connect(parsed.append)
            handler.error.connect(errors.append)
            handler.connectionChanged.connect(states.append)
            with patch.object(namespace["serial"], "Serial", side_effect=[old, current]):
                self.assertTrue(handler.connect("OLD"))
                old_reader = handler._thread
                # Waiting for the actual QThread does not process the GUI queue.
                # Its raw, parsed and error signals are now pending together.
                self.assertTrue(old_reader.wait(2000))
                self.assertEqual((raw, parsed, errors), ([], [], []))
                self.assertTrue(handler.connect("CURRENT"))
                current_reader = handler._thread
                self.app.processEvents()
                self.assertEqual((raw, parsed, errors), ([], [], []))
                self.assertTrue(handler.is_connected)
                self.assertIs(handler._thread, current_reader)
                self.assertEqual(old.close_count, 1)
                self.assertEqual(current.close_count, 0)
                self.assertEqual(states, [True, False, True])

                current.packets.append(b"temp=22\n")
                self.wait_for(lambda: bool(parsed))
                self.assertEqual(raw, [b"temp=22\n"])
                self.assertEqual(parsed, [{"temp": 22}])

                current.failure = "current reader failed"
                self.assertTrue(current_reader.wait(2000))
                self.assertTrue(handler.is_connected)
                self.app.processEvents()
                self.assertEqual(errors, ["current reader failed"])
                self.assertFalse(handler.is_connected)
                self.assertIsNone(handler._thread)
                self.assertEqual(current.close_count, 1)
                self.assertEqual(states, [True, False, True, False])

    def test_explicit_disconnect_discards_pending_samples_and_error(self):
        for namespace in self.runtimes():
            handler = self.make_handler(namespace)
            port = MemoryPort([b"temp=11\n"], "closed reader failed")
            raw, parsed, errors = [], [], []
            handler.rawReceived.connect(raw.append)
            handler.dataReceived.connect(parsed.append)
            handler.error.connect(errors.append)
            with patch.object(namespace["serial"], "Serial", return_value=port):
                self.assertTrue(handler.connect("OLD"))
                self.assertTrue(handler._thread.wait(2000))
                handler.disconnect()
                self.app.processEvents()
            self.assertEqual((raw, parsed, errors), ([], [], []))
            self.assertFalse(handler.is_connected)
            self.assertEqual(port.close_count, 1)

    def test_error_observer_can_reconnect_without_new_connection_being_closed(self):
        for namespace in self.runtimes():
            handler = self.make_handler(namespace)
            old = MemoryPort(failure="current reader failed")
            replacement = MemoryPort()
            errors = []
            handler.error.connect(errors.append)
            handler.error.connect(lambda _message, handler=handler: handler.connect("NEW"))
            with patch.object(namespace["serial"], "Serial", side_effect=[old, replacement]):
                self.assertTrue(handler.connect("OLD"))
                self.assertTrue(handler._thread.wait(2000))
                self.app.processEvents()
                self.assertEqual(errors, ["current reader failed"])
                self.assertTrue(handler.is_connected)
                self.assertIs(handler._port, replacement)
                self.assertEqual(old.close_count, 1)
                self.assertEqual(replacement.close_count, 0)


if __name__ == "__main__":
    unittest.main()
