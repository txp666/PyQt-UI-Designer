"""One editable project profile shared by every referencing status/timing widget."""
import copy

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QTableWidgetItem, QHeaderView
from qfluentwidgets import CardWidget, StrongBodyLabel, ComboBox, LineEdit, PushButton, TableWidget

from app.core.bit_profiles import default_bit_profile, normalize_bit_profiles
from app.core.i18n import tr


class BitProfileEditor(CardWidget):
    changed = pyqtSignal(object, object)

    def __init__(self, profiles, current="default", parent=None):
        super().__init__(parent)
        self.profiles = copy.deepcopy(profiles)
        self.current = current
        self._loading = False

        layout = QVBoxLayout(self)
        layout.addWidget(StrongBodyLabel(tr("共享位配置")))
        self.selector = ComboBox()
        layout.addWidget(self.selector)

        row = QHBoxLayout()
        self.name_edit = LineEdit()
        self.width_combo = ComboBox()
        self.width_combo.addItems(["8", "16"])
        row.addWidget(self.name_edit, 1)
        row.addWidget(self.width_combo)
        layout.addLayout(row)

        add = PushButton(tr("新增配置"))
        add.clicked.connect(self._add)
        layout.addWidget(add)
        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels([tr("位名"), tr("颜色")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(26)
        layout.addWidget(self.table)

        self.selector.currentTextChanged.connect(self._select)
        self.name_edit.editingFinished.connect(self._rename)
        self.width_combo.currentTextChanged.connect(self._width)
        self.table.cellChanged.connect(self._cell)
        self._reload_names()

    def _reload_names(self):
        self._loading = True
        names = list(dict.fromkeys(["default", *self.profiles, self.current]))
        self.selector.clear()
        self.selector.addItems(names)
        self.selector.setCurrentText(self.current)
        self._loading = False
        self._load()

    def _load(self):
        self._loading = True
        profile = self.profiles.get(self.current, default_bit_profile())
        self.name_edit.setText(self.current)
        self.width_combo.setCurrentText(str(profile["width"]))
        self.table.setRowCount(profile["width"])
        self.table.setVerticalHeaderLabels([str(i) for i in range(profile["width"])])
        for index, bit in enumerate(profile["bits"]):
            self.table.setItem(index, 0, QTableWidgetItem(bit["name"]))
            color = QTableWidgetItem(bit["color"])
            color.setBackground(QBrush(QColor(bit["color"])))
            self.table.setItem(index, 1, color)
        self.table.setMinimumHeight(min(280, 34 + profile["width"] * 26))
        self._loading = False

    def _select(self, name):
        if not self._loading:
            self.current = name
            self._load()

    def _emit(self, rename=None):
        self.changed.emit(copy.deepcopy(self.profiles), rename)

    def _add(self):
        index = 1
        while f"profile{index}" in self.profiles:
            index += 1
        self.current = f"profile{index}"
        self.profiles[self.current] = default_bit_profile()
        self._reload_names()
        self._emit()

    def _rename(self):
        name = self.name_edit.text().strip()
        if not name or name == self.current or name in self.profiles:
            self.name_edit.setText(self.current)
            return
        old = self.current
        self.profiles[name] = self.profiles.pop(old, default_bit_profile())
        self.current = name
        self._reload_names()
        self._emit((old, name))

    def _width(self, text):
        if self._loading:
            return
        old = self.profiles.get(self.current, default_bit_profile())
        profile = default_bit_profile(int(text))
        count = min(len(old["bits"]), profile["width"])
        profile["bits"][:count] = copy.deepcopy(old["bits"][:count])
        self.profiles[self.current] = profile
        self._load()
        self._emit()

    def _cell(self, row, column):
        if self._loading:
            return
        profile = copy.deepcopy(self.profiles.get(self.current, default_bit_profile()))
        field = "name" if column == 0 else "color"
        profile["bits"][row][field] = self.table.item(row, column).text()
        try:
            normalized = normalize_bit_profiles({self.current: profile})
        except ValueError:
            return
        self.profiles.update(normalized)
        if column == 1:
            self._loading = True
            self.table.item(row, column).setBackground(QBrush(QColor(profile["bits"][row]["color"])))
            self._loading = False
        self._emit()
