# .uidp 工程格式：让 AI 直接写工程

PyQt UI Designer 的工程文件 `.uidp` 是一个 JSON 文件，和 C++ 版 FluentHMI Studio 通用。这份文档写给两种读者：

- **想让 AI 帮忙做上位机的人**：把这份文档的链接或内容，连同你的需求，一起交给 Claude、Codex 等 AI，让它直接写出 `.uidp`。写完按下面「写完怎么检查」验一遍，再用设计器打开微调。
- **AI 助手**：照下面的规则和例子写。不确定的属性，查最后的「控件参考」；没列出的字段不要编。只写需要改的属性，没写的会用默认值。

## 写完怎么检查

在本仓库根目录（装好 `requirements.txt` 里的依赖）运行：

```bash
# 输出 "ok: <应用名>"；否则逐条列出问题：设计器打开时会报的错（未知控件类型、ID 重复、坐标不是数字……），
# 以及打开时不报、但会让设置不生效的拼写错误（属性名、选项值、曲线字段）
python tools/check_uidp.py motor.uidp
```

然后用设计器打开工程看布局；切到「预览」，点链路卡片上的「连接」，接上设备看能不能收发。没问题就可以导出代码（Windows 上 `Ctrl+Shift+E`，Mac 上 `⌘⇧E`），或者在预览页点「一键打包」生成 exe / `.app`（需要本机有 C/C++ 编译器，见 README）。

