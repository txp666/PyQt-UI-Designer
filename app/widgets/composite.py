# coding: utf-8
"""Composite card widgets: connection cards (serial, TCP, UDP, MQTT), DataSendCard, DataRecvCard,
LogBox, ModbusSlaveTable."""
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
    FluentIcon as FIF, ToolButton,
    CheckBox, TextEdit, isDarkTheme, setCustomStyleSheet,
)

from app.widgets.base import WidgetMeta, WidgetCategory, PropDef, PropType
from app.core.i18n import tr, N_
from app.core.widget_registry import registry
from app.core.signal_lifetime import SignalConnections

try:
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


def _log_html(text):
    return _escape(str(text)).replace("\n", "<br>")


# ---------------------------------------------------------------------------
# Link cards (serial, TCP, UDP, MQTT): the runtime cards themselves. Each owns its link once the
# preview hands it the hub (preview_interface.PreviewCanvas); on the canvas a card has no link.
# ---------------------------------------------------------------------------

from app.core.serial_card import SerialConfigCard
from app.core.tcp_card import TcpConfigCard
from app.core.udp_card import UdpConfigCard
from app.core.mqtt_card import MqttConfigCard


# ---------------------------------------------------------------------------
# Data Send Card
# ---------------------------------------------------------------------------

class DataSendCard(CardWidget):
    """Card with text input + send button for manual data sending over every connected
    link. Auto-wired to the communication hub. Supports HEX mode via checkbox."""

    _NEWLINES = {"无": "", "\\r\\n": "\r\n", "\\n": "\n", "\\r": "\r"}  # i18n: value

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self._title = StrongBodyLabel(tr("数据发送"))
        layout.addWidget(self._title)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._input = LineEdit()
        self._input.setPlaceholderText(tr("输入要发送的数据..."))
        self._send_btn = PrimaryPushButton(FIF.SEND, tr("发送"))
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
        self._hex_check = CheckBox(tr("HEX模式"))
        self._hex_check.setChecked(False)
        self._newline_combo = ComboBox()
        for newline in self._NEWLINES:  # the newline's name shown translated, the name itself as data
            self._newline_combo.addItem(tr(newline), userData=newline)
        self._newline_combo.setCurrentIndex(1)
        self._newline_combo.setFixedWidth(80)
        opt_row.addWidget(self._hex_check)
        opt_row.addStretch()
        opt_row.addWidget(BodyLabel(tr("换行符")))
        opt_row.addWidget(self._newline_combo)
        layout.addLayout(opt_row)

    def _do_send(self):
        text = self._input.text().strip()
        if not text:
            self._flash_tip(tr("请输入数据"))
            return
        from app.core.comm_manager import commHub
        if not commHub.is_connected:
            self._flash_tip(tr("未连接"))
            return

        suffix = self._NEWLINES.get(self._newline_combo.currentData(), "\r\n")

        if self._hex_check.isChecked():
            hex_str = text.replace(" ", "")
            if len(hex_str) % 2 != 0:
                hex_str = "0" + hex_str
            try:
                raw = bytes.fromhex(hex_str)
            except ValueError:
                self._flash_tip(tr("HEX格式错误"))
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
        self._send_btn.setText(tr("发送"))
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
        self._title = StrongBodyLabel(tr("数据接收"))
        self._counter = CaptionLabel(tr("%1 条", 0))
        self._counter.setTextColor(QColor("#606060"), QColor("#b0b0b0"))
        title_row.addWidget(self._title)
        title_row.addStretch()
        title_row.addWidget(self._counter)
        layout.addLayout(title_row)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(8)
        self._hex_check = CheckBox(tr("HEX显示"))
        self._hex_check.setChecked(False)
        self._autoscroll_check = CheckBox(tr("自动滚动"))
        self._autoscroll_check.setChecked(True)
        for check in (self._hex_check, self._autoscroll_check):
            # macOS lays a check box out by the native style's smaller rect; this one paints all of itself.
            check.setAttribute(Qt.WA_LayoutUsesWidgetRect)
        self._clear_btn = PushButton(tr("清空"))
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
        self._append_sys(tr("已连接: %1", port))

    def _on_disconnected(self):
        self._append_sys(tr("已断开"))

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
        self._counter.setText(tr("%1 条", self._count))
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
        self._counter.setText(tr("%1 条", 0))

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
        self._serial_connections.connect(signalBus.serialSlaveLog, self.append_log)

    def _on_parsed_data(self, data):
        from app.core.comm_manager import commHub
        if not commHub.slave_data:  # a slave message: the request and reply lines tell what happened
            super()._on_parsed_data(data)


