"""Interface language: the source texts are Simplified Chinese; English comes from one flat table.

The table maps a Chinese source text to its English text, whatever the context. A text missing from
it is shown in Chinese. Until set_language is called the language is Simplified Chinese.
"""
import re
import sys

# An export's modules import this module as ``i18n``; in the designer's process, which can run their
# sources too, that name is this module, so both read the one language.
sys.modules.setdefault("i18n", sys.modules[__name__])

_PLACEHOLDER = re.compile(r"%([1-9])")
_language = "zh_CN"
_table = {}


def resolve(setting):
    """The effective language of a setting: "Auto" follows the system, "zh_CN" and "en_US" are themselves."""
    if setting in ("zh_CN", "en_US"):
        return setting
    from PyQt5.QtCore import QLocale  # here, so that importing this module needs no Qt
    # The first preferred UI language, not the format locale: inside a macOS bundle the latter only
    # reports the languages the bundle declares.
    preferred = QLocale.system().uiLanguages()
    locale = QLocale(preferred[0]) if preferred else QLocale.system()
    return "zh_CN" if locale.language() == QLocale.Chinese else "en_US"


def set_language(setting, table):
    """Sets the language from a setting; ``table`` (source text -> English) is used only for English."""
    global _language, _table
    _language = resolve(setting)
    _table = dict(table) if _language == "en_US" else {}


def language():
    return _language


def tr(text, *args):
    """``text`` in the current language, with %1 to %9 replaced by ``args`` in one pass."""
    text = _table.get(text, text)
    if not args:
        return text

    def argument(match):
        index = int(match.group(1))
        return str(args[index - 1]) if index <= len(args) else match.group(0)
    return _PLACEHOLDER.sub(argument, text)


def N_(text):
    """Marks a text that is translated where it is shown."""
    return text
