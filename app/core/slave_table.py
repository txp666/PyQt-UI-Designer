"""The register table (ModbusSlaveTable) shared by the designer preview and exported applications.

It shows one area of a slave data table (slave_runtime.ModbusSlaveDevice): the first link card in the slave
role in the document, a row per address. A value cell edited with a double-click is written into the table,
which publishes the change like any other write; writes from elsewhere (an external master, a control) show
in the rows they touch. Without such a card the table holds one hint row.
"""
import re

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHeaderView, QTableWidgetItem, QAbstractItemView
from qfluentwidgets import TableWidget

from .modbus_slave import AREA_TABLES
from .i18n import tr, N_

NO_SLAVE = N_("没有从站链路卡片")
_UNSIGNED, _SIGNED, _HEX = "无符号", "有符号", "十六进制"  # i18n: value  (the display formats)


def slave_value_text(table, value, display_format=_UNSIGNED):
    """A value as the table shows it: 0 / 1 for coils and discrete inputs; a register unsigned, signed
    (−32768–32767) or as four hex digits (0x04D2)."""
    if table in ("co", "di"):
        return "1" if value else "0"
    if display_format == _SIGNED:
        return str(value - 65536 if value > 32767 else value)
    if display_format == _HEX:
        return f"0x{value:04X}"
    return str(value)


def slave_value_from_text(table, text, display_format=_UNSIGNED):
    """The value typed into a cell, read by the display format (hex takes 1A and 0x1A); None when it is not
    one: a coil or discrete input takes 0 or 1, a register 0–65535 (signed: −32768–32767)."""
    text = text.strip()
    if table in ("co", "di"):
        return int(text) if text in ("0", "1") else None
    if display_format == _HEX:
        match = re.fullmatch(r"(?:0[xX])?([0-9A-Fa-f]{1,4})", text)
        return int(match.group(1), 16) if match else None
    if display_format == _SIGNED:
        if not re.fullmatch(r"-?[0-9]{1,5}", text) or not -32768 <= int(text) <= 32767:
            return None
        return int(text) & 0xFFFF
    if not re.fullmatch(r"[0-9]{1,5}", text) or int(text) > 65535:
        return None
    return int(text)


class ModbusSlaveTable(QWidget):
    """Address / value rows of one area of a slave data table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._table = TableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels([tr("地址"), tr("值")])
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table)
        self._area = "hr"
        self._format = _UNSIGNED
        self._store = None   # the data table shown, or None
        self._device = None  # the slave it belongs to, which takes edits; None in the designer
        self._filling = False
        self._show()

    def set_area(self, area):
        """An area name of binding_values.MODBUS_AREAS; holding registers by default."""
        self._area = AREA_TABLES.get(area, "hr")
        self._show()

    def set_display_format(self, display_format):
        """Unsigned (the default), signed or hex; coils and discrete inputs always show 0 / 1."""
        self._format = display_format if display_format in (_UNSIGNED, _SIGNED, _HEX) else _UNSIGNED
        self._show()

    def set_slave_device(self, device):
        """The slave whose table this shows and edits, or None for the hint row."""
        if self._device is not None:
            self._device.written.disconnect(self._on_written)
        self._device = device
        if device is not None:
            device.written.connect(self._on_written)
        self.show_store(device.store if device is not None else None)

    def show_store(self, store):
        """Show ``store`` (a modbus_slave.SlaveStore), or the hint row for None."""
        self._store = store
        self._show()

    def _show(self):
        self._filling = True
        table = self._table
        table.clearSpans()
        if self._store is None:
            table.setRowCount(1)
            hint = QTableWidgetItem(tr(NO_SLAVE))
            hint.setFlags(Qt.ItemIsEnabled)
            table.setItem(0, 0, hint)
            table.setSpan(0, 0, 1, 2)
        else:
            addresses = self._store.addresses(self._area)
            table.setRowCount(len(addresses))
            for row, address in enumerate(addresses):
                cell = QTableWidgetItem(str(address))
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                table.setItem(row, 0, cell)
                table.setItem(row, 1, QTableWidgetItem(self._text(address)))
        self._filling = False

    def _text(self, address):
        return slave_value_text(self._area, self._store.get(self._area, address), self._format)

    def _on_written(self, message):
        """A write to the slave: the rows of the addresses it names are shown again."""
        if self._store is None:
            return
        start = self._store.areas[self._area][0]
        self._filling = True
        for key in message:
            if key.startswith(self._area) and key[2:].isdigit():
                item = self._table.item(int(key[2:]) - start, 1)
                if item is not None:
                    item.setText(self._text(int(key[2:])))
        self._filling = False

    def _on_item_changed(self, item):
        if self._filling or self._store is None or item.column() != 1:
            return
        address = self._store.areas[self._area][0] + item.row()
        value = slave_value_from_text(self._area, item.text(), self._format)
        if value is None or self._device is None or not self._device.write(self._area, address, [value]):
            self._filling = True
            item.setText(self._text(address))  # not a value: the old one stays
            self._filling = False
