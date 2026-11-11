"""Metadata and factory for the shared industrial SVG catalog."""
from app.core.industrial_runtime import INDUSTRIAL_CATALOG, INDUSTRIAL_TYPES, IndustrialWidget
from app.core.i18n import N_
from app.core.widget_registry import registry
from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType

_GROUP_CATEGORIES = {
    "instrument": WidgetCategory.INDUSTRIAL_INSTRUMENT,
    "equipment": WidgetCategory.INDUSTRIAL_EQUIPMENT,
    "automotive": WidgetCategory.AUTOMOTIVE,
    "diy": WidgetCategory.DIY,
    "embedded": WidgetCategory.EMBEDDED,
}

ALL_INDUSTRIAL = [WidgetMeta(
    type_name=spec["type"], display_name=spec["name"],
    category=_GROUP_CATEGORIES[spec["group"]],
    icon="SPEED_HIGH" if spec["group"] == "instrument" else "APPLICATION",
    default_width=160, default_height=140, min_width=80, min_height=72,
    properties=[
        PropDef("title", N_("标题"), PropType.STRING, spec["name"]),
        PropDef("unit", N_("单位"), PropType.STRING, spec["unit"]),
        PropDef("value", N_("当前值"), PropType.FLOAT, spec["value"], min_val=-1e12, max_val=1e12),
        PropDef("minimum", N_("最小值"), PropType.FLOAT, spec["minimum"], min_val=-1e12, max_val=1e12),
        PropDef("maximum", N_("最大值"), PropType.FLOAT, spec["maximum"], min_val=-1e12, max_val=1e12),
        PropDef("decimals", N_("小数位数"), PropType.INT, spec["decimals"], min_val=0, max_val=6),
    ]) for group in _GROUP_CATEGORIES for spec in INDUSTRIAL_CATALOG if spec["group"] == group]


def register_industrial_widgets():
    for meta in ALL_INDUSTRIAL:
        registry.register(meta)


def create_industrial_widget(type_name, props, parent=None):
    if type_name in INDUSTRIAL_TYPES:
        return IndustrialWidget(type_name, props, parent)


def apply_industrial_property(widget, type_name, name, value):
    if type_name in INDUSTRIAL_TYPES:
        widget.set_property(name, value)

# Optional engineering settings are present only on symbols that support them.
for meta in ALL_INDUSTRIAL:
    spec = next(item for item in INDUSTRIAL_CATALOG if item["type"] == meta.type_name)
    if "limits" in spec:
        low, high = spec["limits"]
        meta.properties.extend([
            PropDef("showLimits", N_("显示限值"), PropType.BOOL, spec.get("limitsOn", False)),
            PropDef("lowLimit", N_("低限"), PropType.FLOAT, low, min_val=-1e12, max_val=1e12),
            PropDef("highLimit", N_("高限"), PropType.FLOAT, high, min_val=-1e12, max_val=1e12)])
    if meta.type_name == "FlowPipe":
        meta.properties.extend([
            PropDef("pipeShape", N_("管道形状"), PropType.ENUM, "弯管", options=["弯管", "直管"]),  # i18n: value
            PropDef("pipeDirection", N_("管道布局"), PropType.ENUM, "正向布局", options=["正向布局", "镜像布局"]),  # i18n: value
            PropDef("pipeWidth", N_("管道宽度"), PropType.INT, 16, min_val=8, max_val=26)])
    if meta.type_name in ("Motor", "Cylinder"):
        options = ["转速", "运行位"] if meta.type_name == "Motor" else ["行程", "端位状态"]  # i18n: value
        meta.properties.append(PropDef("feedbackMode", N_("反馈模式"), PropType.ENUM, options[0], options=options))  # i18n: value

for meta in ALL_INDUSTRIAL:
    spec = next(item for item in INDUSTRIAL_CATALOG if item["type"] == meta.type_name)
    if spec["mode"] in ("word", "timing"):
        meta.properties = [prop for prop in meta.properties if prop.name in ("title", "value")]
        value = next(prop for prop in meta.properties if prop.name == "value")
        value.prop_type = PropType.INT
        value.min_val, value.max_val = 0, 65535
        meta.properties.append(PropDef("bitProfile", N_("位配置"), PropType.STRING, "default"))
    elif spec["mode"] == "encoder":
        meta.properties = [prop for prop in meta.properties if prop.name in ("title", "value")]
        value = next(prop for prop in meta.properties if prop.name == "value")
        value.prop_type = PropType.INT
        value.min_val, value.max_val = -(2**53-1), 2**53-1
        meta.properties.append(PropDef("pulsesPerTurn", N_("每圈脉冲数"), PropType.INT, 1024, min_val=1, max_val=2**53-1))
    elif spec["mode"] in ("cells", "supply"):
        meta.properties = [prop for prop in meta.properties if prop.name == "title"]
    if "size" in spec:
        meta.default_width, meta.default_height = spec["size"]
