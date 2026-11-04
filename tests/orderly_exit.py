"""Delete the QObjects Python still owns before PyQt's own exit hook does.

At exit PyQt deletes every QObject Python still owns while it walks sip's table of wrappers
(QtCore's cleanup_on_exit). If one of those deletions runs Python, such as a slot on `destroyed`
or an event filter, and that code wraps new objects, sip can grow the table and free the copy
being walked. The process then segfaults after the script has finished, now and then (seen on
macOS-Intel / Python 3.12 and Windows / Python 3.14). This module deletes those objects first,
from an atexit hook registered after PyQt's (atexit runs the last one first), so PyQt's walk has
nothing left to delete.

Importing it does that for this process. Child processes get it by starting their script with
`CHILD_PRELUDE`.
"""
import atexit
import gc
from pathlib import Path

from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QObject, QThread


def delete_owned_qobjects():
    """What PyQt's exit hook would delete (the same objects), done while nothing walks sip's table."""
    app = QCoreApplication.instance()
    for _ in range(10):  # deleting can create objects; PyQt's hook gets whatever is left after this
        owned = [obj for obj in gc.get_objects()
                 if issubclass(type(obj), QObject) and obj is not app and not sip.isdeleted(obj)
                 and sip.ispyowned(obj) and not (isinstance(obj, QThread) and obj.isRunning())]
        if not owned:
            return
        for obj in reversed(owned):  # roughly newest first, like unwinding
            if not sip.isdeleted(obj):
                sip.delete(obj)
        if app is not None:
            app.sendPostedEvents(None, QEvent.DeferredDelete)


atexit.register(delete_owned_qobjects)

# One line, so a child's traceback line numbers are its script's plus one.
CHILD_PRELUDE = f"__import__('runpy').run_path({str(Path(__file__).resolve())!r})\n"
