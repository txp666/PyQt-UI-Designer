# coding: utf-8
"""Checks a .uidp file the way PyQt UI Designer opens it, and also what opening lets through: a misspelt
property name or option value is not an error, it just does nothing. Run it on a project written by hand or by
an AI assistant before opening it.

    python tools/check_uidp.py motor.uidp
Prints "ok: <应用名>", or one problem per line and exits 1.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with contextlib.redirect_stdout(io.StringIO()):  # qfluentwidgets prints an advert when first imported
    from app.core.binding_values import MODBUS_AREAS
    from app.core.chart_runtime import _DEFAULT_CURVE_CFG
    from app.core.command_runtime import MODBUS_DATA_TYPES, MODBUS_ORDERS
    from app.core.modbus_card import modbus_poll_table
    from app.core.data_binding import BIND_PROPERTIES
    from app.core.project import ProjectData
    from app.core.widget_registry import registry
    from app.widgets.base import PropType
    from app.widgets.basic import register_basic_widgets
    from app.widgets.chart import register_chart_widgets
    from app.widgets.comm import register_comm_widgets
    from app.widgets.composite import register_composite_widgets
    from app.widgets.display import register_display_widgets
    from app.widgets.layout import register_layout_widgets

PARSE_MODES = ("键值匹配", "JSON路径", "HEX字节提取", "Modbus")
# Modbus binding (and chart curve) fields that take one of a few values, and those values.
MODBUS_BINDING_OPTIONS = {"mbArea": tuple(MODBUS_AREAS), "mbDataType": MODBUS_DATA_TYPES,
                          "mbRegOrder": MODBUS_ORDERS}


def _register_widgets():
    for register in (register_basic_widgets, register_layout_widgets, register_display_widgets,
                     register_chart_widgets, register_comm_widgets, register_composite_widgets):
        register()


def problems(data) -> list:
    """What is wrong with a project document, as readable lines; empty when it is fine."""
    _register_widgets()
    try:
        ProjectData.validate(data)
    except ValueError as error:
        return [str(error)]
    found = []

    def walk(items):
        for item in items:
            kind = item["type"]
            name = item.get("id") or kind
            meta = registry.get(kind)
            for key, value in item.get("properties", {}).items():
                if kind == "RealtimeChart" and key.startswith("_curve_"):
                    field = key.split("_", 3)[-1]  # _curve_0_key -> key
                    if field not in _DEFAULT_CURVE_CFG:
                        found.append(f"{name}: 曲线没有字段 {field}（{key}）")
                    elif field == "parseMode" and value not in PARSE_MODES:
                        found.append(f"{name}: {key} 不能是 {value!r}，可选 {'、'.join(PARSE_MODES)}")
                    elif field in MODBUS_BINDING_OPTIONS and value not in MODBUS_BINDING_OPTIONS[field]:
                        found.append(f"{name}: {key} 不能是 {value!r}，"
                                     f"可选 {'、'.join(MODBUS_BINDING_OPTIONS[field])}")
                    continue
                if kind == "TabWidget" and key.startswith("_tabLayout_") and key[11:].isdigit():
                    options = meta.get_prop_def("tabLayout").options  # one page's layout, see "容器" in the guide
                    if value not in options:
                        found.append(f"{name}: {key} 不能是 {value!r}，可选 {'、'.join(options)}")
                    continue
                prop = meta.get_prop_def(key)
                if prop is None:
                    found.append(f"{name}: {kind} 没有属性 {key}")
                elif prop.prop_type == PropType.ENUM and value not in prop.options:
                    found.append(f"{name}: {key} 不能是 {value!r}，可选 {'、'.join(prop.options)}")
                elif kind == "ModbusConfigCard" and key == "pollList":
                    try:
                        modbus_poll_table(value)
                    except ValueError as error:
                        found.append(f"{name}: {error}")
                elif kind == "ModbusConfigCard" and key == "autoStart" and not isinstance(value, bool):
                    found.append(f"{name}: autoStart 应为 true 或 false")
            binding = item.get("binding")
            if binding:
                if kind not in BIND_PROPERTIES:
                    found.append(f"{name}: {kind} 不能绑定数据")
                if binding.get("parseMode", "键值匹配") not in PARSE_MODES:
                    found.append(f"{name}: parseMode 不能是 {binding.get('parseMode')!r}，"
                                 f"可选 {'、'.join(PARSE_MODES)}")
                for key, options in MODBUS_BINDING_OPTIONS.items():
                    if key in binding and binding[key] not in options:
                        found.append(f"{name}: binding 的 {key} 不能是 {binding[key]!r}，可选 {'、'.join(options)}")
                period = binding.get("mbPeriod", 0)
                if type(period) is not int or not 0 <= period <= 60000:
                    found.append(f"{name}: binding 的 mbPeriod 应为 0–60000 的整数（毫秒），不能是 {period!r}")
            walk(item.get("children", []))

    walk(data.get("widgets", []))
    return found


def main(argv) -> int:
    # A Windows pipe's code page has no Chinese: pipes get UTF-8, a console replaces what it cannot show.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(**({"errors": "replace"} if stream.isatty() else {"encoding": "utf-8"}))
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"无法读取 {argv[1]}: {error}")
        return 1
    found = problems(data)
    for line in found:
        print(line)
    if not found:
        print(f"ok: {data.get('appName', '上位机')}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
