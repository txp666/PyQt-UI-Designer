# Python 版 .uidp 导航（给 AI）

给 AI 这份[三端公共格式与可复制模板](https://raw.githubusercontent.com/txp666/FluentHMI-Studio/main/docs/uidp-format.md)。其他规则按任务查阅。

- [取值、实时曲线、转换表达式](https://raw.githubusercontent.com/txp666/FluentHMI-Studio/main/docs/uidp/data.md)
- [链路、帧配置、Modbus](https://raw.githubusercontent.com/txp666/FluentHMI-Studio/main/docs/uidp/connections.md)
- [命令下发](https://raw.githubusercontent.com/txp666/FluentHMI-Studio/main/docs/uidp/commands.md)
- [汽车电子、电子 DIY 与嵌入式](https://raw.githubusercontent.com/txp666/FluentHMI-Studio/main/docs/uidp/electronics.md)
- CAN 工程使用 FluentHMI Studio。[CAN 专题](https://raw.githubusercontent.com/txp666/FluentHMI-Studio/main/docs/uidp/can.md)

本页末尾列出 Python 支持的控件，属性名、默认值和选项由本版注册表生成。[控件参考](uidp-widgets.md) · [Python 通信协议](protocol.md)

## 本地教程模板

下面的示例可直接打开，再按设备修改连接参数、取值或命令。

- [温湿度采集](../examples/tutorials/01-温湿度采集.uidp)
- [温控仪监控](../examples/tutorials/02-温控仪监控.uidp)
- [ADC 采集板](../examples/tutorials/07-ADC采集板.uidp)
- [温控仪模拟器](../examples/tutorials/11-温控仪模拟器.uidp)
- [双泵供水与压力、流量反馈](../examples/industrial/恒压供水泵站.uidp) · [工业控件回放](../examples/industrial/工业控件回放.uidp)
- [电子控件回放](../examples/industrial/电子控件回放.uidp) · [电子反馈数据](../examples/industrial/电子反馈.jsonl)

## Python 检查与导出

安装 `requirements.txt` 中的依赖后，在源码根目录检查工程。

```sh
python tools/check_uidp.py 工程.uidp
```

检查通过后用设计器打开、预览，再使用「导出代码」生成独立 PyQt5 项目，或使用「一键打包」。源码应用按生成的 requirements.txt 安装依赖后运行 main.py。

## 控件一览

类型名、名称和默认尺寸（宽×高）。完整属性见 [uidp-widgets.md](uidp-widgets.md)。

<!-- 以下由 tools/uidp_reference.py 从控件定义生成，不要手改 -->

- 基础控件：`PushButton` 按钮（120×36）、`Label` 标签（120×30）、`LineEdit` 输入框（200×36）、`ComboBox` 下拉框（160×36）、`ToggleSwitch` 开关（140×30）、`Slider` 滑块（200×30）、`SpinBox` 数值框（140×36）
- 布局容器：`HBoxLayout` 水平布局（300×80）、`VBoxLayout` 垂直布局（200×200）、`FlexLayout` 弹性布局（400×200）、`GroupBox` 分组框（280×180）、`TabWidget` 选项卡（350×250）、`Separator` 分割线（200×2）、`CardContainer` 卡片容器（300×200）
- 显示控件：`LEDIndicator` LED指示灯（140×30）、`NumericDisplay` 数值显示（160×90）、`ProgressBar` 进度条（250×20）、`ProgressRingDisplay` 进度环（120×130）、`ImageDisplay` 图片显示（200×150）
- 图表控件：`RealtimeChart` 实时曲线（400×280）、`GaugeMeter` 仪表盘（180×180）、`DataTable` 数据表格（350×250）
- 通信控件：`SerialConfigCard` 串口配置卡片（360×320）、`TcpConfigCard` TCP 配置卡片（360×250）、`UdpConfigCard` UDP 配置卡片（360×220）、`MqttConfigCard` MQTT 配置卡片（380×390）、`DataSendCard` 数据发送卡片（350×140）、`DataRecvCard` 数据接收卡片（350×250）、`LogBox` 日志显示框（400×200）、`ModbusSlaveTable` 从站寄存器表（260×300）
- [工业设备与工业仪表的类型和默认值](https://raw.githubusercontent.com/txp666/FluentHMI-Studio/main/docs/uidp/industrial.md)
- [汽车电子、电子 DIY 与嵌入式的类型和默认值](https://raw.githubusercontent.com/txp666/FluentHMI-Studio/main/docs/uidp/electronics.md)
