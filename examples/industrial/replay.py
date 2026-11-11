"""Replay the gallery's sample frames to a local desktop or browser connection."""
import argparse
import itertools
import signal
import socketserver
import time
from pathlib import Path


def serve_tcp(port, frames):
    class Client(socketserver.BaseRequestHandler):
        def handle(self):
            for frame in itertools.cycle(frames):
                try:
                    self.request.sendall(frame)
                except OSError:
                    return
                time.sleep(2)

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server(("127.0.0.1", port), Client) as server:
        print(f"TCP 127.0.0.1:{server.server_address[1]}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def serve_websocket(port, frames):
    from PyQt5.QtCore import QCoreApplication, QTimer
    from PyQt5.QtNetwork import QHostAddress
    from PyQt5.QtWebSockets import QWebSocketServer

    app = QCoreApplication([])
    server = QWebSocketServer("Industrial replay", QWebSocketServer.NonSecureMode)
    if not server.listen(QHostAddress.LocalHost, port):
        raise SystemExit(server.errorString())
    print(f"WebSocket ws://127.0.0.1:{server.serverPort()}", flush=True)

    def accept():
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            sequence = itertools.cycle(frames)
            timer = QTimer(client)
            timer.timeout.connect(lambda c=client, s=sequence: c.sendBinaryMessage(next(s)))
            client.disconnected.connect(timer.stop)
            client.disconnected.connect(client.deleteLater)
            client.sendBinaryMessage(next(sequence))
            timer.start(2000)

    server.newConnection.connect(accept)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(200)
    app.exec()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", action="store_true", help="serve WebSocket using the Python designer's PyQt5 environment")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--frames", type=Path, default=Path(__file__).with_name("反馈回放.jsonl"),
                        help="path to newline-delimited JSON feedback")
    args = parser.parse_args()
    frames = args.frames.read_bytes().splitlines(keepends=True)
    if args.web:
        serve_websocket(args.port, frames)
    else:
        serve_tcp(args.port, frames)
