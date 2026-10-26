"""TLS contexts that trust what the operating system trusts.

A Python runtime bundled into an application keeps OpenSSL's certificate paths from the
machine that built it. On another computer those paths usually do not exist, so a default
context trusts nothing and every HTTPS or MQTT-over-TLS connection fails with "unable to
get local issuer certificate". truststore verifies through the operating system instead
(the macOS keychain, the Windows certificate store), including certificates the user
added there.
"""
import ssl


def system_ssl_context():
    """A client context that verifies servers against the operating system's trust store."""
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # not installed, or the platform's certificate API is unavailable
        return ssl.create_default_context()

"""MQTT link shared by the designer and standalone exports.

paho-mqtt runs its network loop on its own thread and calls back from there. Every
callback only emits a queued Qt signal tagged with the connection's generation, so the
GUI thread does all parsing and state changes, and a retired client's late callbacks are
ignored. Each message is one complete frame: a line-mode payload without a trailing
newline is still parsed, and a bare value is also published under its topic name so it
can be bound by topic.
"""
import re
import uuid

from PyQt5.QtCore import QObject, Qt, pyqtSignal

from serial_handler import create_parser


try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - exercised only without the optional dependency
    mqtt = None

_TOPIC_SPLIT = re.compile(r"[\n,;]")


def mqtt_topics(value):
    """Accept a list or a newline/comma/semicolon separated string of topic filters."""
    if value is None:
        return []
    parts = value if isinstance(value, (list, tuple)) else _TOPIC_SPLIT.split(str(value))
    topics = []
    for part in parts:
        topic = str(part).strip()
        if topic and topic not in topics:
            topics.append(topic)
    return topics


def _reason_value(code):
    """paho 2 passes ReasonCode objects, paho 1 plain integers."""
    value = getattr(code, "value", code)
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


# MQTT 5 style CONNACK reason codes; paho 2 also reports MQTT 3.1.1 refusals this way.
_CONNACK_TEXT = {132: "协议版本不支持", 133: "客户端ID无效", 134: "用户名或密码错误",
                 135: "未授权，请检查用户名和密码", 136: "服务器不可用"}
_V1_CONNACK = {1: 132, 2: 133, 3: 136, 4: 134, 5: 135}  # paho 1 passes MQTT 3.1.1 return codes


def _connack_text(code):
    """Why the broker refused a connection, in the user's language where we know it."""
    if isinstance(code, int):
        text = _CONNACK_TEXT.get(_V1_CONNACK.get(code, code))
        if text is None and mqtt is not None and hasattr(mqtt, "connack_string"):
            text = mqtt.connack_string(code)
        return text or str(code)
    return _CONNACK_TEXT.get(_reason_value(code)) or str(code)


def _disconnect_text(code):
    """Why the connection dropped; empty when paho only knows it was lost."""
    if isinstance(code, int):  # paho 1: an MQTT_ERR_* value, 7 = connection lost
        if code == 7:
            return ""
        if mqtt is not None and hasattr(mqtt, "error_string"):
            return mqtt.error_string(code)
        return str(code)
    return "" if _reason_value(code) == 128 else str(code)  # 128: unspecified error


