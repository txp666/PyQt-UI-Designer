"""Data table shared by the designer preview and exported applications."""
from datetime import datetime

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHeaderView, QTableWidgetItem, QAbstractItemView
from qfluentwidgets import TableWidget

from .signal_lifetime import SignalConnections


class DataTableWidget(QWidget):
    """Either the latest frame as field / value rows, or a log with one row per frame.

    In the log, each column takes the value of the key it is named after and a column named 时间 takes the
    time the frame arrived; frames carrying none of the named keys belong to some other message and are
    skipped. Beyond the row limit the oldest rows go."""

    TIME_COLUMN = "时间"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial_connections = SignalConnections(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._table = TableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["字段", "值"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self._table)
        self._columns = ["字段", "值"]
        self._max_rows = 500
        self._logging = False
        self._fit_columns()

    def set_serial_handler(self, handler):
        self._serial_connections.clear()
        self._serial_connections.connect(handler.dataReceived, self.on_data)

    def set_columns(self, columns):
        self._columns = list(columns) or ["字段", "值"]
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)
        self._fit_columns()

    def _fit_columns(self):
        """Field / value columns share the width. A log's columns fit what they hold, so a time stamp or a
        reading is never squeezed into an ellipsis, and the last one takes what is left."""
        header = self._table.horizontalHeader()
        header.setResizeContentsPrecision(64)  # sizes from a sample of rows, not the whole log
        # a log's rows are told apart by their time stamps; row numbers growing to four digits would only
        # take width from the readings
        self._table.verticalHeader().setVisible(not self._logging)
        last = len(self._columns) - 1
        for column in range(len(self._columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents
                                        if self._logging and column < last else QHeaderView.Stretch)

    def set_max_rows(self, count):
        self._max_rows = max(10, count)
        while self._table.rowCount() > self._max_rows:
            self._table.removeRow(0 if self._logging else self._table.rowCount() - 1)

    def set_record_mode(self, mode):
        """最新值 (the latest frame) or 逐行记录 (one row per frame)."""
        logging = mode == "逐行记录"
        if logging != self._logging:
            self._logging = logging
            self.clear_data()
            self._fit_columns()

    def on_data(self, data):
        if self._logging:
            self.log_frame(data)
        else:
            self.update_kv_data(data)

    def log_frame(self, data):
        keys = [name for name in self._columns if name != self.TIME_COLUMN]
        if not any(key in data for key in keys):
            return
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.append_row([stamp if name == self.TIME_COLUMN else ("" if data.get(name) is None else data[name])
                         for name in self._columns])

    def append_row(self, values):
        if self._table.rowCount() >= self._max_rows:
            self._table.removeRow(0)
        row = self._table.rowCount()
        self._table.insertRow(row)
        for column, value in enumerate(values):
            if column < self._table.columnCount():
                self._table.setItem(row, column, QTableWidgetItem(str(value)))
        self._table.scrollToBottom()

    def update_kv_data(self, data):
        self._table.setRowCount(0)
        for key, value in data.items():
            row = self._table.rowCount()
            if row >= self._max_rows:
                break
            self._table.insertRow(row)
            for column, cell in enumerate((key, value)):
                if column < self._table.columnCount():
                    self._table.setItem(row, column, QTableWidgetItem(str(cell)))

    def clear_data(self):
        self._table.setRowCount(0)
