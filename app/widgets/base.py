# coding: utf-8
"""Base class and metadata definitions for all designable widgets."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PropType(Enum):
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    COLOR = "color"
    ENUM = "enum"
    TEXT = "text"       # multiline string
    COMMAND = "command"  # serial command string


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
    bindable: bool = False  # can be bound to serial data


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
        return {p.name: p.default for p in self.properties}

    def get_prop_def(self, name: str) -> Optional[PropDef]:
        for p in self.properties:
            if p.name == name:
                return p
        return None