class MqttHandler(QObject):
    dataReceived = pyqtSignal(dict)
    rawReceived = pyqtSignal(bytes)
    dataSent = pyqtSignal(bytes)
    connectionChanged = pyqtSignal(bool)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    error = pyqtSignal(str)
    DEFAULT_CONFIG = {}

    # paho thread -> GUI thread (generation, ...)
    _connectResult = pyqtSignal(int, int, str)
    _connectionLost = pyqtSignal(int, int, str)
    _messageArrived = pyqtSignal(int, str, bytes)

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self._client = None
        self._generation = 0
        self._up = False
        self._topics = []
        self._publish_topic = ""
        self._qos = 0
        self._retain = False
        self._tls = False
        self._parser_setup = ("line", {})
        self._parsers = {}
        self._description = ""
        self._connectResult.connect(self._on_connect_result, Qt.QueuedConnection)
        self._connectionLost.connect(self._on_connection_lost, Qt.QueuedConnection)
        self._messageArrived.connect(self._on_message_arrived, Qt.QueuedConnection)
        self.configure(config or self.DEFAULT_CONFIG)

    def configure(self, config):
        self._config = {"host": "127.0.0.1", "port": 1883, "clientId": "", "username": "",
                        "password": "", "subscribe": "device/data", "publish": "device/cmd",
                        "qos": 0, "retain": False, "tls": False, "keepalive": 60,
                        "parser": "line", "parserConfig": {"separator": ","}, **config}
        self._parser_setup = (self._config["parser"], self._config["parserConfig"])

    @property
    def parser_type(self):
        """The parser in use; Modbus commands are framed to match (MBAP for modbus_tcp)."""
        return self._parser_setup[0]

    @property
    def is_connected(self):
        return self._client is not None and self._up

    @property
    def is_active(self):
        """Connected, connecting, or reconnecting."""
        return self._client is not None

    @property
    def description(self):
        return self._description

    @property
    def topics(self):
        return list(self._topics)

    @property
    def publish_topic(self):
        return self._publish_topic

    def connect(self, host=None, port=None, client_id=None, username=None, password=None,
                subscribe=None, publish=None, qos=None, tls=None, parser_type=None,
                parser_config=None):
        """Start connecting; ``connected`` reports success, ``error`` then ``disconnected`` a failure."""
        if mqtt is None:
            self.error.emit("paho-mqtt 未安装，请运行 pip install paho-mqtt")
            return False
        cfg = self._config

        def pick(value, key):
            return cfg[key] if value is None else value

        try:
            host = str(pick(host, "host")).strip()
            port = int(pick(port, "port"))
            if not host:
                raise ValueError("请填写 MQTT 服务器地址")
            if not 1 <= port <= 65535:
                raise ValueError("端口必须在 1–65535 之间")
            qos = int(pick(qos, "qos"))
            if qos not in (0, 1, 2):
                raise ValueError("QoS 只能是 0、1 或 2")
            topics = mqtt_topics(pick(subscribe, "subscribe"))
            publish_topic = str(pick(publish, "publish")).strip()
            selected_parser = pick(parser_type, "parser")
            selected_config = parser_config
            if selected_config is None:
                selected_config = cfg["parserConfig"] if selected_parser == cfg["parser"] else {}
            create_parser(selected_parser, selected_config)
        except (TypeError, ValueError) as exc:
            self.error.emit(f"MQTT 参数无效: {exc}")
            return False
        if self.is_active:
            self.disconnect()
        self._generation += 1
        generation = self._generation
        client_id = str(pick(client_id, "clientId")).strip() or f"pyqt-ui-{uuid.uuid4().hex[:8]}"
        username = str(pick(username, "username"))
        password = str(pick(password, "password"))
        try:
            if hasattr(mqtt, "CallbackAPIVersion"):
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                                     userdata=generation)
            else:
                client = mqtt.Client(client_id=client_id, userdata=generation)
            if username:
                client.username_pw_set(username, password or None)
            use_tls = bool(pick(tls, "tls"))
            if use_tls:
                client.tls_set_context(system_ssl_context())
            client.on_connect = self._paho_connect
            client.on_connect_fail = self._paho_connect_fail
            client.on_disconnect = self._paho_disconnect
            client.on_message = self._paho_message
            client.connect_async(host, port, int(cfg["keepalive"]))
            client.loop_start()
        except Exception as exc:
            self.error.emit(f"MQTT 连接失败: {exc}")
            return False
        self._client = client
        self._up = False
        self._topics = topics
        self._publish_topic = publish_topic
        self._qos = qos
        self._tls = use_tls
        self._retain = bool(cfg["retain"])
        self._parser_setup = (selected_parser, selected_config)
        self._parsers = {}
        self._description = f"MQTT {host}:{port}"
        return True

    def disconnect(self):
        client = self._client
        if client is None:
            return
        self._client = None
        self._generation += 1  # queued callbacks of this client are now stale
        self._up = False
        self._parsers = {}
        for stop in (client.disconnect, client.loop_stop):
            try:
                stop()
            except Exception:  # the network loop may already be gone
                pass
        self.disconnected.emit()
        self.connectionChanged.emit(False)

    def send(self, data):
        """Publish to the configured topic; True once the client accepted the message."""
        if not self.is_connected:
            return False
        if not self._publish_topic:
            self.error.emit("发送失败: 未设置发布主题")
            return False
        payload = bytes(data)
        try:
            result = self._client.publish(self._publish_topic, payload, qos=self._qos,
                                          retain=self._retain)
            code = getattr(result, "rc", result[0] if isinstance(result, tuple) else 0)
            if code != 0:
                raise OSError(mqtt.error_string(code) if hasattr(mqtt, "error_string") else code)
        except Exception as exc:
            self.error.emit(f"发送失败: {exc}")
            return False
        self.dataSent.emit(payload)
        return True

    def send_text(self, text, encoding="utf-8"):
        return self.send(text.encode(encoding))

    # ---- paho thread ----

    def _paho_connect(self, client, generation, flags, code, *_properties):
        self._connectResult.emit(generation, _reason_value(code), _connack_text(code))

    def _paho_connect_fail(self, client, generation):
        self._connectResult.emit(generation, -1, "无法连接到服务器")

    def _paho_disconnect(self, client, generation, *args):
        # paho 1: (rc) or (rc, properties)   paho 2: (disconnect_flags, reason_code, properties)
        code = args[0] if len(args) <= 2 else args[1]
        self._connectionLost.emit(generation, _reason_value(code), _disconnect_text(code))

    def _paho_message(self, client, generation, message):
        self._messageArrived.emit(generation, message.topic, bytes(message.payload))

    # ---- GUI thread ----

    def _on_connect_result(self, generation, code, message):
        if generation != self._generation or self._client is None:
            return
        if code != 0:
            if code == -1 and self._tls:
                # paho does not say why; an untrusted certificate looks the same as a dead port.
                message += "（已启用 TLS，请检查端口和服务器证书）"
            self.error.emit(f"MQTT 连接失败: {message}")
            self.disconnect()
            return
        for topic in self._topics:
            try:
                result = self._client.subscribe(topic, self._qos)
                code = result[0] if isinstance(result, tuple) else getattr(result, "rc", 0)
                if code != 0:
                    raise ValueError(mqtt.error_string(code) if hasattr(mqtt, "error_string") else code)
            except Exception as exc:
                self.error.emit(f"订阅 {topic} 失败: {exc}")
        self._up = True
        self.connected.emit(self._description)
        self.connectionChanged.emit(True)

    def _on_connection_lost(self, generation, code, message):
        if generation != self._generation or self._client is None or not self._up:
            return
        # paho keeps reconnecting; its next successful CONNACK reports connected again.
        self._up = False
        self._parsers = {}
        self.error.emit("MQTT 连接断开，正在重连" + (f": {message}" if message else ""))
        self.disconnected.emit()
        self.connectionChanged.emit(False)

    def _on_message_arrived(self, generation, topic, payload):
        if generation != self._generation or not self._up:
            return
        self.rawReceived.emit(payload)
        parser = self._parsers.get(topic)
        if parser is None:
            if len(self._parsers) >= 256:  # wildcard subscriptions can fan out widely
                self._parsers = {}
            parser = self._parsers[topic] = create_parser(*self._parser_setup)
        data = payload
        if self._parser_setup[0] == "line" and not payload.endswith(b"\n"):
            data = payload + b"\n"
        for parsed in parser.feed(data):
            if set(parsed) == {"ch0"}:
                parsed[topic] = parsed["ch0"]
            self.dataReceived.emit(parsed)

MqttHandler.DEFAULT_CONFIG = {'parser': 'line', 'parserConfig': {'separator': ','}}
