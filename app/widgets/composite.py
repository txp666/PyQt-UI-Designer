# coding: utf-8
"""Composite card widgets: connection cards (serial, TCP, MQTT), DataSendCard, DataRecvCard,
LogBox, ProgressRing."""
from html import escape as _escape
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QSizePolicy,
)
from qfluentwidgets import (
    CardWidget, StrongBodyLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ComboBox, LineEdit, SpinBox,
    ProgressRing, FluentIcon as FIF, ToolButton,
    CheckBox, TextEdit, isDarkTheme, setCustomStyleSheet,
)

from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.widget_registry import registry
from app.core.signal_lifetime import SignalConnections
from app.core.command_runtime import MODBUS_DATA_TYPES, MODBUS_FUNCTIONS, MODBUS_ORDERS

try:
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


def _log_html(text):
    return _escape(str(text)).replace("\n", "<br>")


# ---------------------------------------------------------------------------
# Serial Config Card
# ---------------------------------------------------------------------------

from app.core.serial_card import SerialConfigCard as RuntimeSerialCard


class SerialConfigCard(RuntimeSerialCard):
    def __init__(self, parent=None):
        super().__init__(parent)
        from app.core.comm_manager import commHub
        self.set_serial_handler(commHub.serial)


# ---------------------------------------------------------------------------
# TCP / MQTT Config Cards
# ---------------------------------------------------------------------------

from app.core.tcp_card import TcpConfigCard as RuntimeTcpCard
from app.core.mqtt_card import MqttConfigCard as RuntimeMqttCard


class TcpConfigCard(RuntimeTcpCard):
    def __init__(self, parent=None):
        super().__init__(parent)
        from app.core.comm_manager import commHub
        self.set_serial_handler(commHub.tcp)


class MqttConfigCard(RuntimeMqttCard):
    def __init__(self, parent=None):
        super().__init__(parent)
        from app.core.comm_manager import commHub
        self.set_serial_handler(commHub.mqtt)


# ---------------------------------------------------------------------------
# Data Send Card
# ---------------------------------------------------------------------------

