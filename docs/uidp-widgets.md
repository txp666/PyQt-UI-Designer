# .uidp 控件参考

[uidp-format.md](uidp-format.md) 的附录：每个控件的类型名、属性名、默认值、取值范围和可选项，由`app/widgets` 里的控件定义生成，和程序完全一致。字符串按 JSON 里的写法列出。改了控件之后运行 `python tools/uidp_reference.py docs`，更新这份文件和 uidp-format.md 末尾的「控件一览」；没更新时 `tests/test_uidp_guide.py` 会失败。

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
- `mbFunc`（功能码，选项）默认 `"03 读保持寄存器"`，可选 `"01 读线圈"` `"02 读离散输入"` `"03 读保持寄存器"` `"04 读输入寄存器"` `"05 写单线圈"` `"06 写单寄存器"` `"16 写多个寄存器"`
- `mbAddress`（寄存器地址，整数）默认 `0`，范围 0–65535
- `mbDataType`（数据类型，选项）默认 `"uint16"`，可选 `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `mbRegOrder`（寄存器序，选项）默认 `"大端(AB CD)"`，可选 `"大端(AB CD)"` `"小端(CD AB)"`
- `mbValue`（值/数量，整数）默认 `1`，范围 -2147483648–2147483647
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
- `mbFunc`（功能码，选项）默认 `"06 写单寄存器"`，可选 `"03 读保持寄存器"` `"04 读输入寄存器"` `"05 写单线圈"` `"06 写单寄存器"` `"16 写多个寄存器"`
- `mbAddress`（寄存器地址，整数）默认 `0`，范围 0–65535
- `mbDataType`（数据类型，选项）默认 `"uint16"`，可选 `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `mbRegOrder`（寄存器序，选项）默认 `"大端(AB CD)"`，可选 `"大端(AB CD)"` `"小端(CD AB)"`

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
- `mbFunc`（功能码，选项）默认 `"06 写单寄存器"`，可选 `"03 读保持寄存器"` `"04 读输入寄存器"` `"05 写单线圈"` `"06 写单寄存器"` `"16 写多个寄存器"`
- `mbAddress`（寄存器地址，整数）默认 `0`，范围 0–65535
- `mbDataType`（数据类型，选项）默认 `"uint16"`，可选 `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `mbRegOrder`（寄存器序，选项）默认 `"大端(AB CD)"`，可选 `"大端(AB CD)"` `"小端(CD AB)"`
- `mbValue`（值/数量，整数）默认 `1`，范围 -2147483648–2147483647

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
- `mbFunc`（功能码，选项）默认 `"06 写单寄存器"`，可选 `"05 写单线圈"` `"06 写单寄存器"` `"16 写多个寄存器"`
- `mbAddress`（寄存器地址，整数）默认 `0`，范围 0–65535
- `mbDataType`（数据类型，选项）默认 `"uint16"`，可选 `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `mbRegOrder`（寄存器序，选项）默认 `"大端(AB CD)"`，可选 `"大端(AB CD)"` `"小端(CD AB)"`

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
- `mbFunc`（功能码，选项）默认 `"06 写单寄存器"`，可选 `"05 写单线圈"` `"06 写单寄存器"` `"16 写多个寄存器"`
- `mbAddress`（寄存器地址，整数）默认 `0`，范围 0–65535
- `mbDataType`（数据类型，选项）默认 `"uint16"`，可选 `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `mbRegOrder`（寄存器序，选项）默认 `"大端(AB CD)"`，可选 `"大端(AB CD)"` `"小端(CD AB)"`

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
- `curveMbArea`（寄存器区，选项）默认 `"响应内序号"`，可选 `"响应内序号"` `"保持寄存器"` `"输入寄存器"` `"线圈"` `"离散输入"`
- `curveRegIndex`（寄存器索引/地址，整数）默认 `0`，范围 0–65535
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
- `defaultParser`（默认解析模式，选项）默认 `"项目设置"`，可选 `"项目设置"` `"line"` `"hex"` `"modbus"` `"modbus_tcp"` `"modbus_ascii"`
- `parserConfig`（帧格式，对象）默认 `{}`，帧格式设置，键同工程的 serial.parserConfig；默认解析模式不是「项目设置」时生效，空对象表示沿用工程设置（模式相同时）或默认值
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
- `defaultParser`（默认解析模式，选项）默认 `"项目设置"`，可选 `"项目设置"` `"line"` `"hex"` `"modbus"` `"modbus_tcp"` `"modbus_ascii"`
- `parserConfig`（帧格式，对象）默认 `{}`，帧格式设置，键同工程的 serial.parserConfig；默认解析模式不是「项目设置」时生效，空对象表示沿用工程设置（模式相同时）或默认值

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
- `defaultParser`（默认解析模式，选项）默认 `"项目设置"`，可选 `"项目设置"` `"line"` `"hex"` `"modbus"` `"modbus_tcp"` `"modbus_ascii"`
- `parserConfig`（帧格式，对象）默认 `{}`，帧格式设置，键同工程的 serial.parserConfig；默认解析模式不是「项目设置」时生效，空对象表示沿用工程设置（模式相同时）或默认值

#### `ModbusConfigCard` Modbus 配置卡片

默认尺寸 380×180，最小 280×120

- `title`（标题，文本）默认 `"Modbus 配置"`
- `defaultSlave`（默认从站，整数）默认 `1`，范围 1–247
- `defaultFunc`（默认功能码，选项）默认 `"03 读保持寄存器"`，可选 `"01 读线圈"` `"02 读离散输入"` `"03 读保持寄存器"` `"04 读输入寄存器"` `"05 写单线圈"` `"06 写单寄存器"` `"16 写多个寄存器"`
- `defaultAddr`（默认地址，整数）默认 `0`，范围 0–65535
- `defaultValue`（默认值/数量，文本）默认 `"1"`
- `defaultPoll`（默认轮询(ms)，整数）默认 `0`，范围 0–60000
- `mbDataType`（写入数据类型，选项）默认 `"uint16"`，可选 `"uint16"` `"int16"` `"uint32"` `"int32"` `"float32"`
- `mbRegOrder`（写入寄存器序，选项）默认 `"大端(AB CD)"`，可选 `"大端(AB CD)"` `"小端(CD AB)"`
- `timeout`（响应超时(ms)，整数）默认 `1000`，范围 10–60000
- `pollMode`（轮询方式，选项）默认 `"自动"`，可选 `"自动"` `"轮询表"`
- `autoStart`（连接后自动轮询，true/false）默认 `true`
- `pollList`（轮询表，多行文本）默认 `""`

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
