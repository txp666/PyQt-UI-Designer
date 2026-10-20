"""A slow update check must not outlive its settings window's destruction."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
_SETUP = '''
import json
import sys
import threading
import time
import traceback
from contextlib import ExitStack
from unittest.mock import patch
from PyQt5 import sip
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication
from app.common import update_checker
from app.view import setting_interface

errors = []
sys.excepthook = lambda *exc: errors.append(''.join(traceback.format_exception(*exc)))
class Response:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps({"tag_name": "v0.0.0"}).encode()
app = QApplication([])
def drain():
    app.processEvents()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
def await_complete(interface):
    deadline = time.monotonic() + 3
    while interface._update_thread is not None and time.monotonic() < deadline:
        drain()
        time.sleep(0.005)
    assert interface._update_thread is None
    drain()
with ExitStack() as stack:
    if sys.platform == "darwin":
        from qframelesswindow.mac import MacFramelessWindow
        for name in ("updateFrameless", "_hideSystemTitleBar", "setSystemTitleBarButtonVisible"):
            stack.enter_context(patch.object(MacFramelessWindow, name, lambda *args, **kwargs: None))
    success = stack.enter_context(patch.object(setting_interface.InfoBar, "success"))
    failure = stack.enter_context(patch.object(setting_interface.InfoBar, "error"))
    from app.view.main_window import MainWindow
    window = MainWindow()
    interface = window.setting_interface
    window.show()
    drain()
__CHECKS__
    assert not errors, errors
    assert window.close()
    window.deleteLater()
    drain()
    assert not errors, errors
print("UPDATE_LIFETIME_OK")
'''


class UpdateLifecycleTests(unittest.TestCase):
    def run_script(self, checks):
        script = _SETUP.replace('__CHECKS__', textwrap.indent(textwrap.dedent(checks), '    '))
        result = subprocess.run(
            [sys.executable, '-X', 'faulthandler', '-c', script], cwd=ROOT,
            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True,
            text=True, encoding='utf-8', timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('UPDATE_LIFETIME_OK', result.stdout)
        self.assertNotIn('QThread: Destroyed', result.stderr)

    def test_close_waits_for_inflight_io_and_suppresses_cancelled_result(self):
        self.run_script('''
            started = threading.Event()
            def slow_response(*args, **kwargs):
                assert kwargs["timeout"] == 15
                started.set()
                time.sleep(0.2)
                raise TimeoutError("simulated slow response")
            stack.enter_context(patch.object(update_checker, "urlopen", slow_response))
            interface._check_update()
            assert started.wait(2)
            thread = interface._update_thread
            assert thread.isRunning()
            assert window.close()
            assert thread.isFinished()
            assert interface._update_thread is None
            assert not interface._update_connections._connections
            drain()
            assert sip.isdeleted(thread)
            assert not success.called and not failure.called
        ''')

    def test_completed_checks_release_thread_and_allow_repeated_check(self):
        self.run_script('''
            stack.enter_context(patch.object(update_checker, "urlopen", return_value=Response()))
            for index in range(3):
                interface._check_update()
                thread = interface._update_thread
                assert not interface.aboutCard.button.isEnabled()
                await_complete(interface)
                assert sip.isdeleted(thread)
                assert not interface._update_connections._connections
                assert interface.aboutCard.button.isEnabled()
                assert interface.aboutCard.button.text() == "检查更新"
                assert success.call_count == index + 1
            assert not failure.called
        ''')

    def test_rejected_close_preserves_worker_and_normal_result(self):
        self.run_script('''
            started, release = threading.Event(), threading.Event()
            def delayed_response(*args, **kwargs):
                started.set()
                assert release.wait(2)
                return Response()
            stack.enter_context(patch.object(update_checker, "urlopen", delayed_response))
            interface._check_update()
            assert started.wait(2)
            thread = interface._update_thread
            with patch.object(window, "_confirm_unsaved_changes", return_value=False):
                assert not window.close()
            assert interface._update_thread is thread
            assert thread.isRunning()
            assert not thread.isInterruptionRequested()
            release.set()
            await_complete(interface)
            assert sip.isdeleted(thread)
            success.assert_called_once()
        ''')

    def test_close_cancels_already_queued_success_result(self):
        self.run_script('''
            stack.enter_context(patch.object(update_checker, "urlopen", return_value=Response()))
            interface._check_update()
            thread = interface._update_thread
            assert thread.wait(2000)
            # Worker has emitted its result, but the GUI has not delivered it.
            assert not success.called
            assert window.close()
            drain()
            assert interface._update_thread is None
            assert sip.isdeleted(thread)
            assert not success.called and not failure.called
        ''')