class DataSendCard(CardWidget):
    """Card with text input + send button for manual data sending over every connected
    link. Auto-wired to the communication hub. Supports HEX mode via checkbox."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self._title = StrongBodyLabel("数据发送")
        layout.addWidget(self._title)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._input = LineEdit()
        self._input.setPlaceholderText("输入要发送的数据...")
        self._send_btn = PrimaryPushButton(FIF.SEND, "发送")
        self._tip_timer = QTimer(self)
        self._tip_timer.setSingleShot(True)
        self._tip_timer.timeout.connect(self._restore_send_button)
        self._send_btn.clicked.connect(self._do_send)
        self._input.returnPressed.connect(self._do_send)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send_btn)
        layout.addLayout(input_row)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(8)
        self._hex_check = CheckBox("HEX模式")
        self._hex_check.setChecked(False)
        self._newline_combo = ComboBox()
        self._newline_combo.addItems(["无", "\\r\\n", "\\n", "\\r"])
        self._newline_combo.setCurrentIndex(1)
        self._newline_combo.setFixedWidth(80)
        opt_row.addWidget(self._hex_check)
        opt_row.addStretch()
        opt_row.addWidget(BodyLabel("换行符"))
        opt_row.addWidget(self._newline_combo)
        layout.addLayout(opt_row)

    def _do_send(self):
        text = self._input.text().strip()
        if not text:
            self._flash_tip("请输入数据")
            return
        from app.core.comm_manager import commHub
        if not commHub.is_connected:
            self._flash_tip("未连接")
            return

        newline_map = {"无": "", "\\r\\n": "\r\n", "\\n": "\n", "\\r": "\r"}
        suffix = newline_map.get(self._newline_combo.currentText(), "\r\n")

        if self._hex_check.isChecked():
            hex_str = text.replace(" ", "")
            if len(hex_str) % 2 != 0:
                hex_str = "0" + hex_str
            try:
                raw = bytes.fromhex(hex_str)
            except ValueError:
                self._flash_tip("HEX格式错误")
                return
            commHub.send(raw)
        else:
            commHub.send_text(text + suffix)
        self._input.selectAll()

    def _flash_tip(self, msg: str):
        """Briefly show a warning tip on the send button, then restore."""
        self._send_btn.setText(msg)
        self._send_btn.setEnabled(False)
        self._tip_timer.start(1200)

    def _restore_send_button(self):
        self._send_btn.setText("发送")
        self._send_btn.setEnabled(True)

    def set_title(self, t): self._title.setText(t)
    def set_placeholder(self, t): self._input.setPlaceholderText(t)


# ---------------------------------------------------------------------------
# Data Receive Card
# ---------------------------------------------------------------------------

class DataRecvCard(CardWidget):
    """Card showing received serial data with raw/parsed toggle.
    Auto-wired to signalBus."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        self._title = StrongBodyLabel("数据接收")
        self._counter = CaptionLabel("0 条")
        self._counter.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        title_row.addWidget(self._title)
        title_row.addStretch()
        title_row.addWidget(self._counter)
        layout.addLayout(title_row)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(8)
        self._hex_check = CheckBox("HEX显示")
        self._hex_check.setChecked(False)
        self._autoscroll_check = CheckBox("自动滚动")
        self._autoscroll_check.setChecked(True)
        for check in (self._hex_check, self._autoscroll_check):
            # macOS lays a check box out by the native style's smaller rect; this one paints all of itself.
            check.setAttribute(Qt.WA_LayoutUsesWidgetRect)
        self._clear_btn = PushButton("清空")
        self._clear_btn.setFixedWidth(60)
        self._clear_btn.clicked.connect(self._clear)
        opt_row.addWidget(self._hex_check)
        opt_row.addWidget(self._autoscroll_check)
        opt_row.addStretch()
        opt_row.addWidget(self._clear_btn)
        layout.addLayout(opt_row)

        self._output = TextEdit()
        self._output.setReadOnly(True)
        terminal_style = (
            "QTextEdit { font-family: Menlo, Consolas, 'Courier New', monospace; "
            "font-size: 12px; background: #1e1e2e; color: #cdd6f4; "
            "border-radius: 4px; padding: 4px; }"
        )
        # Received messages retain their semantic colors, so keep the terminal
        # background in both themes and register it with Fluent's style manager.
        setCustomStyleSheet(self._output, terminal_style, terminal_style)
        terminal_scroll_bar(self._output)
        layout.addWidget(self._output, 1)

        self._count = 0
        self._max_lines = 1000

        from app.common.signal_bus import signalBus
        self._serial_connections = SignalConnections(self)
        self._serial_connections.connect(signalBus.serialRawReceived, self._on_raw_recv)
        self._serial_connections.connect(signalBus.serialDataSent, self._on_sent)
        self._serial_connections.connect(signalBus.serialConnected, self._on_connected)
        self._serial_connections.connect(signalBus.serialDisconnected, self._on_disconnected)

    def _on_connected(self, port):
        self._append_sys(f"已连接: {port}")

    def _on_disconnected(self):
        self._append_sys("已断开")

    def _on_raw_recv(self, data: bytes):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if self._hex_check.isChecked():
            text = " ".join(f"{b:02X}" for b in data)
        else:
            from app.core.comm_manager import commHub
            text = commHub.decode_raw(data).rstrip("\r\n")
            if not text:
                return
        self._output.append(
            f'<span style="color:#9399b2">[{ts}]</span> '
            f'<span style="color:#a6e3a1">&lt;&lt; {_log_html(text)}</span>')
        self._count += 1
        self._counter.setText(f"{self._count} 条")
        self._trim()
        self._scroll()

    def _on_sent(self, data: bytes):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if self._hex_check.isChecked():
            text = " ".join(f"{b:02X}" for b in data)
        else:
            text = data.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                return
        self._output.append(
            f'<span style="color:#9399b2">[{ts}]</span> '
            f'<span style="color:#f9e2af">&gt;&gt; {_log_html(text)}</span>')
        self._trim()
        self._scroll()

    def _scroll(self):
        if self._autoscroll_check.isChecked():
            sb = self._output.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _append_sys(self, msg: str):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._output.append(
            f'<span style="color:#74c7ec">[{ts}] --- {_log_html(msg)} ---</span>')
        self._trim()

    def _clear(self):
        self._output.clear()
        self._count = 0
        self._counter.setText("0 条")

    def _trim(self):
        doc = self._output.document()
        while doc.blockCount() > self._max_lines:
            cursor = self._output.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def set_title(self, t): self._title.setText(t)
    def set_max_lines(self, n):
        self._max_lines = max(50, n)
        self._trim()


# ---------------------------------------------------------------------------
# Log Display Box
# ---------------------------------------------------------------------------

from app.core.log_runtime import LogDisplayBox as RuntimeLogBox, terminal_scroll_bar


