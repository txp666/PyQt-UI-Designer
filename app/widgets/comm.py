# coding: utf-8
"""Communication widgets: data table."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView,
    QTableWidgetItem, QAbstractItemView,
)
from qfluentwidgets import TableWidget

from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.widget_registry import registry


class DataTableWidget(QWidget):
    """Table showing key-value data records with history.
    Auto-wired to signalBus for live parsed serial data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self._table = TableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["字段", "值"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self._table)

        self._columns = ["字段", "值"]
        self._max_rows = 500

        from app.common.signal_bus import signalBus
        signalBus.serialDataReceived.connect(self._on_parsed_data)

    def _on_parsed_data(self, data: dict):
        self.update_kv_data(data)

    def set_columns(self, cols: list):
        self._columns = list(cols) or ["字段", "值"]
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)

    def set_max_rows(self, n: int):
        self._max_rows = max(10, n)
        while self._table.rowCount() > self._max_rows:
            self._table.removeRow(self._table.rowCount() - 1)

    def append_row(self, values: list):
        row = self._table.rowCount()
        if row >= self._max_rows:
            self._table.removeRow(0)
            row = self._table.rowCount()
        self._table.insertRow(row)
        for col, val in enumerate(values):
            if col < self._table.columnCount():
                self._table.setItem(row, col, QTableWidgetItem(str(val)))
        self._table.scrollToBottom()

    def update_kv_data(self, data: dict):
        self._table.setRowCount(0)
        for key, val in data.items():
            row = self._table.rowCount()
            if row >= self._max_rows:
                break
            self._table.insertRow(row)
            for column, value in enumerate((key, val)):
                if column < self._table.columnCount():
                    self._table.setItem(row, column, QTableWidgetItem(str(value)))

    def clear_data(self):
        self._table.setRowCount(0)


DATA_TABLE_META = WidgetMeta(
    type_name="DataTable",
    display_name="数据表格",
    category=WidgetCategory.CHART,
    icon="VIEW",
    default_width=350, default_height=250,
    min_width=200, min_height=100,
    properties=[
        PropDef("columns", "列名", PropType.TEXT, "字段\n值"),
        PropDef("maxRows", "最大行数", PropType.INT, 500, min_val=10, max_val=50000),
    ],
)

ALL_COMM = [DATA_TABLE_META]


def register_comm_widgets():
    for meta in ALL_COMM:
        registry.register(meta)


def create_comm_widget(type_name: str, props: dict, parent=None) -> QWidget:
    if type_name == "DataTable":
        w = DataTableWidget(parent)
        cols_text = props.get("columns", "字段\n值")
        cols = [c.strip() for c in cols_text.split("\n") if c.strip()]
        w.set_columns(cols)
        w.set_max_rows(props.get("maxRows", 500))
        return w
    return None


def apply_comm_property(widget, type_name: str, prop_name: str, value):
    if type_name == "DataTable":
        if prop_name == "columns":
            cols = [c.strip() for c in value.split("\n") if c.strip()]
            widget.set_columns(cols)
        elif prop_name == "maxRows":
            widget.set_max_rows(value)
