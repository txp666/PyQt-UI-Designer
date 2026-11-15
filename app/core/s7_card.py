"""S7 connection card, shared by preview and standalone exports."""
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QGridLayout, QLayout
from qfluentwidgets import CardWidget, BodyLabel, StrongBodyLabel, LineEdit, SpinBox, ComboBox, PushButton, CheckBox

from .i18n import tr
from .s7_values import DEFAULT_CONFIG, s7_config
from .s7_runtime import S7Link


class S7ConfigCard(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._hub = self._link = None
        self._source_id = ""
        self._config = dict(DEFAULT_CONFIG)
        self._editors = {}
        self._labels = {}
        layout = self._grid = QGridLayout(self)
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setVerticalSpacing(4)
        self._title = StrongBodyLabel(tr("S7 配置"), self)
        fields = [("host", tr("地址"), None), ("port", tr("端口"), (1, 65535)),
                  ("rack", "Rack", (0, 7)), ("slot", "Slot", (0, 31)),
                  ("connectionType", tr("连接类型"), None),
                  ("period", tr("默认轮询(ms)"), (1, 60000)),
                  ("timeout", tr("响应超时(ms)"), (1, 60000)),
                  ("reconnectInterval", tr("重连间隔(ms)"), (1, 60000))]
        for row, (key, label, limits) in enumerate(fields, 1):
            if key == "host":
                editor = LineEdit(self)
                editor.setText(self._config[key])
            elif key == "connectionType":
                editor = ComboBox(self)
                for text, value in (("PG", 1), ("OP", 2), ("S7 Basic", 3)):
                    editor.addItem(text, userData=value)
            else:
                editor = SpinBox(self)
                editor.setRange(*limits)
                editor.setValue(self._config[key])
            self._editors[key] = editor
            self._labels[key] = BodyLabel(label, self)
            if key in ("period", "timeout", "reconnectInterval"):
                editor.hide()
                self._labels[key].hide()
        row = len(fields) + 1
        self._reconnect = CheckBox(tr("自动重连"), self)
        self._reconnect.setChecked(True)
        self._status = BodyLabel(tr("未连接"), self)
        self._status.setWordWrap(True)
        self._button = PushButton(tr("连接"), self)
        self._button.clicked.connect(self._toggle)
        self._button.setEnabled(False)  # the design canvas never opens a PLC connection
        self._columns = 0
        self._arrange()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_columns"):
            self._arrange()

    def _arrange(self):
        columns = 5 if self.width() >= 800 else 2 if self.width() >= 440 else 1
        if columns == self._columns:
            return
        self._columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index in range(10):
            self._grid.setColumnStretch(index, 0)
        width = columns * 2
        self._grid.addWidget(self._title, 0, 0, 1, max(1, width - 1))
        self._grid.addWidget(self._button, 0, width - 1)
        keys = ("host", "port", "rack", "slot", "connectionType")
        for index, key in enumerate(keys):
            row, column = 1 + index // columns, 2 * (index % columns)
            self._grid.addWidget(self._labels[key], row, column)
            self._grid.addWidget(self._editors[key], row, column + 1)
            self._grid.setColumnStretch(column + 1, 1)
        row = 2 + (len(keys) - 1) // columns
        self._grid.addWidget(self._status, row, 0, 1, max(1, width - 1))
        self._grid.addWidget(self._reconnect, row, width - 1)

    def set_config_value(self, key, value):
        self._config[key] = value
        if key == "title":
            self._title.setText(str(value))
            return
        editor = self._editors.get(key)
        if key == "host":
            editor.setText(str(value))
        elif key == "connectionType":
            editor.setCurrentIndex(editor.findData(int(value)))
        elif editor is not None:
            editor.setValue(int(value))
        elif key == "autoReconnect":
            self._reconnect.setChecked(bool(value))
        if self._link is not None and self._link.is_active:
            self._link.disconnect()

    def set_hub(self, hub, source_id=""):
        if self._hub is not None:
            self._hub.remove_s7_link(self._source_id)
        self._hub, self._source_id = hub, source_id
        if self._link is not None:
            self._link.deleteLater()
            self._link = None
        self._button.setEnabled(hub is not None)
        if hub is not None:
            self._link = S7Link(source_id, self)
            self._link.stateChanged.connect(self._state)
            self._link.writeCompleted.connect(self._written)
            hub.add_s7_link(source_id, self._link)
            if self._config.get("autoConnect"):
                QTimer.singleShot(0, self._toggle)

    def _toggle(self):
        if self._link is None:
            return
        if self._link.is_active:
            self._link.disconnect()
            return
        config = dict(self._config)
        for key, editor in self._editors.items():
            config[key] = (editor.text().strip() if key == "host" else
                           editor.currentData() if key == "connectionType" else editor.value())
        config["autoReconnect"] = self._reconnect.isChecked()
        try:
            self._link.connect(s7_config(config))
        except (ValueError, RuntimeError) as error:
            self._status.setText(str(error))

    def _state(self, connected, active, error):
        self._button.setText(tr("断开") if active else tr("连接"))
        self._status.setText((tr("已连接") if connected else tr("连接中") if active else tr("未连接"))
                             + (" · " + error if error else ""))
        for editor in (*self._editors.values(), self._reconnect):
            editor.setEnabled(not active)

    def _written(self, result):
        if result.get("status") != "good":
            self._status.setText(tr("S7 写入未确认") + " · " + result.get("error", ""))
