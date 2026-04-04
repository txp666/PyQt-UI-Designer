# coding: utf-8
"""Central registry of all designable widget types."""
from typing import Dict, List, Optional
from app.widgets.base import WidgetMeta, WidgetCategory


class WidgetRegistry:
    _instance: Optional["WidgetRegistry"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._widgets: Dict[str, WidgetMeta] = {}
        return cls._instance

    def register(self, meta: WidgetMeta):
        self._widgets[meta.type_name] = meta

    def get(self, type_name: str) -> Optional[WidgetMeta]:
        return self._widgets.get(type_name)

    def all(self) -> List[WidgetMeta]:
        return list(self._widgets.values())

    def by_category(self, category: WidgetCategory) -> List[WidgetMeta]:
        return [m for m in self._widgets.values() if m.category == category]

    def categories(self) -> List[WidgetCategory]:
        seen = []
        for m in self._widgets.values():
            if m.category not in seen:
                seen.append(m.category)
        return seen


registry = WidgetRegistry()
