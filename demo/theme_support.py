"""Explicit Qt signal lifetimes, including compiled Python callables."""


class SignalConnections:
    """Disconnect external signals when their owning QObject is destroyed.

    PyQt cannot always infer the QObject receiver of a compiled bound method.
    Relays therefore have an explicit lifetime and release their callback before
    disconnecting, so already queued deliveries also become harmless.
    """

    def __init__(self, owner):
        self._connections = []
        owner.destroyed.connect(self.clear)

    def connect(self, signal, slot, *args, **kwargs):
        callback = [slot]

        def relay(*values):
            current = callback[0]
            if current is not None:
                current(*values)

        connection = signal.connect(relay, *args, **kwargs)
        self._connections.append((signal, connection, callback))
        return connection

    def clear(self, *_):
        connections, self._connections = self._connections, []
        for _signal, _connection, callback in connections:
            callback[0] = None
        for signal, connection, _callback in connections:
            try:
                signal.disconnect(connection)
            except (TypeError, RuntimeError):
                # The sender or its connection may already have been destroyed.
                pass

"""Theme coordination shared by the designer and exported applications."""
import darkdetect

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtGui import QColor, QPalette
from qfluentwidgets import Theme, isDarkTheme, qconfig, setTheme, themeColor



class ThemeController(QObject):
    """Keep native Qt widgets and Fluent widgets on the same theme."""

    def __init__(self, app, mode="Auto"):
        super().__init__(app)
        self._app = app
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._check_system_theme)
        self._external_connections = SignalConnections(self)
        self._external_connections.connect(qconfig.themeChangedFinished, self._apply_palette)
        self._external_connections.connect(app.aboutToQuit, self._timer.stop)
        mode = mode if isinstance(mode, Theme) else Theme(mode)
        # setTheme alone skips resolving Auto when the saved mode is unchanged.
        qconfig.theme = mode
        setTheme(mode, save=False)

    def _apply_palette(self):
        dark = isDarkTheme()
        palette = QPalette()
        colors = {
            QPalette.Window: "#202020" if dark else "#ffffff",
            QPalette.WindowText: "#f0f0f0" if dark else "#202020",
            QPalette.Base: "#2b2b2b" if dark else "#ffffff",
            QPalette.AlternateBase: "#323232" if dark else "#f5f5f5",
            QPalette.Text: "#f0f0f0" if dark else "#202020",
            QPalette.Button: "#333333" if dark else "#f5f5f5",
            QPalette.ButtonText: "#f0f0f0" if dark else "#202020",
            QPalette.ToolTipBase: "#2b2b2b" if dark else "#ffffff",
            QPalette.ToolTipText: "#f0f0f0" if dark else "#202020",
            QPalette.BrightText: "#ffffff",
            QPalette.Highlight: themeColor(),
            QPalette.HighlightedText: "#202020" if dark else "#ffffff",
            QPalette.Link: "#60cdff" if dark else "#0067c0",
            QPalette.LinkVisited: "#c4a7ff" if dark else "#6b35a5",
            QPalette.PlaceholderText: "#a0a0a0" if dark else "#606060",
        }
        for role, color in colors.items():
            palette.setColor(role, QColor(color))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role,
                             QColor("#888888" if dark else "#777777"))
        self._app.setPalette(palette)
        if qconfig.get(qconfig.themeMode) == Theme.AUTO:
            self._timer.start()
        else:
            self._timer.stop()

    def _check_system_theme(self):
        if qconfig.get(qconfig.themeMode) != Theme.AUTO:
            return
        detected = darkdetect.theme()
        if detected not in ("Light", "Dark") or Theme(detected) == qconfig.theme:
            return
        # The preference stays Auto; notify Fluent paint-based widgets too.
        qconfig.theme = Theme(detected)
        qconfig.themeChanged.emit(Theme.AUTO)
        setTheme(Theme.AUTO, save=False)
