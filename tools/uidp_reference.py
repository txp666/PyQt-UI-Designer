# coding: utf-8
"""Regenerates the parts of the .uidp guide that come from the widget definitions: the widget reference in
docs/uidp-widgets.md and the widget list that ends docs/uidp-format.md. Run it after changing a widget's
properties; tests/test_uidp_guide.py fails until both are current.

    python tools/uidp_reference.py docs   rewrite both documents in place
    python tools/uidp_reference.py        print the reference
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with contextlib.redirect_stdout(io.StringIO()):  # qfluentwidgets prints an advert when first imported
    from app.core.data_binding import BIND_PROPERTIES
    from app.designer.canvas_item import LAYOUT_TYPES
    from app.widgets.base import PropType
    from app.widgets.basic import ALL_BASIC
    from app.widgets.chart import ALL_CHART
    from app.widgets.comm import ALL_COMM
    from app.widgets.composite import ALL_COMPOSITE
    from app.widgets.display import ALL_DISPLAY
    from app.widgets.layout import ALL_LAYOUT
    from app.widgets.industrial import ALL_INDUSTRIAL

# The line in docs/uidp-format.md and docs/uidp-widgets.md after which the generated part starts.
MARKER = "<!-- 以下由 tools/uidp_reference.py 从控件定义生成，不要手改 -->"

# In the order the main window registers them, which is the palette's order. Walking these lists rather than
# the registry keeps the output the same whichever module a test happened to register first.
WIDGETS = ALL_BASIC + ALL_LAYOUT + ALL_DISPLAY + ALL_CHART + ALL_COMM + ALL_COMPOSITE + ALL_INDUSTRIAL
INDUSTRIAL_TYPES = {meta.type_name for meta in ALL_INDUSTRIAL}
INDUSTRIAL_REFERENCE = "https://raw.githubusercontent.com/txp666/FluentHMI-Studio/main/docs/uidp/industrial.md"
ELECTRONICS_REFERENCE = "https://raw.githubusercontent.com/txp666/FluentHMI-Studio/main/docs/uidp/electronics.md"

TYPE_TEXT = {
    PropType.STRING: "文本", PropType.INT: "整数", PropType.FLOAT: "小数", PropType.BOOL: "true/false",
    PropType.COLOR: "颜色", PropType.ENUM: "选项", PropType.TEXT: "多行文本", PropType.COMMAND: "命令",
    PropType.OBJECT: "对象",
}


def _json(value) -> str:
    """A value as a .uidp spells it, so the newline option "\\r\\n" reads "\\\\r\\\\n"."""
    return "`" + json.dumps(value, ensure_ascii=False) + "`"


def _number(value) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def widget_index() -> str:
    """The widget list that ends docs/uidp-format.md, as Markdown: one line per category, each widget type with
    its name and default size."""
    lines = {}
    for meta in WIDGETS:
        if meta.type_name in INDUSTRIAL_TYPES:
            continue
        lines.setdefault(meta.category.value, []).append(
            f"`{meta.type_name}` {meta.display_name}（{meta.default_width}×{meta.default_height}）")
    return ("\n" + "".join(f"- {category}：{'、'.join(entries)}\n" for category, entries in lines.items())
            + f"- [工业设备与工业仪表的类型和默认值]({INDUSTRIAL_REFERENCE})\n"
            + f"- [汽车电子、电子 DIY 与嵌入式的类型和默认值]({ELECTRONICS_REFERENCE})\n")


SHARED_GROUPS = (
    ("command-common", "命令控件共有属性", ("PushButton", "LineEdit", "ComboBox", "ToggleSwitch", "Slider", "SpinBox")),
    ("link-common", "链路卡片共有属性", ("SerialConfigCard", "TcpConfigCard", "UdpConfigCard", "MqttConfigCard")),
)


def shared_properties(members):
    """Only properties whose complete definitions match in every member are shared."""
    metas = {meta.type_name: meta for meta in WIDGETS}
    return [prop for prop in metas[members[0]].properties
            if all(any(other == prop for other in metas[name].properties) for name in members[1:])]


def property_line(prop):
    line = f"- `{prop.name}`（{prop.label}，{TYPE_TEXT[prop.prop_type]}）默认 {_json(prop.default)}"
    if prop.min_val is not None and prop.max_val is not None:
        line += f"，范围 {_number(prop.min_val)}–{_number(prop.max_val)}"
    if prop.options:
        line += "，可选 " + " ".join(_json(option) for option in prop.options)
    if prop.description:
        line += "，" + prop.description
    return line + "\n"


def widget_reference() -> str:
    """Every widget type with its default size, the property a binding writes and each property's default,
    range and options, as Markdown."""
    out = []
    for anchor, title, members in SHARED_GROUPS:
        out.append(f'\n<a id="{anchor}"></a>\n\n### {title}\n\n')
        out.append("适用于 " + "、".join(f"`{member}`" for member in members) + "。\n\n")
        out.extend(property_line(prop) for prop in shared_properties(members))
    category = None
    for meta in WIDGETS:
        if meta.type_name in INDUSTRIAL_TYPES:
            continue
        if meta.category != category:
            out.append(f"\n### {meta.category.value}\n")
            category = meta.category
        out.append(f"\n#### `{meta.type_name}` {meta.display_name}\n\n")
        line = f"默认尺寸 {meta.default_width}×{meta.default_height}，最小 {meta.min_width}×{meta.min_height}"
        if meta.type_name in LAYOUT_TYPES:
            line += "；**容器**，子控件放在 `children` 里"
        if meta.type_name in BIND_PROPERTIES:
            line += f"；绑定数据时写入 `{BIND_PROPERTIES[meta.type_name]}`"
        out.append(line + "\n\n")
        common = []
        for anchor, title, members in SHARED_GROUPS:
            if meta.type_name in members:
                common.extend(shared_properties(members))
                out.append(f"另见[{title}](#{anchor})。\n\n")
        for prop in meta.properties:
            if prop not in common:
                out.append(property_line(prop))
    out.append(f"\n### 工业设备与仪表\n\n共用属性、各类型默认值和设备特有选项见[工业控件参考]({INDUSTRIAL_REFERENCE})。\n")
    out.append(f"\n### 汽车电子、电子 DIY 与嵌入式\n\n类型、默认值和反馈规则见[电子控件参考]({ELECTRONICS_REFERENCE})；共用属性仍见[工业控件参考]({INDUSTRIAL_REFERENCE})。\n")
    return "".join(out)


def with_generated(document: str, generated: str):
    """``document`` with everything after the marker line replaced by ``generated``, or None when the marker is
    missing."""
    at = document.find(MARKER)
    if at < 0:
        return None
    return document[:at + len(MARKER)] + "\n" + generated


# Each generated document in docs/ and what follows its marker line.
GENERATED = {"uidp-format.md": widget_index, "uidp-widgets.md": widget_reference}


def update(path: Path, generated: str) -> bool:
    document = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    updated = with_generated(document, generated)
    if updated is None:
        print(f"{path} has no line\n{MARKER}", file=sys.stderr)
        return False
    if updated == document:
        print(f"{path} is current")
        return True
    path.write_text(updated, encoding="utf-8", newline="\n")
    print(f"updated {path}")
    return True


def main(argv) -> int:
    if len(argv) < 2:
        sys.stdout.write(widget_reference())
        return 0
    results = [update(Path(argv[1]) / name, generate()) for name, generate in GENERATED.items()]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
