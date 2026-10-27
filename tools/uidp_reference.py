# coding: utf-8
"""Regenerates the widget reference at the end of docs/uidp-format.md from the widget definitions. Run it after
changing a widget's properties; tests/test_uidp_guide.py fails until the document is current.

    python tools/uidp_reference.py docs/uidp-format.md   rewrite the document in place
    python tools/uidp_reference.py                       print the reference
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

# The line in docs/uidp-format.md after which the generated reference starts.
MARKER = "<!-- 以下由 tools/uidp_reference.py 从控件定义生成，不要手改 -->"

# In the order the main window registers them, which is the palette's order. Walking these lists rather than
# the registry keeps the output the same whichever module a test happened to register first.
WIDGETS = ALL_BASIC + ALL_LAYOUT + ALL_DISPLAY + ALL_CHART + ALL_COMM + ALL_COMPOSITE

TYPE_TEXT = {
    PropType.STRING: "文本", PropType.INT: "整数", PropType.FLOAT: "小数", PropType.BOOL: "true/false",
    PropType.COLOR: "颜色", PropType.ENUM: "选项", PropType.TEXT: "多行文本", PropType.COMMAND: "命令",
}


def _json(value) -> str:
    """A value as a .uidp spells it, so the newline option "\\r\\n" reads "\\\\r\\\\n"."""
    return "`" + json.dumps(value, ensure_ascii=False) + "`"


def _number(value) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def widget_reference() -> str:
    """Every widget type with its default size, the property a binding writes and each property's default,
    range and options, as Markdown."""
    out = []
    category = None
    for meta in WIDGETS:
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
        for prop in meta.properties:
            line = f"- `{prop.name}`（{prop.label}，{TYPE_TEXT[prop.prop_type]}）默认 {_json(prop.default)}"
            if prop.min_val is not None and prop.max_val is not None:
                line += f"，范围 {_number(prop.min_val)}–{_number(prop.max_val)}"
            if prop.options:
                line += "，可选 " + " ".join(_json(option) for option in prop.options)
            out.append(line + "\n")
    return "".join(out)


def with_widget_reference(document: str):
    """``document`` with everything after the marker line replaced by the current reference, or None when the
    marker is missing."""
    at = document.find(MARKER)
    if at < 0:
        return None
    return document[:at + len(MARKER)] + "\n" + widget_reference()


def main(argv) -> int:
    if len(argv) < 2:
        sys.stdout.write(widget_reference())
        return 0
    path = Path(argv[1])
    document = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    updated = with_widget_reference(document)
    if updated is None:
        print(f"{path} has no line\n{MARKER}", file=sys.stderr)
        return 1
    if updated == document:
        print(f"{path} is current")
        return 0
    path.write_text(updated, encoding="utf-8", newline="\n")
    print(f"updated {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