class LogDisplayBox(RuntimeLogBox):
    """The shared log box, auto-wired to signalBus for serial events and data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from app.common.signal_bus import signalBus
        self._serial_connections.connect(signalBus.serialConnected, self._on_connected)
        self._serial_connections.connect(signalBus.serialDisconnected, self._on_disconnected)
        self._serial_connections.connect(signalBus.serialError, self._on_serial_error)
        self._serial_connections.connect(signalBus.serialDataReceived, self._on_parsed_data)


# ---------------------------------------------------------------------------
# Progress Ring Display
# ---------------------------------------------------------------------------

class ProgressRingDisplay(QWidget):
    """Circular progress indicator with value label."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(4)

        self._ring = ProgressRing()
        self._ring.setRange(0, 100)
        self._ring.setValue(0)
        self._ring.setFixedSize(80, 80)
        self._ring.setTextVisible(True)

        self._label = CaptionLabel("进度")
        self._label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self._ring, 0, Qt.AlignCenter)
        layout.addWidget(self._label)

    def set_value(self, v): self._ring.setValue(int(v))
    def set_maximum(self, v): self._ring.setMaximum(int(v))
    def set_label(self, t): self._label.setText(t)
    def set_ring_size(self, s): self._ring.setFixedSize(s, s)


# ---------------------------------------------------------------------------
# Modbus Config Card
# ---------------------------------------------------------------------------

from app.core.modbus_card import ModbusConfigCard as RuntimeModbusCard


class ModbusConfigCard(RuntimeModbusCard):
    def __init__(self, parent=None):
        super().__init__(parent)
        from app.core.comm_manager import commHub
        self.set_serial_handler(commHub)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

MODBUS_CONFIG_META = WidgetMeta(
    type_name="ModbusConfigCard",
    display_name="Modbus 配置卡片",
    category=WidgetCategory.COMPOSITE,
    icon="DEVELOPER_TOOLS",
    default_width=380, default_height=180,
    min_width=280, min_height=120,
    properties=[
        PropDef("title", "标题", PropType.STRING, "Modbus 配置"),
        PropDef("defaultSlave", "默认从站", PropType.INT, 1, min_val=1, max_val=247),
        PropDef("defaultFunc", "默认功能码", PropType.ENUM, "03 读保持寄存器",
                options=list(MODBUS_FUNCTIONS)),
        PropDef("defaultAddr", "默认地址", PropType.INT, 0, min_val=0, max_val=65535),
        PropDef("defaultValue", "默认值/数量", PropType.STRING, "1"),  # what the card writes, or a count
        PropDef("defaultPoll", "默认轮询(ms)", PropType.INT, 0, min_val=0, max_val=60000),
        PropDef("mbDataType", "写入数据类型", PropType.ENUM, "uint16",
                options=list(MODBUS_DATA_TYPES)),
        PropDef("mbRegOrder", "写入寄存器序", PropType.ENUM, MODBUS_ORDERS[0],
                options=list(MODBUS_ORDERS)),
        PropDef("timeout", "响应超时(ms)", PropType.INT, 1000, min_val=10, max_val=60000),
        PropDef("pollList", "轮询表", PropType.TEXT, ""),
    ],
)

# A link card's own frame format, edited in the property panel's 帧格式 section.
PARSER_CONFIG_PROP = PropDef(
    "parserConfig", "帧格式", PropType.OBJECT, {},
    description="帧格式设置，键同工程的 serial.parserConfig；默认解析模式不是「项目设置」时生效，"
                "空对象表示沿用工程设置（模式相同时）或默认值")

