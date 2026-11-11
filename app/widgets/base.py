# coding: utf-8
"""Base class and metadata definitions for all designable widgets."""
import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.i18n import tr, N_


def normalized_range_properties(type_name, properties, changed=None):
    """Keep editable numeric endpoints and their initial value consistent."""
    if type_name not in ("Slider", "SpinBox", "GaugeMeter"):
        return dict(properties)
    props = dict(properties)
    lo, hi = props.get("minimum", 0), props.get("maximum", 100)
    if lo > hi:
        if changed == "maximum":
            lo = hi
        else:
            hi = lo
    value = props.get("value", 50 if type_name == "Slider" else 0)
    props.update(minimum=lo, maximum=hi, value=max(lo, min(hi, value)))
    return props


class PropType(Enum):
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    COLOR = "color"
    ENUM = "enum"
    TEXT = "text"       # multiline string
    COMMAND = "command"  # serial command string
    OBJECT = "object"   # JSON object with its own editor section; gets no ordinary row


@dataclass
class PropDef:
    """Definition of a single editable property."""
    name: str
    label: str
    prop_type: PropType
    default: Any
    options: Optional[List[str]] = None  # for ENUM type
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    description: str = ""  # what the widget reference says about it, when the label is not enough


class WidgetCategory(Enum):
    """A palette category; its value is the Chinese name, shown translated."""
    BASIC = N_("基础控件")
    LAYOUT = N_("布局容器")
    DISPLAY = N_("显示控件")
    CHART = N_("图表控件")
    COMM = N_("通信控件")
    INDUSTRIAL_EQUIPMENT = N_("工业设备")
    INDUSTRIAL_INSTRUMENT = N_("工业仪表")
    AUTOMOTIVE = N_("汽车电子")
    DIY = N_("电子 DIY")
    EMBEDDED = N_("嵌入式")


@dataclass
class WidgetMeta:
    """Metadata describing a designable widget type."""
    type_name: str
    display_name: str
    category: WidgetCategory
    icon: str  # a WidgetIcon or FluentIcon name, see app/common/icon.py
    default_width: int
    default_height: int
    properties: List[PropDef] = field(default_factory=list)
    resizable: bool = True
    min_width: int = 30
    min_height: int = 20

    def get_default_props(self) -> Dict[str, Any]:
        """The properties a widget has when its file leaves them out; the same in every language."""
        # A copy each, so editing one widget's object property cannot change the default.
        return {p.name: copy.deepcopy(p.default) for p in self.properties}

    def get_new_props(self) -> Dict[str, Any]:
        """The properties of a widget added from the palette: the default texts in the interface
        language (a default text is marked with N_ where it is defined), the rest as get_default_props."""
        props = self.get_default_props()
        for p in self.properties:
            if p.prop_type in (PropType.STRING, PropType.TEXT) and isinstance(p.default, str) and p.default:
                props[p.name] = tr(p.default)
        if self.type_name == "RealtimeChart":  # a curve without a name shows 曲线1 whatever the language
            props["_curve_0_name"] = tr("曲线%1", 1)
        return props

    def get_prop_def(self, name: str) -> Optional[PropDef]:
        for p in self.properties:
            if p.name == name:
                return p
        return None
