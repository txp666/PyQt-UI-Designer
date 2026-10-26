# coding: utf-8
"""Communication widgets: data table."""
from PyQt5.QtWidgets import QWidget

from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.widget_registry import registry
from app.core.table_runtime import DataTableWidget as RuntimeTable


class DataTableWidget(RuntimeTable):
    """The shared data table, auto-wired to signalBus for live parsed serial data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from app.common.signal_bus import signalBus
        self._serial_connections.connect(signalBus.serialDataReceived, self.on_data)


DATA_TABLE_META = WidgetMeta(
    type_name="DataTable",
    display_name="数据表格",
    category=WidgetCategory.CHART,
    icon="VIEW",
    default_width=350, default_height=250,
    min_width=200, min_height=100,
    properties=[
        PropDef("columns", "列名", PropType.TEXT, "字段\n值"),
        PropDef("recordMode", "记录方式", PropType.ENUM, "最新值", options=["最新值", "逐行记录"]),
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
        w.set_record_mode(props.get("recordMode", "最新值"))
        w.set_max_rows(props.get("maxRows", 500))
        return w
    return None


def apply_comm_property(widget, type_name: str, prop_name: str, value):
    if type_name == "DataTable":
        if prop_name == "columns":
            cols = [c.strip() for c in value.split("\n") if c.strip()]
            widget.set_columns(cols)
        elif prop_name == "recordMode":
            widget.set_record_mode(value)
        elif prop_name == "maxRows":
            widget.set_max_rows(value)