同一个工程也能用 C++ 版 [FluentHMI Studio](https://github.com/txp666/FluentHMI-Studio) 打开、预览和导出。

## 一个完整的例子

需求：「通过 TCP 连 127.0.0.1:9100 的电机控制器，它每 100 毫秒发一行 `rpm=1500,power=2.40,load=50,running=1`；仪表盘显示转速，曲线画负载，LED 显示是否在运行，开关发 START/STOP，滑块（0–3000）发 `SPEED=数值`。」

```json
{
  "version": "1.0",
  "appName": "电机监控",
  "canvas": {"width": 900, "height": 620, "gridSize": 10},
  "serial": {"parser": "line", "parserConfig": {"separator": ","}},
  "widgets": [
    {"type": "Label", "id": "title", "geometry": {"x": 20, "y": 10, "w": 860, "h": 36},
     "properties": {"text": "电机监控", "fontSize": 22, "bold": true}},
    {"type": "TcpConfigCard", "id": "tcp", "geometry": {"x": 20, "y": 60, "w": 300, "h": 290},
     "properties": {"title": "TCP 连接", "defaultHost": "127.0.0.1", "defaultPort": 9100}},
    {"type": "GaugeMeter", "id": "rpm", "geometry": {"x": 340, "y": 60, "w": 260, "h": 260},
     "properties": {"title": "转速", "unit": "rpm", "maximum": 3000},
     "binding": {"parseMode": "键值匹配", "key": "rpm"}},
    {"type": "LEDIndicator", "id": "running_led", "geometry": {"x": 620, "y": 70, "w": 260, "h": 36},
     "properties": {"label": "运行中", "on": false},
     "binding": {"parseMode": "键值匹配", "key": "running"}},
    {"type": "ToggleSwitch", "id": "run", "geometry": {"x": 620, "y": 130, "w": 260, "h": 36},
     "properties": {"label": "电机启停", "onCommand": "START", "offCommand": "STOP"},
     "binding": {"parseMode": "键值匹配", "key": "running"}},
    {"type": "Label", "id": "speed_label", "geometry": {"x": 620, "y": 200, "w": 260, "h": 28},
     "properties": {"text": "设定转速（0–3000 rpm）"}},
    {"type": "Slider", "id": "speed", "geometry": {"x": 620, "y": 235, "w": 260, "h": 36},
     "properties": {"minimum": 0, "maximum": 3000, "value": 0, "sendOnChange": true,
                    "commandTemplate": "SPEED={value}"}},
    {"type": "RealtimeChart", "id": "load_chart", "geometry": {"x": 20, "y": 370, "w": 860, "h": 230},
     "properties": {"title": "负载", "curveCount": 1, "_curve_0_name": "负载", "_curve_0_key": "load"}}
  ]
}
```

要点：

- 设备通过一张链路卡片连接（这里是 `TcpConfigCard`），运行时由用户点「连接」，不会自动连。
- `serial.parser` 是 `line`：每收到一行，按逗号拆成 `rpm`、`power`、`load`、`running` 四个键，数字自动转成数值。
- 显示控件用 `binding` 取一个键；实时曲线的每条曲线写成 `_curve_{序号}_{字段}`。
- 开关也绑定了 `running`：设备的状态会拨动开关，但不会因此再发一次命令；开关被点击时才发 `START` / `STOP`。
- 文本命令默认在末尾加 `\r\n`。

## 文件结构

```json
{
  "version": "1.0",
  "appName": "上位机",
  "canvas": {"width": 1200, "height": 800, "gridSize": 10},
  "serial": {"parser": "line", "parserConfig": {"separator": ","}},
  "widgets": []
}
```

| 字段 | 说明 |
| --- | --- |
| `version` | 只能是 `"1.0"` |
| `appName` | 应用名，导出的应用以它命名 |
| `canvas` | 画布宽、高（1–9999 的整数）和网格大小 |
| `serial` | 工程默认的帧格式：`parser` 和 `parserConfig`，见下面「解析收到的数据」。名字叫 serial，但对所有链路都有效 |
| `widgets` | 控件数组 |

每个控件：

```json
{
  "type": "GaugeMeter",
  "id": "rpm",
  "geometry": {"x": 340, "y": 60, "w": 260, "h": 260},
  "properties": {"title": "转速", "maximum": 3000},
  "binding": {"parseMode": "键值匹配", "key": "rpm"}
}
```

| 字段 | 说明 |
| --- | --- |
| `type` | 控件类型，大小写要和「控件参考」里完全一致 |
| `id` | 控件 ID，整个工程里不能重复。建议每个控件都写 |
| `geometry` | 位置和大小，单位是画布像素；`w`、`h` 必须大于 0，并且不要小于参考里的最小尺寸 |
| `properties` | 属性。只写要改的，没写的用默认值。选项类属性必须是参考里列出的原文（包括中文） |
| `binding` | 数据绑定，只有能显示数据的控件需要，见下面 |
| `children` | 容器的子控件数组，子控件的坐标相对于容器左上角 |
| `tabIndex` | 选项卡（`TabWidget`）的子控件放在第几页，从 0 开始 |

## 连接设备：链路卡片

每个设备放一张链路卡片，用户在运行时点卡片上的「连接」：

| 卡片 | 常用属性 |
| --- | --- |
| `SerialConfigCard` 串口 | `defaultBaud`（如 `"115200"`）、`defaultDatabits`、`defaultParity`、`defaultStopbits`；串口号运行时选 |
| `TcpConfigCard` TCP | `defaultMode`（`"客户端"` / `"服务端"`）、`defaultHost`、`defaultPort` |
| `MqttConfigCard` MQTT | `defaultHost`、`defaultPort`、`defaultSubscribe`（可用 `+` `#` 通配）、`defaultPublish`、`defaultUsername`、`defaultPassword`、`defaultQos`（`"0"` `"1"` `"2"`） |

- 每张卡片都有 `defaultParser`：`"项目设置"`（默认，用工程的 `serial.parser`）、`"line"`、`"hex"`、`"modbus"`、`"modbus_tcp"`。不同设备帧格式不同时，在卡片上分别设置。
- MQTT 每条消息算一帧，按这条链路的解析模式解析；用 `line` 解析时消息末尾不需要换行。消息只有一个数值时（比如主题 `sensor/temp` 收到 `25.3`），还可以直接用主题名 `sensor/temp` 当键绑定。
- MQTT 发命令时，编码后的整条命令就是消息内容，**包括 `commandNewline` 加的换行**。设备要的是不带换行的 `RESET` 时，把发命令控件的 `commandNewline` 设成 `"无"`。
- 订阅主题如果也包含了发布主题（比如订阅 `workshop/#`、发布到 `workshop/cmd`），上位机会收到自己发出的命令；只要没有控件绑定同名的键，就没有影响。
- 发送命令时，命令会发到**所有已连接的链路**（MQTT 发到 `defaultPublish` 主题）。
- `ModbusConfigCard` 用来手动发送或轮询 Modbus 请求，它本身不是链路，需要和串口或 TCP 卡片一起用。

## 解析收到的数据

`serial.parser`（或卡片的 `defaultParser`）决定一帧怎么变成键值：

| parser | 帧 | 解析结果 |
| --- | --- | --- |
| `line` | 一行文本，以 `\n` 结尾（`\r\n` 也行）。`parserConfig.separator` 是分隔符，默认 `","` | `temp=25.3,hum=60` → 键 `temp`、`hum`；一行 JSON 对象 → 原样的对象；`25.3,60` → `ch0`、`ch1`。数字自动转成数值 |
| `hex` | 二进制帧。`parserConfig`：`header`（如 `"AA55"`）、`footer`（如 `"55AA"`）、`fields`：`[["temp", 0, 2, "int16"], ...]`，每项是 `[名字, 偏移, 长度, 类型]` | 按字段取值得到键 |
| `modbus` / `modbus_tcp` | Modbus RTU / TCP 响应 | `slave`、`fc`，以及 `reg0`、`reg1`……（读寄存器）或 `coil0`……（读线圈） |

协议的完整规则（各种发送格式的例子、HEX 类型的字节长度、Modbus 输出格式）见 [protocol.md](protocol.md)。

## 绑定数据

能接收数据的控件和它被写入的属性：

| 控件 | 写入 |
| --- | --- |
| `Label` | `text` |
| `NumericDisplay`、`GaugeMeter`、`ProgressBar`、`ProgressRingDisplay` | `value` |
| `LEDIndicator` | `on`：值等于属性 `onValue`（默认 `"1"`）时亮，等于 `offValue`（默认 `"0"`）时灭 |
| `ToggleSwitch` | `checked`：设备状态拨动开关，不会因此发命令 |
| `Slider`、`SpinBox` | `value`：同上，不会因此发命令 |

`binding` 里只写用到的字段：

| parseMode | 需要的字段 |
| --- | --- |
| `"键值匹配"` | `key`：键名，如 `"rpm"` |
| `"JSON路径"` | `jsonPath`：用点分隔，数组用下标，如 `"data.sensors.0.temp"`（负数从末尾数） |
| `"HEX字节提取"` | 直接从原始字节取：`byteOffset`、`dataType`（`"uint8"` … `"float32"`）、`byteOrder`（`"大端(BE)"` / `"小端(LE)"`），可选 `frameHeader` / `frameTail`（HEX 文本，如 `"AA55"`） |
| `"Modbus"` | `mbRegIndex`（第几个寄存器，从 0 开始）、`mbDataType`（`"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`）、`mbRegOrder`（`"大端(AB CD)"` / `"小端(CD AB)"`），可选过滤 `mbSlaveFilter`、`mbFcFilter`（-1 表示不过滤） |

所有模式都可以加 `expression` 做换算，变量是 `value`，如 `"value * 0.1"`。

## 发送命令

按钮、开关、滑块、数值框、输入框、下拉框都能发命令。`commandMode` 决定格式：

- **`"文本"`（默认）**：`commandTemplate` 里的 `{value}` 换成要发的值，末尾加 `commandNewline`。`commandNewline` 可选 `"无"`、`"\\r\\n"`（默认）、`"\\n"`、`"\\r"`。注意在 JSON 里要写成两个反斜杠，因为这个值本身就是反斜杠加字母的文字。
- **`"HEX"`**：`dataType` 为 `"HEX字符串"` 时，值本身就是 HEX 文本（如 `"01 03 00 00"`）；为数值类型时，按 `dataType` 和 `byteOrder` 打包后放进模板。可加 `frameHeader` / `frameTail`。
- **`"Modbus"`**：用 `mbSlave`、`mbFunc`（如 `"06 写单寄存器"`）、`mbAddress` 组请求；连接的链路解析模式是 `modbus_tcp` 时自动用 MBAP 帧，否则用 RTU 帧加 CRC。

每种控件发什么值：

| 控件 | 值 | 什么时候发 |
| --- | --- | --- |
| `PushButton` | `command` | 点击 |
| `ToggleSwitch` | 打开时 `onCommand`，关闭时 `offCommand` | 用户拨动 |
| `Slider`、`SpinBox` | 当前数值 | `sendOnChange` 为 `true` 时每次数值变化都发（拖动滑块会连续发很多条）；文本和 HEX 模式不打开它就不发 |
| `LineEdit` | 输入的文字 | `sendOnEnter` 为 `true` 时按回车 |
| `ComboBox` | `commands` 里和选项同一行的命令（多行文本，一行对应 `items` 的一项）；那一行是空的就发选项文字本身 | `sendOnSelect` 为 `true` 时选中 |

需要设备的反馈控制开关或滑块的位置时，给它们加 `binding`（见上表）。

## 实时曲线

`RealtimeChart` 最多 8 条曲线（`curveCount`），每条曲线的配置写成 `_curve_{序号}_{字段}`，序号从 0 开始：

| 字段 | 说明 |
| --- | --- |
| `_curve_0_name` | 图例名 |
| `_curve_0_parseMode` | 同 binding 的 `parseMode`，默认 `"键值匹配"` |
| `_curve_0_key`、`_curve_0_jsonPath` | 键值匹配 / JSON路径 |
| `_curve_0_byteOffset`、`_curve_0_dataType`、`_curve_0_byteOrder`、`_curve_0_frameHeader`、`_curve_0_frameTail` | HEX字节提取 |
| `_curve_0_regIndex`、`_curve_0_mbDataType`、`_curve_0_mbRegOrder`、`_curve_0_mbFcFilter`、`_curve_0_mbSlaveFilter` | Modbus |

控件参考里 `curveName`、`curveKey` 这些 `curve` 开头的属性，是设计器属性面板编辑「当前曲线」用的，写文件时不需要。

曲线颜色按顺序固定（浅色主题下依次是蓝、红、绿、橙、紫、青、棕、灰，深色主题用对应的浅一些的颜色），文件里不能改。所有曲线共用一条自动缩放的纵轴，数量级差很多的量最好分到两个曲线控件里。

横轴是这条曲线收到的点数，不是时间。几条曲线来自发送频率不同的设备时，会一条快一条慢；能统一频率最好。

## 容器

`HBoxLayout`、`VBoxLayout`、`FlexLayout`、`GroupBox`、`CardContainer`、`TabWidget` 可以放子控件，写在 `children` 里，坐标相对容器。`TabWidget` 的页名在 `tabNames`（多行文本，一行一页），子控件用 `tabIndex` 指定页。每页的布局写成 `_tabLayout_{页号}`，可选 `"自由"` `"垂直"` `"水平"` `"弹性(Flex)"`；控件参考里的 `tabLayout` 是属性面板编辑当前页用的，写文件时不需要。

## 常见错误

- 控件类型拼错或大小写不对 → 设计器和 `check_uidp.py` 都会报「未知控件类型」。
- 两个控件同一个 `id` → 「控件 ID 无效或重复」。
- 选项类属性写了参考里没有的值（比如把 `"键值匹配"` 写成 `"key"`、`"大端(BE)"` 写成 `"BE"`）→ 设计器打开时不报错，但设置不生效，`check_uidp.py` 会指出来。照抄参考里的原文。
- `defaultPort`、`maximum` 这类数值写成了字符串；`defaultBaud`、`defaultQos` 反过来是字符串选项。
- 文本命令忘了设备需要的换行符；设备只认 `\n` 时把 `commandNewline` 设成 `"\\n"`。反过来，MQTT 设备通常不要换行，设成 `"无"`。
- 以为工程会自动连接：不会，用户要点「连接」。

## 控件参考

下面由 `app/widgets` 里的控件定义生成，和程序完全一致：类型名、属性名、默认值、取值范围和可选项。字符串按 JSON 里的写法列出。改了控件之后运行 `python tools/uidp_reference.py docs/uidp-format.md` 更新这一节；没更新时 `tests/test_uidp_guide.py` 会失败。

<!-- 以下由 tools/uidp_reference.py 从控件定义生成，不要手改 -->

### 基础控件

#### `PushButton` 按钮

默认尺寸 120×36，最小 30×20

- `text`（文本，文本）默认 `"按钮"`
- `enabled`（启用，true/false）默认 `true`
- `commandMode`（发送模式，选项）默认 `"文本"`，可选 `"文本"` `"HEX"` `"Modbus"`
- `command`（发送内容，命令）默认 `""`
- `commandTemplate`（发送模板，文本）默认 `"{value}"`
- `frameHeader`（帧头(HEX)，文本）默认 `""`
- `frameTail`（帧尾(HEX)，文本）默认 `""`
- `dataType`（数据类型，选项）默认 `"HEX字符串"`，可选 `"HEX字符串"` `"uint8"` `"int8"` `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `byteOrder`（字节序，选项）默认 `"大端(BE)"`，可选 `"大端(BE)"` `"小端(LE)"`
- `commandNewline`（换行符，选项）默认 `"\\r\\n"`，可选 `"无"` `"\\r\\n"` `"\\n"` `"\\r"`
- `mbSlave`（从站地址，整数）默认 `1`，范围 1–247
- `mbFunc`（功能码，选项）默认 `"03 读保持寄存器"`，可选 `"01 读线圈"` `"02 读离散输入"` `"03 读保持寄存器"` `"04 读输入寄存器"` `"05 写单线圈"` `"06 写单寄存器"`
- `mbAddress`（寄存器地址，整数）默认 `0`，范围 0–65535
- `mbValue`（值/数量，整数）默认 `1`，范围 0–65535
- `notify`（按下通知，true/false）默认 `false`
- `notifyTitle`（通知标题，文本）默认 `"提示"`
- `notifyContent`（通知内容，文本）默认 `"按钮已按下"`
- `notifyType`（通知类型，选项）默认 `"成功"`，可选 `"成功"` `"信息"` `"警告"` `"错误"`
- `notifyDuration`（通知时长(ms)，整数）默认 `3000`，范围 500–30000

#### `Label` 标签

默认尺寸 120×30，最小 30×20；绑定数据时写入 `text`

- `text`（文本，文本）默认 `"标签"`
- `fontSize`（字号，整数）默认 `14`，范围 8–72
- `bold`（加粗，true/false）默认 `false`
- `alignment`（对齐，选项）默认 `"Left"`，可选 `"Left"` `"Center"` `"Right"`
- `displayFormat`（显示格式，选项）默认 `"自动"`，可选 `"自动"` `"十进制"` `"十六进制(HEX)"` `"二进制(BIN)"`
- `decimals`（小数位数，选项）默认 `"自动"`，可选 `"自动"` `"0"` `"1"` `"2"` `"3"` `"4"`

#### `LineEdit` 输入框

默认尺寸 200×36，最小 30×20

- `placeholderText`（占位文本，文本）默认 `"请输入..."`
- `text`（默认值，文本）默认 `""`
- `readOnly`（只读，true/false）默认 `false`
- `sendOnEnter`（回车发送，true/false）默认 `false`
- `commandMode`（发送模式，选项）默认 `"文本"`，可选 `"文本"` `"HEX"` `"Modbus"`
- `commandTemplate`（发送模板，文本）默认 `"{value}"`
- `frameHeader`（帧头(HEX)，文本）默认 `""`
- `frameTail`（帧尾(HEX)，文本）默认 `""`
- `dataType`（数据类型，选项）默认 `"HEX字符串"`，可选 `"HEX字符串"` `"uint8"` `"int8"` `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `byteOrder`（字节序，选项）默认 `"大端(BE)"`，可选 `"大端(BE)"` `"小端(LE)"`
- `commandNewline`（换行符，选项）默认 `"\\r\\n"`，可选 `"无"` `"\\r\\n"` `"\\n"` `"\\r"`
- `mbSlave`（从站地址，整数）默认 `1`，范围 1–247
- `mbFunc`（功能码，选项）默认 `"06 写单寄存器"`，可选 `"03 读保持寄存器"` `"04 读输入寄存器"` `"05 写单线圈"` `"06 写单寄存器"`
- `mbAddress`（寄存器地址，整数）默认 `0`，范围 0–65535

#### `ComboBox` 下拉框

默认尺寸 160×36，最小 30×20

- `items`（选项，多行文本）默认 `"选项1\n选项2\n选项3"`
- `currentIndex`（默认选项，整数）默认 `0`，范围 0–99
- `sendOnSelect`（选中发送，true/false）默认 `false`
- `commands`（发送命令表，多行文本）默认 `""`
- `commandMode`（发送模式，选项）默认 `"文本"`，可选 `"文本"` `"HEX"` `"Modbus"`
- `commandTemplate`（发送模板，文本）默认 `"{value}"`
- `frameHeader`（帧头(HEX)，文本）默认 `""`
- `frameTail`（帧尾(HEX)，文本）默认 `""`
- `dataType`（数据类型，选项）默认 `"HEX字符串"`，可选 `"HEX字符串"` `"uint8"` `"int8"` `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `byteOrder`（字节序，选项）默认 `"大端(BE)"`，可选 `"大端(BE)"` `"小端(LE)"`
- `commandNewline`（换行符，选项）默认 `"\\r\\n"`，可选 `"无"` `"\\r\\n"` `"\\n"` `"\\r"`
- `mbSlave`（从站地址，整数）默认 `1`，范围 1–247
- `mbFunc`（功能码，选项）默认 `"06 写单寄存器"`，可选 `"03 读保持寄存器"` `"04 读输入寄存器"` `"05 写单线圈"` `"06 写单寄存器"`
- `mbAddress`（寄存器地址，整数）默认 `0`，范围 0–65535
- `mbValue`（值/数量，整数）默认 `1`，范围 0–65535

#### `ToggleSwitch` 开关

默认尺寸 140×30，最小 30×20；绑定数据时写入 `checked`

- `label`（标签，文本）默认 `"开关"`
- `checked`（默认开启，true/false）默认 `false`
- `commandMode`（发送模式，选项）默认 `"文本"`，可选 `"文本"` `"HEX"` `"Modbus"`
- `onCommand`（开启命令，命令）默认 `""`
- `offCommand`（关闭命令，命令）默认 `""`
- `commandTemplate`（发送模板，文本）默认 `"{value}"`
- `frameHeader`（帧头(HEX)，文本）默认 `""`
- `frameTail`（帧尾(HEX)，文本）默认 `""`
- `dataType`（数据类型，选项）默认 `"HEX字符串"`，可选 `"HEX字符串"` `"uint8"` `"int8"` `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `byteOrder`（字节序，选项）默认 `"大端(BE)"`，可选 `"大端(BE)"` `"小端(LE)"`
- `commandNewline`（换行符，选项）默认 `"\\r\\n"`，可选 `"无"` `"\\r\\n"` `"\\n"` `"\\r"`
- `mbSlave`（从站地址，整数）默认 `1`，范围 1–247
- `mbAddress`（线圈地址，整数）默认 `0`，范围 0–65535
- `notify`（切换通知，true/false）默认 `false`
- `notifyTitle`（通知标题，文本）默认 `"提示"`
- `notifyContent`（通知内容，文本）默认 `"开关已切换"`
- `notifyType`（通知类型，选项）默认 `"信息"`，可选 `"成功"` `"信息"` `"警告"` `"错误"`
- `notifyDuration`（通知时长(ms)，整数）默认 `3000`，范围 500–30000

#### `Slider` 滑块

默认尺寸 200×30，最小 30×20；绑定数据时写入 `value`

- `minimum`（最小值，整数）默认 `0`，范围 -99999–99999
- `maximum`（最大值，整数）默认 `100`，范围 -99999–99999
- `value`（默认值，整数）默认 `50`，范围 -99999–99999
- `sendOnChange`（变化发送，true/false）默认 `false`
- `commandMode`（发送模式，选项）默认 `"文本"`，可选 `"文本"` `"HEX"` `"Modbus"`
- `commandTemplate`（发送模板，文本）默认 `"{value}"`
- `frameHeader`（帧头(HEX)，文本）默认 `""`
- `frameTail`（帧尾(HEX)，文本）默认 `""`
- `commandNewline`（换行符，选项）默认 `"\\r\\n"`，可选 `"无"` `"\\r\\n"` `"\\n"` `"\\r"`
- `dataType`（数据类型，选项）默认 `"uint16"`，可选 `"uint8"` `"int8"` `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `byteOrder`（字节序，选项）默认 `"大端(BE)"`，可选 `"大端(BE)"` `"小端(LE)"`
- `mbSlave`（从站地址，整数）默认 `1`，范围 1–247
- `mbFunc`（功能码，选项）默认 `"06 写单寄存器"`，可选 `"05 写单线圈"` `"06 写单寄存器"`
- `mbAddress`（寄存器地址，整数）默认 `0`，范围 0–65535

#### `SpinBox` 数值框

默认尺寸 140×36，最小 30×20；绑定数据时写入 `value`

- `minimum`（最小值，整数）默认 `0`，范围 -99999–99999
- `maximum`（最大值，整数）默认 `100`，范围 -99999–99999
- `value`（默认值，整数）默认 `0`，范围 -99999–99999
- `suffix`（后缀，文本）默认 `""`
- `sendOnChange`（变化发送，true/false）默认 `false`
- `commandMode`（发送模式，选项）默认 `"文本"`，可选 `"文本"` `"HEX"` `"Modbus"`
- `commandTemplate`（发送模板，文本）默认 `"{value}"`
- `frameHeader`（帧头(HEX)，文本）默认 `""`
- `frameTail`（帧尾(HEX)，文本）默认 `""`
- `commandNewline`（换行符，选项）默认 `"\\r\\n"`，可选 `"无"` `"\\r\\n"` `"\\n"` `"\\r"`
- `dataType`（数据类型，选项）默认 `"uint16"`，可选 `"uint8"` `"int8"` `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `byteOrder`（字节序，选项）默认 `"大端(BE)"`，可选 `"大端(BE)"` `"小端(LE)"`
- `mbSlave`（从站地址，整数）默认 `1`，范围 1–247
- `mbFunc`（功能码，选项）默认 `"06 写单寄存器"`，可选 `"05 写单线圈"` `"06 写单寄存器"`
- `mbAddress`（寄存器地址，整数）默认 `0`，范围 0–65535

### 布局容器

#### `HBoxLayout` 水平布局

默认尺寸 300×80，最小 60×40；**容器**，子控件放在 `children` 里

- `title`（标题，文本）默认 `"水平布局"`
- `spacing`（间距，整数）默认 `8`，范围 0–100

#### `VBoxLayout` 垂直布局

默认尺寸 200×200，最小 60×40；**容器**，子控件放在 `children` 里

- `title`（标题，文本）默认 `"垂直布局"`
- `spacing`（间距，整数）默认 `8`，范围 0–100

#### `FlexLayout` 弹性布局

默认尺寸 400×200，最小 100×60；**容器**，子控件放在 `children` 里

- `title`（标题，文本）默认 `"弹性布局"`
- `direction`（方向，选项）默认 `"row"`，可选 `"row"` `"column"`
- `spacing`（间距，整数）默认 `8`，范围 0–100

#### `GroupBox` 分组框

默认尺寸 280×180，最小 80×60；**容器**，子控件放在 `children` 里

- `title`（标题，文本）默认 `"分组"`

#### `TabWidget` 选项卡

默认尺寸 350×250，最小 150×80；**容器**，子控件放在 `children` 里

- `tabNames`（标签名称，多行文本）默认 `"标签1\n标签2\n标签3"`
- `currentTab`（当前标签页，整数）默认 `0`，范围 0–9999
- `tabLayout`（当前页布局，选项）默认 `"自由"`，可选 `"自由"` `"垂直"` `"水平"` `"弹性(Flex)"`

#### `Separator` 分割线

默认尺寸 200×2，最小 20×2

- `orientation`（方向，选项）默认 `"horizontal"`，可选 `"horizontal"` `"vertical"`

#### `CardContainer` 卡片容器

默认尺寸 300×200，最小 80×60；**容器**，子控件放在 `children` 里

- `title`（标题，文本）默认 `""`
- `layout`（布局，选项）默认 `"自由"`，可选 `"自由"` `"垂直"` `"水平"`
- `spacing`（间距，整数）默认 `8`，范围 0–100

### 显示控件

#### `LEDIndicator` LED指示灯

默认尺寸 140×30，最小 30×20；绑定数据时写入 `on`

- `label`（标签，文本）默认 `"状态"`
- `color`（颜色，选项）默认 `"green"`，可选 `"green"` `"red"` `"yellow"` `"blue"` `"gray"`
- `on`（点亮，true/false）默认 `true`
- `onValue`（亮值，文本）默认 `"1"`
- `offValue`（灭值，文本）默认 `"0"`

#### `NumericDisplay` 数值显示

默认尺寸 160×90，最小 30×20；绑定数据时写入 `value`

- `title`（标题，文本）默认 `"温度"`
- `value`（数值，文本）默认 `"0.00"`
- `unit`（单位，文本）默认 `"°C"`
- `fontSize`（字号，整数）默认 `28`，范围 12–72
- `displayFormat`（显示格式，选项）默认 `"自动"`，可选 `"自动"` `"十进制"` `"十六进制(HEX)"` `"二进制(BIN)"`
- `decimals`（小数位数，选项）默认 `"自动"`，可选 `"自动"` `"0"` `"1"` `"2"` `"3"` `"4"`

#### `ProgressBar` 进度条

默认尺寸 250×20，最小 30×10；绑定数据时写入 `value`

- `value`（当前值，整数）默认 `50`，范围 0–100
- `maximum`（最大值，整数）默认 `100`，范围 1–99999

#### `ImageDisplay` 图片显示

默认尺寸 200×150，最小 30×20

- `imagePath`（图片路径，文本）默认 `""`

### 图表控件

#### `RealtimeChart` 实时曲线

默认尺寸 400×280，最小 200×150

- `title`（标题，文本）默认 `"实时曲线"`
- `displayPoints`（显示点数，整数）默认 `200`，范围 10–10000
- `curveCount`（曲线数量，整数）默认 `1`，范围 1–8
- `currentCurve`（当前编辑曲线，整数）默认 `0`，范围 0–7
- `curveName`（曲线名称，文本）默认 `"曲线1"`
- `curveParseMode`（解析模式，选项）默认 `"键值匹配"`，可选 `"键值匹配"` `"JSON路径"` `"HEX字节提取"` `"Modbus"`
- `curveKey`（匹配键，文本）默认 `""`
- `curveJsonPath`（JSON路径，文本）默认 `""`
- `curveByteOffset`（字节偏移，整数）默认 `0`，范围 0–9999
- `curveDataType`（数据类型(HEX)，选项）默认 `"float32"`，可选 `"uint8"` `"int8"` `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `curveByteOrder`（字节序(HEX)，选项）默认 `"大端(BE)"`，可选 `"大端(BE)"` `"小端(LE)"`
- `curveFrameHeader`（帧头(HEX)，文本）默认 `""`
- `curveFrameTail`（帧尾(HEX)，文本）默认 `""`
- `curveRegIndex`（寄存器索引，整数）默认 `0`，范围 0–65535
- `curveMbDataType`（数据类型(MB)，选项）默认 `"uint16"`，可选 `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `curveMbRegOrder`（寄存器序(MB)，选项）默认 `"大端(AB CD)"`，可选 `"大端(AB CD)"` `"小端(CD AB)"`
- `curveMbFcFilter`（功能码过滤，整数）默认 `-1`，范围 -1–255
- `curveMbSlaveFilter`（从站过滤，整数）默认 `-1`，范围 -1–255

#### `GaugeMeter` 仪表盘

默认尺寸 180×180，最小 80×80；绑定数据时写入 `value`

- `title`（标题，文本）默认 `"仪表"`
- `unit`（单位，文本）默认 `""`
- `value`（当前值，小数）默认 `0.0`，范围 -99999–99999
- `minimum`（最小值，小数）默认 `0.0`，范围 -99999–99999
- `maximum`（最大值，小数）默认 `100.0`，范围 -99999–99999

#### `DataTable` 数据表格

默认尺寸 350×250，最小 200×100

- `columns`（列名，多行文本）默认 `"字段\n值"`
- `recordMode`（记录方式，选项）默认 `"最新值"`，可选 `"最新值"` `"逐行记录"`
- `maxRows`（最大行数，整数）默认 `500`，范围 10–50000

### 复合卡片

#### `SerialConfigCard` 串口配置卡片

默认尺寸 360×340，最小 200×50

- `title`（标题，文本）默认 `"串口配置"`
- `displayMode`（显示模式，选项）默认 `"完整"`，可选 `"完整"` `"简洁"` `"单行"`
- `defaultParser`（默认解析模式，选项）默认 `"项目设置"`，可选 `"项目设置"` `"line"` `"hex"` `"modbus"` `"modbus_tcp"`
- `defaultBaud`（默认波特率，选项）默认 `"115200"`，可选 `"9600"` `"19200"` `"38400"` `"57600"` `"115200"` `"230400"` `"460800"` `"921600"`
- `defaultDatabits`（默认数据位，选项）默认 `"8"`，可选 `"5"` `"6"` `"7"` `"8"`
- `defaultParity`（默认校验位，选项）默认 `"None"`，可选 `"None"` `"Even"` `"Odd"` `"Mark"` `"Space"`
- `defaultStopbits`（默认停止位，选项）默认 `"1"`，可选 `"1"` `"1.5"` `"2"`
- `defaultFlow`（默认流控制，选项）默认 `"无"`，可选 `"无"` `"RTS/CTS"` `"XON/XOFF"` `"DTR/DSR"`

#### `TcpConfigCard` TCP 配置卡片

默认尺寸 360×290，最小 240×50

- `title`（标题，文本）默认 `"TCP 配置"`
- `displayMode`（显示模式，选项）默认 `"完整"`，可选 `"完整"` `"简洁"`
- `defaultMode`（默认模式，选项）默认 `"客户端"`，可选 `"客户端"` `"服务端"`
- `defaultHost`（默认地址，文本）默认 `"127.0.0.1"`
- `defaultPort`（默认端口，整数）默认 `8080`，范围 1–65535
- `defaultParser`（默认解析模式，选项）默认 `"项目设置"`，可选 `"项目设置"` `"line"` `"hex"` `"modbus"` `"modbus_tcp"`

#### `MqttConfigCard` MQTT 配置卡片

默认尺寸 380×430，最小 260×50

- `title`（标题，文本）默认 `"MQTT 配置"`
- `displayMode`（显示模式，选项）默认 `"完整"`，可选 `"完整"` `"简洁"`
- `defaultHost`（默认服务器，文本）默认 `"127.0.0.1"`
- `defaultPort`（默认端口，整数）默认 `1883`，范围 1–65535
- `defaultClientId`（默认客户端ID，文本）默认 `""`
- `defaultUsername`（默认用户名，文本）默认 `""`
- `defaultPassword`（默认密码，文本）默认 `""`
- `defaultSubscribe`（默认订阅主题，文本）默认 `"device/data"`
- `defaultPublish`（默认发布主题，文本）默认 `"device/cmd"`
- `defaultQos`（默认 QoS，选项）默认 `"0"`，可选 `"0"` `"1"` `"2"`
- `defaultTls`（默认启用 TLS，true/false）默认 `false`
- `defaultParser`（默认解析模式，选项）默认 `"项目设置"`，可选 `"项目设置"` `"line"` `"hex"` `"modbus"` `"modbus_tcp"`

#### `ModbusConfigCard` Modbus 配置卡片

默认尺寸 380×180，最小 280×120

- `title`（标题，文本）默认 `"Modbus 配置"`
- `defaultSlave`（默认从站，整数）默认 `1`，范围 1–247
- `defaultFunc`（默认功能码，选项）默认 `"03 读保持寄存器"`，可选 `"01 读线圈"` `"02 读离散输入"` `"03 读保持寄存器"` `"04 读输入寄存器"` `"05 写单线圈"` `"06 写单寄存器"`
- `defaultAddr`（默认地址，整数）默认 `0`，范围 0–65535
- `defaultValue`（默认值/数量，整数）默认 `1`，范围 0–65535
- `defaultPoll`（默认轮询(ms)，整数）默认 `0`，范围 0–60000

#### `DataSendCard` 数据发送卡片

默认尺寸 350×140，最小 240×100

- `title`（标题，文本）默认 `"数据发送"`
- `placeholder`（提示文字，文本）默认 `"输入要发送的数据..."`

#### `DataRecvCard` 数据接收卡片

默认尺寸 350×250，最小 240×120

- `title`（标题，文本）默认 `"数据接收"`
- `maxLines`（最大行数，整数）默认 `1000`，范围 50–50000

#### `LogBox` 日志显示框

默认尺寸 400×200，最小 200×80

- `maxLines`（最大行数，整数）默认 `500`，范围 50–50000

#### `ProgressRingDisplay` 进度环

默认尺寸 120×130，最小 80×80；绑定数据时写入 `value`

- `label`（标签，文本）默认 `"进度"`
- `value`（当前值，整数）默认 `0`，范围 0–100
- `maximum`（最大值，整数）默认 `100`，范围 1–99999
