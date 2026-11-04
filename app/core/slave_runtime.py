"""The Modbus slave of a link card in the slave role, on its link: shared by the designer preview and exports.

A serial or TCP card whose Modbus role is slave owns a ModbusSlaveDevice: the data table (modbus_slave.SlaveStore),
built from the card's areas and initial values when it is first needed and kept while the program runs, whether the
link is connected or not. Every write to it (an external master's, a control's, a command's, the register
table's) gives a slave message on ``written``, which the card publishes on its link like a parsed frame.

When the card connects its link and the link parses modbus or modbus_tcp, the link frames requests with the
device's framer and hands each one to ``receive``. A write takes effect at once; the reply goes out the response delay
(``delay``) ms after its request came in, the replies one after another in the order the requests came. The
link's ``slaveLog`` carries the log lines (the reply's when it goes out), and the counts of replies and of
failed requests start from 0 at each connection.
"""
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from .modbus_slave import DEFAULT_AREA, TABLES, ModbusSlave, SlaveStore, request_framer
from .i18n import tr


class ModbusSlaveDevice(QObject):
    written = pyqtSignal(dict)    # a slave message: after a write, or one per area at the start
    statusChanged = pyqtSignal()  # a reply went out, or a request failed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.address = 1       # 默认从站: this slave's address
        self.exceptions = True  # 异常响应
        self.delay = 0         # 响应延时 ms
        self._areas = {table: DEFAULT_AREA for table in TABLES}
        self._init = ""
        self._store = None
        self._link = None      # the link answering with this table, and how
        self._slave = None
        self._pending = []     # (when it is due, reply, its log line, how to send it)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._pump)
        self.replies = self.errors = 0

    # -- the data table -----------------------------------------------------------

    def set_area(self, table, start=None, count=None):
        old_start, old_count = self._areas[table]
        self._areas[table] = (old_start if start is None else start, old_count if count is None else count)
        self._store = None

    def set_init(self, text):
        self._init = str(text)
        self._store = None

    @property
    def store(self):
        if self._store is None:
            self._store = SlaveStore(self._areas, self._init)
        return self._store

    def publish_start(self):
        """The whole table, one message per area that has addresses, so bound widgets show it from the start."""
        for message in self.store.start_messages(self.address):
            self.written.emit(message)

    def write(self, table, address, values):
        """Write ``values`` from ``address`` on and publish the change; False, writing nothing, unless every
        address is in the area."""
        store = self.store
        if not store.has(table, address, len(values)):
            return False
        store.set(table, address, values)
        self.written.emit(store.message(self.address, table, range(address, address + len(values))))
        return True

    # -- on the link -----------------------------------------------------------

    @staticmethod
    def framer(parser_type):
        return request_framer(parser_type)

    def begin(self, link, parser_type):
        """``link`` answers requests from now on, framed as ``parser_type`` (modbus or modbus_tcp)."""
        self.end()
        self._link = link
        self._slave = ModbusSlave("tcp" if parser_type == "modbus_tcp" else "rtu",
                                  self.address, self.exceptions, self.store)
        self.replies = self.errors = 0
        self.statusChanged.emit()

    def end(self):
        """The link stopped answering: replies not sent yet are dropped."""
        self._link = self._slave = None
        self._pending = []
        self._timer.stop()

    def receive(self, frame, send):
        """A request ``frame`` the link received; ``send(reply)`` writes the reply where the request came from
        and is True once it went out."""
        if self._slave is None:
            return
        reply, log, messages = self._slave.request(frame)
        if not log:
            return  # to another slave
        self._log(*log[0])
        if any(level == "warn" for _text, level in log):
            self.errors += 1
            self.statusChanged.emit()
        for message in messages:
            self.written.emit(message)
        if reply is not None:
            self._pending.append((time.monotonic() + self.delay / 1000, reply, log[1], send))
            self._pump()

    def _pump(self):
        while self._pending and not self._timer.isActive():
            due, reply, line, send = self._pending[0]
            wait = due - time.monotonic()
            if wait > 0:
                self._timer.start(max(1, round(wait * 1000)))
                return
            self._pending.pop(0)
            if send(reply):
                self.replies += 1
                self._log(*line)
                self.statusChanged.emit()

    def _log(self, text, level):
        if self._link is not None:
            self._link.slaveLog.emit(text, level)

    def status_text(self):
        """What the card shows after its connection: the slave address and the replies so far, then the
        failed requests once there are any."""
        text = tr("从站 %1 · 应答 %2", self.address, self.replies)
        return text + tr(" · 异常 %1", self.errors) if self.errors else text
