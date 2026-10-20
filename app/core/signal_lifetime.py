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
