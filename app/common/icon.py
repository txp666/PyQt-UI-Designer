# coding: utf-8
"""The icons widget types show in the palette, and the designer's panel switches."""
from enum import Enum
from pathlib import Path

from qfluentwidgets import FluentIcon, FluentIconBase, Theme, getIconColor

_FOLDER = Path(__file__).resolve().parents[1] / "resource" / "widget_icons"


class WidgetIcon(FluentIconBase, Enum):
    """Pictures of controls that qfluentwidgets has no icon for, and of the designer's side panels shown or
    hidden, drawn in its style, one file per theme. FluentHMI Studio has the same files under the same names."""

    BUTTON = "Button"
    TEXT_FIELD = "TextField"
    DROPDOWN = "Dropdown"
    TOGGLE = "Toggle"
    SLIDER = "Slider"
    SPIN_BOX = "SpinBox"
    COLUMNS = "Columns"
    ROWS = "Rows"
    GROUP_BOX = "GroupBox"
    TABS = "Tabs"
    CARD = "Card"
    LED = "Led"
    SEVEN_SEGMENT = "SevenSegment"
    PROGRESS_BAR = "ProgressBar"
    PROGRESS_RING = "ProgressRing"
    TABLE = "Table"
    SERIAL_PORT = "SerialPort"
    PANEL_LEFT = "PanelLeft"
    PANEL_LEFT_ON = "PanelLeftOn"
    PANEL_RIGHT = "PanelRight"
    PANEL_RIGHT_ON = "PanelRightOn"

    def path(self, theme=Theme.AUTO):
        return (_FOLDER / f"{self.value}_{getIconColor(theme)}.svg").as_posix()


def widget_icon(name: str):
    """The icon a WidgetMeta names, a WidgetIcon or a FluentIcon, or None when there is none by that name."""
    for icons in (WidgetIcon, FluentIcon):
        if name in icons.__members__:
            return icons[name]
    return None