SERIAL_CONFIG_META = WidgetMeta(
    type_name="SerialConfigCard",
    display_name="串口配置卡片",
    category=WidgetCategory.COMPOSITE,
    icon="CONNECT",
    default_width=360, default_height=340,
    min_width=200, min_height=50,
    properties=[
        PropDef("title", "标题", PropType.STRING, "串口配置"),
        PropDef("displayMode", "显示模式", PropType.ENUM, "完整",
                options=["完整", "简洁", "单行"]),
        PropDef("defaultParser", "默认解析模式", PropType.ENUM, "项目设置",
                options=["项目设置", "line", "hex", "modbus", "modbus_tcp", "modbus_ascii"]),
        PARSER_CONFIG_PROP,
        PropDef("defaultBaud", "默认波特率", PropType.ENUM, "115200",
                options=["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]),
        PropDef("defaultDatabits", "默认数据位", PropType.ENUM, "8",
                options=["5", "6", "7", "8"]),
        PropDef("defaultParity", "默认校验位", PropType.ENUM, "None",
                options=["None", "Even", "Odd", "Mark", "Space"]),
        PropDef("defaultStopbits", "默认停止位", PropType.ENUM, "1",
                options=["1", "1.5", "2"]),
        PropDef("defaultFlow", "默认流控制", PropType.ENUM, "无",
                options=["无", "RTS/CTS", "XON/XOFF", "DTR/DSR"]),
    ],
)

TCP_CONFIG_META = WidgetMeta(
    type_name="TcpConfigCard",
    display_name="TCP 配置卡片",
    category=WidgetCategory.COMPOSITE,
    icon="GLOBE",
    default_width=360, default_height=290,
    min_width=240, min_height=50,
    properties=[
        PropDef("title", "标题", PropType.STRING, "TCP 配置"),
        PropDef("displayMode", "显示模式", PropType.ENUM, "完整",
                options=["完整", "简洁"]),
        PropDef("defaultMode", "默认模式", PropType.ENUM, "客户端",
                options=["客户端", "服务端"]),
        PropDef("defaultHost", "默认地址", PropType.STRING, "127.0.0.1"),
        PropDef("defaultPort", "默认端口", PropType.INT, 8080, min_val=1, max_val=65535),
        PropDef("defaultParser", "默认解析模式", PropType.ENUM, "项目设置",
                options=["项目设置", "line", "hex", "modbus", "modbus_tcp", "modbus_ascii"]),
        PARSER_CONFIG_PROP,
    ],
)

MQTT_CONFIG_META = WidgetMeta(
    type_name="MqttConfigCard",
    display_name="MQTT 配置卡片",
    category=WidgetCategory.COMPOSITE,
    icon="CLOUD",
    default_width=380, default_height=430,
    min_width=260, min_height=50,
    properties=[
        PropDef("title", "标题", PropType.STRING, "MQTT 配置"),
        PropDef("displayMode", "显示模式", PropType.ENUM, "完整",
                options=["完整", "简洁"]),
        PropDef("defaultHost", "默认服务器", PropType.STRING, "127.0.0.1"),
        PropDef("defaultPort", "默认端口", PropType.INT, 1883, min_val=1, max_val=65535),
        PropDef("defaultClientId", "默认客户端ID", PropType.STRING, ""),
        PropDef("defaultUsername", "默认用户名", PropType.STRING, ""),
        PropDef("defaultPassword", "默认密码", PropType.STRING, ""),
        PropDef("defaultSubscribe", "默认订阅主题", PropType.STRING, "device/data"),
        PropDef("defaultPublish", "默认发布主题", PropType.STRING, "device/cmd"),
        PropDef("defaultQos", "默认 QoS", PropType.ENUM, "0", options=["0", "1", "2"]),
        PropDef("defaultTls", "默认启用 TLS", PropType.BOOL, False),
        PropDef("defaultParser", "默认解析模式", PropType.ENUM, "项目设置",
                options=["项目设置", "line", "hex", "modbus", "modbus_tcp", "modbus_ascii"]),
        PARSER_CONFIG_PROP,
    ],
)

DATA_SEND_META = WidgetMeta(
    type_name="DataSendCard",
    display_name="数据发送卡片",
    category=WidgetCategory.COMPOSITE,
    icon="SEND",
    default_width=350, default_height=140,
    min_width=240, min_height=100,
    properties=[
        PropDef("title", "标题", PropType.STRING, "数据发送"),
        PropDef("placeholder", "提示文字", PropType.STRING, "输入要发送的数据..."),
    ],
)

DATA_RECV_META = WidgetMeta(
    type_name="DataRecvCard",
    display_name="数据接收卡片",
    category=WidgetCategory.COMPOSITE,
    icon="DOWNLOAD",
    default_width=350, default_height=250,
    min_width=240, min_height=120,
    properties=[
        PropDef("title", "标题", PropType.STRING, "数据接收"),
        PropDef("maxLines", "最大行数", PropType.INT, 1000, min_val=50, max_val=50000),
    ],
)

LOG_BOX_META = WidgetMeta(
    type_name="LogBox",
    display_name="日志显示框",
    category=WidgetCategory.COMPOSITE,
    icon="HISTORY",
    default_width=400, default_height=200,
    min_width=200, min_height=80,
    properties=[
        PropDef("maxLines", "最大行数", PropType.INT, 500, min_val=50, max_val=50000),
    ],
)

PROGRESS_RING_META = WidgetMeta(
    type_name="ProgressRingDisplay",
    display_name="进度环",
    category=WidgetCategory.COMPOSITE,
    icon="SPEED_MEDIUM",
    default_width=120, default_height=130,
    min_width=80, min_height=80,
    properties=[
        PropDef("label", "标签", PropType.STRING, "进度"),
        PropDef("value", "当前值", PropType.INT, 0, min_val=0, max_val=100),
        PropDef("maximum", "最大值", PropType.INT, 100, min_val=1, max_val=99999),
    ],
)

ALL_COMPOSITE = [
    SERIAL_CONFIG_META, TCP_CONFIG_META, MQTT_CONFIG_META, MODBUS_CONFIG_META,
    DATA_SEND_META, DATA_RECV_META, LOG_BOX_META, PROGRESS_RING_META,
]

# Cards shared with exported applications, configured through their PROPERTY_SETTERS.
_RUNTIME_CARDS = {"TcpConfigCard": TcpConfigCard, "MqttConfigCard": MqttConfigCard,
                  "ModbusConfigCard": ModbusConfigCard}


def register_composite_widgets():
    for meta in ALL_COMPOSITE:
        registry.register(meta)


def create_composite_widget(type_name: str, props: dict, parent=None) -> QWidget:
    if type_name == "SerialConfigCard":
        w = SerialConfigCard(parent)
        w.set_title(props.get("title", "串口配置"))
        w.set_display_mode(props.get("displayMode", "完整"))
        w.set_default_baud(props.get("defaultBaud", "115200"))
        w.set_default_databits(props.get("defaultDatabits", "8"))
        w.set_default_parity(props.get("defaultParity", "None"))
        w.set_default_stopbits(props.get("defaultStopbits", "1"))
        w.set_default_flow(props.get("defaultFlow", "无"))
        w.set_default_parser(props.get("defaultParser", "项目设置"))
        w.set_parser_config(props.get("parserConfig", {}))
        return w
    if type_name in _RUNTIME_CARDS:
        w = _RUNTIME_CARDS[type_name](parent)
        for prop, method, default in w.PROPERTY_SETTERS:
            getattr(w, method)(props.get(prop, default))
        return w
    if type_name == "DataSendCard":
        w = DataSendCard(parent)
        w.set_title(props.get("title", "数据发送"))
        w.set_placeholder(props.get("placeholder", "输入要发送的数据..."))
        return w
    if type_name == "DataRecvCard":
        w = DataRecvCard(parent)
        w.set_title(props.get("title", "数据接收"))
        w.set_max_lines(props.get("maxLines", 1000))
        return w
    if type_name == "LogBox":
        w = LogDisplayBox(parent)
        w.set_max_lines(props.get("maxLines", 500))
        return w
    if type_name == "ProgressRingDisplay":
        w = ProgressRingDisplay(parent)
        w.set_label(props.get("label", "进度"))
        w.set_maximum(props.get("maximum", 100))
        w.set_value(props.get("value", 0))
        return w
    return None


def apply_composite_property(widget, type_name: str, prop_name: str, value):
    if type_name == "SerialConfigCard":
        if prop_name == "title": widget.set_title(value)
        elif prop_name == "displayMode": widget.set_display_mode(value)
        elif prop_name == "defaultBaud": widget.set_default_baud(value)
        elif prop_name == "defaultDatabits": widget.set_default_databits(value)
        elif prop_name == "defaultParity": widget.set_default_parity(value)
        elif prop_name == "defaultStopbits": widget.set_default_stopbits(value)
        elif prop_name == "defaultFlow": widget.set_default_flow(value)
        elif prop_name == "defaultParser": widget.set_default_parser(value)
        elif prop_name == "parserConfig": widget.set_parser_config(value)
    elif type_name in _RUNTIME_CARDS:
        for prop, method, _default in widget.PROPERTY_SETTERS:
            if prop == prop_name:
                getattr(widget, method)(value)
    elif type_name == "DataSendCard":
        if prop_name == "title": widget.set_title(value)
        elif prop_name == "placeholder": widget.set_placeholder(value)
    elif type_name == "DataRecvCard":
        if prop_name == "title": widget.set_title(value)
        elif prop_name == "maxLines": widget.set_max_lines(value)
    elif type_name == "LogBox":
        if prop_name == "maxLines": widget.set_max_lines(value)
    elif type_name == "ProgressRingDisplay":
        if prop_name == "label": widget.set_label(value)
        elif prop_name == "value": widget.set_value(value)
        elif prop_name == "maximum": widget.set_maximum(value)
