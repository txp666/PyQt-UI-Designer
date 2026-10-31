# coding: utf-8
"""Base class and metadata definitions for all designable widgets."""
import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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
    BASIC = "基础控件"
    LAYOUT = "布局容器"
    DISPLAY = "显示控件"
    CHART = "图表控件"
    COMM = "通信控件"
    COMPOSITE = "复合卡片"


@dataclass
class WidgetMeta:
    """Metadata describing a designable widget type."""
    type_name: str
    display_name: str
    category: WidgetCategory
    icon: str  # FluentIcon name or path
    default_width: int
    default_height: int
    properties: List[PropDef] = field(default_factory=list)
    resizable: bool = True
    min_width: int = 30
    min_height: int = 20

    def get_default_props(self) -> Dict[str, Any]:
        # A copy each, so editing one widget's object property cannot change the default.
        return {p.name: copy.deepcopy(p.default) for p in self.properties}

    def get_prop_def(self, name: str) -> Optional[PropDef]:
        for p in self.properties:
            if p.name == name:
                return p
        return None