# ---------------------------------------------------------------------------
# Register table of a Modbus slave
# ---------------------------------------------------------------------------

from app.core.slave_table import ModbusSlaveTable as RuntimeSlaveTable
from app.core.modbus_slave import SLAVE_ROLE, store_from_properties

SLAVE_CARD_TYPES = ("SerialConfigCard", "TcpConfigCard", "UdpConfigCard")


class ModbusSlaveTable(RuntimeSlaveTable):
    """The shared register table. On the designer canvas it shows the areas of the first card in the slave
    role with their initial values, kept current as the design changes; the preview hands it the running slave."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from app.common.signal_bus import signalBus
        self._design = None  # the properties shown on the canvas
        self._design_timer = QTimer(self)  # one look at the design after a burst of edits
        self._design_timer.setSingleShot(True)
        self._design_timer.timeout.connect(self._show_design)
        self._design_connections = SignalConnections(self)
        for changed in (signalBus.canvasChanged, signalBus.projectLoaded):
            self._design_connections.connect(changed, self._design_changed)
        self._design_timer.start(0)

    def set_slave_device(self, device):
        self._design_connections.clear()
        self._design_timer.stop()
        super().set_slave_device(device)

    def _design_changed(self, *_):
        self._design_timer.start(0)

    def _show_design(self):
        proxy = self.graphicsProxyWidget()
        scene = proxy.scene() if proxy is not None else None
        if scene is None or not hasattr(scene, "top_level_canvas_items"):
            return

        def first_slave(items):
            for item in items:
                if item.type_name in SLAVE_CARD_TYPES and item.properties.get("modbusRole") == SLAVE_ROLE:
                    return item
                found = first_slave(item._container_children)
                if found is not None:
                    return found
            return None

        card = first_slave(scene.top_level_canvas_items())
        design = None if card is None else {key: value for key, value in card.properties.items()
                                            if key.startswith("slave")}
        if design != self._design:
            self._design = design
            self.show_store(None if design is None else store_from_properties(design))


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

# What a link card hands the Modbus poller while its link is connected and parses Modbus (the first
# such card in the document counts); the property panel shows them while the card's own parser is a
# Modbus one.
MODBUS_LINK_PROPS = [
    PropDef("modbusPeriod", N_("默认轮询(ms)"), PropType.INT, 500, min_val=10, max_val=60000),
    PropDef("modbusTimeout", N_("响应超时(ms)"), PropType.INT, 1000, min_val=10, max_val=60000),
    PropDef("modbusSlave", N_("默认从站"), PropType.INT, 1, min_val=1, max_val=247),
]


# The labels of each area's first address and size.
_SLAVE_AREA_LABELS = {
    "Co": (N_("线圈起始"), N_("线圈数量")),
    "Di": (N_("离散输入起始"), N_("离散输入数量")),
    "Hr": (N_("保持寄存器起始"), N_("保持寄存器数量")),
    "Ir": (N_("输入寄存器起始"), N_("输入寄存器数量")),
}


def _slave_area_props(table):
    start, count = _SLAVE_AREA_LABELS[table]
    return [PropDef(f"slave{table}Start", start, PropType.INT, 0, min_val=0, max_val=65535),
            PropDef(f"slave{table}Count", count, PropType.INT, 100, min_val=0, max_val=10000)]


# A serial, TCP or UDP card's Modbus role, the polling settings (主站) and the slave settings (从站): the panel
# shows the role and 默认从站 while the card's own parser is a Modbus one, and the settings of its role.
MODBUS_ROLE_PROPS = [
    PropDef("modbusRole", N_("Modbus 角色"), PropType.ENUM, "主站", options=["主站", "从站"],  # i18n: value
            description="从站：解析模式为 modbus 或 modbus_tcp 时应答外部主站"),  # i18n: ignore
    *MODBUS_LINK_PROPS,
    PropDef("modbusDelay", N_("响应延时(ms)"), PropType.INT, 0, min_val=0, max_val=5000),
    PropDef("modbusExceptions", N_("异常响应"), PropType.BOOL, True, description="关掉后出错的请求不应答"),  # i18n: ignore
    *_slave_area_props("Co"), *_slave_area_props("Di"), *_slave_area_props("Hr"), *_slave_area_props("Ir"),
    PropDef("slaveInit", N_("初始值"), PropType.TEXT, "",
            description="每行一条 `区地址=值`，如 `hr100=1234`、`co3=1`；寄存器 −32768–65535，线圈、离散输入 0 或 1"),  # i18n: ignore
]

# A link card's own frame format, edited in the property panel's 帧格式 section.
PARSER_CONFIG_PROP = PropDef(
    "parserConfig", N_("帧格式"), PropType.OBJECT, {},
    description="帧格式设置，键同工程的 serial.parserConfig；默认解析模式不是「项目设置」时生效，"  # i18n: ignore
                "空对象表示沿用工程设置（模式相同时）或默认值")  # i18n: ignore

SERIAL_CONFIG_META = WidgetMeta(
    type_name="SerialConfigCard",
    display_name=N_("串口配置卡片"),
    category=WidgetCategory.COMM,
    icon="SERIAL_PORT",
    default_width=360, default_height=320,
    min_width=200, min_height=50,
    properties=[
        PropDef("title", N_("标题"), PropType.STRING, N_("串口配置")),
        PropDef("displayMode", N_("显示模式"), PropType.ENUM, "完整",  # i18n: value
                options=["完整", "简洁", "单行"]),  # i18n: value
        PropDef("defaultParser", N_("默认解析模式"), PropType.ENUM, "项目设置",  # i18n: value
                options=["项目设置", "line", "hex", "modbus", "modbus_tcp", "modbus_ascii"]),  # i18n: value
        *MODBUS_ROLE_PROPS,
        PARSER_CONFIG_PROP,
        PropDef("defaultBaud", N_("默认波特率"), PropType.ENUM, "115200",
                options=["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]),
        PropDef("defaultDatabits", N_("默认数据位"), PropType.ENUM, "8",
                options=["5", "6", "7", "8"]),
        PropDef("defaultParity", N_("默认校验位"), PropType.ENUM, "None",
                options=["None", "Even", "Odd", "Mark", "Space"]),
        PropDef("defaultStopbits", N_("默认停止位"), PropType.ENUM, "1",
                options=["1", "1.5", "2"]),
        PropDef("defaultFlow", N_("默认流控制"), PropType.ENUM, "无",  # i18n: value
                options=["无", "RTS/CTS", "XON/XOFF", "DTR/DSR"]),  # i18n: value
    ],
)

TCP_CONFIG_META = WidgetMeta(
    type_name="TcpConfigCard",
    display_name=N_("TCP 配置卡片"),
    category=WidgetCategory.COMM,
    icon="GLOBE",
    default_width=360, default_height=250,
    min_width=240, min_height=50,
    properties=[
        PropDef("title", N_("标题"), PropType.STRING, N_("TCP 配置")),
        PropDef("displayMode", N_("显示模式"), PropType.ENUM, "完整",  # i18n: value
                options=["完整", "简洁"]),  # i18n: value
        PropDef("defaultMode", N_("默认模式"), PropType.ENUM, "客户端",  # i18n: value
                options=["客户端", "服务端"]),  # i18n: value
        PropDef("defaultHost", N_("默认地址"), PropType.STRING, "127.0.0.1"),
        PropDef("defaultPort", N_("默认端口"), PropType.INT, 8080, min_val=1, max_val=65535),
        PropDef("defaultParser", N_("默认解析模式"), PropType.ENUM, "项目设置",  # i18n: value
                options=["项目设置", "line", "hex", "modbus", "modbus_tcp", "modbus_ascii"]),  # i18n: value
        *MODBUS_ROLE_PROPS,
        PARSER_CONFIG_PROP,
    ],
)

UDP_CONFIG_META = WidgetMeta(
    type_name="UdpConfigCard",
    display_name=N_("UDP 配置卡片"),
    category=WidgetCategory.COMM,
    icon="WIFI",
    default_width=360, default_height=220,
    min_width=240, min_height=50,
    properties=[
        PropDef("title", N_("标题"), PropType.STRING, N_("UDP 配置")),
        PropDef("displayMode", N_("显示模式"), PropType.ENUM, "完整",  # i18n: value
                options=["完整", "简洁"]),  # i18n: value
        PropDef("defaultLocalPort", N_("默认本地端口"), PropType.INT, 0, min_val=0, max_val=65535,
                description="0 表示由系统选一个空闲端口"),  # i18n: ignore
        PropDef("defaultHost", N_("默认远程地址"), PropType.STRING, "127.0.0.1",
                description="留空则回复最后发送方"),  # i18n: ignore
        PropDef("defaultPort", N_("默认远程端口"), PropType.INT, 8080, min_val=1, max_val=65535),
        PropDef("defaultParser", N_("默认解析模式"), PropType.ENUM, "项目设置",  # i18n: value
                options=["项目设置", "line", "hex", "modbus", "modbus_tcp", "modbus_ascii"]),  # i18n: value
        *MODBUS_ROLE_PROPS,
        PARSER_CONFIG_PROP,
    ],
)

MQTT_CONFIG_META = WidgetMeta(
    type_name="MqttConfigCard",
    display_name=N_("MQTT 配置卡片"),
    category=WidgetCategory.COMM,
    icon="CLOUD",
    default_width=380, default_height=390,
    min_width=260, min_height=50,
    properties=[
        PropDef("title", N_("标题"), PropType.STRING, N_("MQTT 配置")),
        PropDef("displayMode", N_("显示模式"), PropType.ENUM, "完整",  # i18n: value
                options=["完整", "简洁"]),  # i18n: value
        PropDef("defaultHost", N_("默认服务器"), PropType.STRING, "127.0.0.1"),
        PropDef("defaultPort", N_("默认端口"), PropType.INT, 1883, min_val=1, max_val=65535),
        PropDef("defaultClientId", N_("默认客户端ID"), PropType.STRING, ""),
        PropDef("defaultUsername", N_("默认用户名"), PropType.STRING, ""),
        PropDef("defaultPassword", N_("默认密码"), PropType.STRING, ""),
        PropDef("defaultSubscribe", N_("默认订阅主题"), PropType.STRING, "device/data"),
        PropDef("defaultPublish", N_("默认发布主题"), PropType.STRING, "device/cmd"),
        PropDef("defaultQos", N_("默认 QoS"), PropType.ENUM, "0", options=["0", "1", "2"]),
        PropDef("defaultTls", N_("默认启用 TLS"), PropType.BOOL, False),
        PropDef("defaultParser", N_("默认解析模式"), PropType.ENUM, "项目设置",  # i18n: value
                options=["项目设置", "line", "hex", "modbus", "modbus_tcp", "modbus_ascii"]),  # i18n: value
        *MODBUS_LINK_PROPS,
        PARSER_CONFIG_PROP,
    ],
)

DATA_SEND_META = WidgetMeta(
    type_name="DataSendCard",
    display_name=N_("数据发送卡片"),
    category=WidgetCategory.COMM,
    icon="SEND",
    default_width=350, default_height=140,
    min_width=240, min_height=100,
    properties=[
        PropDef("title", N_("标题"), PropType.STRING, N_("数据发送")),
        PropDef("placeholder", N_("提示文字"), PropType.STRING, N_("输入要发送的数据...")),
    ],
)

DATA_RECV_META = WidgetMeta(
    type_name="DataRecvCard",
    display_name=N_("数据接收卡片"),
    category=WidgetCategory.COMM,
    icon="DOWNLOAD",
    default_width=350, default_height=250,
    min_width=240, min_height=120,
    properties=[
        PropDef("title", N_("标题"), PropType.STRING, N_("数据接收")),
        PropDef("maxLines", N_("最大行数"), PropType.INT, 1000, min_val=50, max_val=50000),
    ],
)

LOG_BOX_META = WidgetMeta(
    type_name="LogBox",
    display_name=N_("日志显示框"),
    category=WidgetCategory.COMM,
    icon="DOCUMENT",
    default_width=400, default_height=200,
    min_width=200, min_height=80,
    properties=[
        PropDef("maxLines", N_("最大行数"), PropType.INT, 500, min_val=50, max_val=50000),
    ],
)

SLAVE_TABLE_META = WidgetMeta(
    type_name="ModbusSlaveTable",
    display_name=N_("从站寄存器表"),
    category=WidgetCategory.COMM,
    icon="TABLE",
    default_width=260, default_height=300,
    min_width=160, min_height=120,
    properties=[
        PropDef("mbArea", N_("区"), PropType.ENUM, "保持寄存器",  # i18n: value
                options=["保持寄存器", "输入寄存器", "线圈", "离散输入"]),  # i18n: value
        PropDef("displayFormat", N_("显示格式"), PropType.ENUM, "无符号", options=["无符号", "有符号", "十六进制"],  # i18n: value
                description="线圈和离散输入总是显示 0/1"),  # i18n: ignore
    ],
)

ALL_COMPOSITE = [
    SERIAL_CONFIG_META, TCP_CONFIG_META, UDP_CONFIG_META, MQTT_CONFIG_META,
    DATA_SEND_META, DATA_RECV_META, LOG_BOX_META, SLAVE_TABLE_META,
]

# Cards shared with exported applications, configured through their PROPERTY_SETTERS.
_RUNTIME_CARDS = {"SerialConfigCard": SerialConfigCard, "TcpConfigCard": TcpConfigCard,
                  "UdpConfigCard": UdpConfigCard, "MqttConfigCard": MqttConfigCard}


def register_composite_widgets():
    for meta in ALL_COMPOSITE:
        registry.register(meta)


def create_composite_widget(type_name: str, props: dict, parent=None) -> QWidget:
    if type_name in _RUNTIME_CARDS:
        w = _RUNTIME_CARDS[type_name](parent)
        for prop, method, default in w.PROPERTY_SETTERS:
            getattr(w, method)(props.get(prop, default))
        return w
    if type_name == "DataSendCard":
        w = DataSendCard(parent)
        w.set_title(props.get("title", "数据发送"))  # i18n: value
        w.set_placeholder(props.get("placeholder", "输入要发送的数据..."))  # i18n: value
        return w
    if type_name == "DataRecvCard":
        w = DataRecvCard(parent)
        w.set_title(props.get("title", "数据接收"))  # i18n: value
        w.set_max_lines(props.get("maxLines", 1000))
        return w
    if type_name == "LogBox":
        w = LogDisplayBox(parent)
        w.set_max_lines(props.get("maxLines", 500))
        return w
    if type_name == "ModbusSlaveTable":
        w = ModbusSlaveTable(parent)
        w.set_area(props.get("mbArea", "保持寄存器"))  # i18n: value
        w.set_display_format(props.get("displayFormat", "无符号"))  # i18n: value
        return w
    return None


def apply_composite_property(widget, type_name: str, prop_name: str, value):
    if type_name in _RUNTIME_CARDS:
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
    elif type_name == "ModbusSlaveTable":
        if prop_name == "mbArea": widget.set_area(value)
        elif prop_name == "displayFormat": widget.set_display_format(value)
