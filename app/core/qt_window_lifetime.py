"""Explicit lifetimes for Fluent's external window and configuration signals."""
from functools import update_wrapper


def _bridge_fluent_slot(cls, name, argument_count):
    original = getattr(cls, name)
    if getattr(original, "_designer_signal_lifetimes", False):
        return

    # PyQt recognizes genuine Python bound methods as QObject receivers, but
    # not Nuitka's compiled_method objects. Runtime-created functions keep this
    # distinction in a compiled app. Exact arity also preserves Qt's argument
    # truncation (themeChanged supplies a Theme to a zero-argument handler).
    parameters = ", value" if argument_count else ""
    values = "value" if argument_count else ""
    namespace = {}
    exec(
        f"def {name}(self{parameters}):\n"
        f"    return _original.__get__(self, type(self))({values})\n",
        {"_original": original}, namespace,
    )
    bridge = namespace[name]
    update_wrapper(bridge, original)
    bridge._designer_signal_lifetimes = True
    setattr(cls, name, bridge)


def install_fluent_signal_lifetimes():
    """Give Fluent's long-lived signals QObject-aware slots before creation."""
    from qfluentwidgets import (
        OptionsSettingCard, SwitchSettingCard, RangeSettingCard,
        ColorSettingCard, ComboBoxSettingCard,
    )
    from qfluentwidgets.common.animation import BackgroundAnimationWidget
    from qfluentwidgets.window.fluent_window import FluentWidget, FluentTitleBar

    _bridge_fluent_slot(BackgroundAnimationWidget, "_updateBackgroundColor", 0)
    _bridge_fluent_slot(FluentWidget, "_onThemeChangedFinished", 0)
    _bridge_fluent_slot(FluentTitleBar, "setTitle", 1)
    _bridge_fluent_slot(FluentTitleBar, "setIcon", 1)
    for cls in (OptionsSettingCard, SwitchSettingCard, RangeSettingCard,
                ColorSettingCard, ComboBoxSettingCard):
        _bridge_fluent_slot(cls, "setValue", 1)


class TitleBarLifecycleMixin:
    """Install QObject-aware slots before Fluent creates its widget tree.

    FluentWindow replaces its initial FluentWidgetTitleBar during construction.
    Both title bars must connect the Python bridge from the start: retrieving a
    fresh compiled bound method later cannot reliably disconnect the first one.
    """

    def __init__(self, *args, **kwargs):
        install_fluent_signal_lifetimes()
        super().__init__(*args, **kwargs)
