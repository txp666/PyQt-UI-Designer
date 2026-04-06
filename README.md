<p align="center">
  <img src="logo.png" width="120" alt="PyQt UI Designer">
  <h1 align="center">PyQt UI Designer</h1>
  <p align="center">面向硬件工程师的可视化上位机设计工具</p>
  <p align="center">
    <a href="#通信协议支持">通信协议</a> •
    <a href="#功能特性">功能特性</a> •
    <a href="#快速开始">快速开始</a> •
    <a href="#使用说明">使用说明</a> •
    <a href="#项目结构">项目结构</a> •
    <a href="#协议文档">协议文档</a> •
    <a href="#许可证">许可证</a>
  </p>
</p>

---

**PyQt UI Designer** 是一个零代码/低代码的桌面上位机设计器。通过拖拽控件、配置属性、绑定通信数据，即可快速生成可独立运行的 PyQt5 上位机程序，并支持一键打包为 exe。

## 界面预览

### 设计器界面

![设计器界面](images/designer.png)

### 预览运行

![预览运行](images/preview.png)

## 通信协议支持

| 协议 | 状态 | 说明 |
|------|------|------|
| **串口 (Serial)** | ✅ 已支持 | RS-232/485/TTL，支持行文本、HEX 帧、Modbus RTU 解析 |
| **TCP Client/Server** | 🚧 开发中 | TCP Socket 通信 |
| **MQTT** | 🚧 开发中 | MQTT 发布/订阅，适用于物联网场景 |
| **UDP** | 📋 计划中 | UDP 数据报通信 |
| **Bluetooth** | 📋 计划中 | 蓝牙串口 (SPP) / BLE |

> 本项目采用模块化通信架构设计，方便扩展更多协议。欢迎贡献 PR！

## 功能特性

### 可视化设计器
- 拖拽式 UI 设计，所见即所得
- 网格吸附与对齐辅助（左对齐、右对齐、顶/底对齐、横纵分布）
- 画布大小自由设置，支持缩放
- 深色/浅色主题切换，云母效果（Win11）
- 项目文件 `.uidp` 保存与加载

### 丰富的控件库

| 分类 | 控件 |
|------|------|
| **基础控件** | 按钮、标签、输入框、下拉框、开关、滑块、数值框 |
| **布局控件** | 水平布局、垂直布局、弹性布局、分组框、选项卡、分割线、卡片容器 |
| **显示控件** | LED 指示灯、数值显示、进度条、进度环、图片显示 |
| **图表控件** | 实时曲线（多通道、游标、数据保存/加载）、仪表盘 |
| **通信控件** | 数据表格 |
| **复合控件** | 串口配置卡片、数据发送卡片、数据接收卡片、Modbus 配置卡片、日志显示框 |

### 多协议通信
- **串口**（已支持）：内置串口管理，自动扫描端口，支持多种波特率/数据位/校验位/停止位
- **TCP / MQTT / UDP / 蓝牙**：开发中，架构已预留扩展接口
- 三种数据解析模式：行文本解析、HEX 帧解析、Modbus RTU 解析
- 自动协议识别

### 数据绑定与解析
- **键值匹配**：解析 `key1:value1,key2:value2` 格式
- **JSON 路径**：解析 JSON 数据，支持嵌套路径
- **HEX 字节提取**：从二进制帧中按偏移提取数据，支持多种数据类型
- **Modbus RTU**：完整的 Modbus 寄存器解析，支持多种数据类型、字节序、功能码过滤

### 命令发送
- 文本模式：带换行符选项
- HEX 模式：支持帧头帧尾、数据类型打包
- Modbus 模式：自动构建 Modbus RTU 帧，支持轮询
- 命令模板：`{value}` 占位符动态替换

### 代码导出与打包
- 一键导出为独立可运行的 Python 项目（`main.py` + `ui.py` + `serial_handler.py` + `data_binding.py`）
- 内置 Nuitka 一键打包，实时显示编译终端输出
- 打包完成自动清理编译缓存、重命名、压缩为 zip
- 自定义上位机名称，同步到窗口标题和打包产物

## 快速开始

### 环境要求

- Python 3.10+
- Windows 10/11（串口通信依赖）

### 安装

```bash
git clone https://github.com/txp666/PyQt-UI-Designer.git
cd PyQt-UI-Designer

# 创建虚拟环境（推荐）
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 运行

```bash
python main.py
```

### 打包设计器本身

```bash
python deploy.py
```

## 使用说明

### 1. 设计界面

在左侧控件面板中拖拽控件到画布，通过右侧属性编辑器配置控件属性。

### 2. 配置数据绑定

选中显示类控件（数值显示、LED、进度条等），在属性编辑器中设置：
- **绑定键**：对应串口数据中的字段名
- **解析模式**：选择键值匹配、JSON 路径、HEX 字节提取或 Modbus

### 3. 配置命令发送

选中交互类控件（按钮、开关、滑块等），设置：
- **发送模式**：文本、HEX 或 Modbus
- **命令内容**：要发送的数据
- **命令模板**（可选）：使用 `{value}` 占位符

### 4. 预览运行

切换到"预览运行"页面，点击"运行预览"，连接串口后即可实时测试。

### 5. 导出与打包

- **导出代码**：`Ctrl+Shift+E` 或导航栏"导出代码"，选择输出目录
- **一键打包**：在预览页面点击"一键打包"，选择目录后自动导出 + Nuitka 编译 + 压缩

## 项目结构

```
pyqtUIDesigner/
├── main.py                     # 程序入口
├── deploy.py                   # Nuitka 打包脚本
├── requirements.txt            # 依赖清单
├── docs/
│   └── protocol.md             # 协议文档
├── app/
│   ├── common/
│   │   ├── config.py           # 应用配置
│   │   ├── signal_bus.py       # 全局信号总线
│   │   └── style_sheet.py      # 样式表
│   ├── core/
│   │   ├── code_generator.py   # 代码导出生成器
│   │   ├── data_binding.py     # 数据绑定引擎
│   │   ├── project.py          # 项目序列化
│   │   ├── protocol_parser.py  # 协议解析器
│   │   ├── serial_manager.py   # 串口管理
│   │   └── widget_registry.py  # 控件注册表
│   ├── designer/
│   │   ├── canvas.py           # 设计画布 (Scene/View)
│   │   ├── canvas_item.py      # 画布控件项
│   │   ├── palette.py          # 控件面板
│   │   ├── property_editor.py  # 属性编辑器
│   │   └── selection_manager.py# 选择与对齐
│   ├── view/
│   │   ├── main_window.py      # 主窗口
│   │   ├── designer_interface.py # 设计器页面
│   │   ├── preview_interface.py  # 预览运行页面
│   │   └── setting_interface.py  # 设置页面
│   └── widgets/
│       ├── base.py             # 控件元数据定义
│       ├── basic.py            # 基础控件
│       ├── chart.py            # 图表控件
│       ├── comm.py             # 通信控件
│       ├── composite.py        # 复合控件
│       ├── display.py          # 显示控件
│       └── layout.py           # 布局控件
```

## 协议文档

详细的数据接收解析和命令发送协议说明请参阅 [docs/protocol.md](docs/protocol.md)。

## 技术栈

- **PyQt5** — GUI 框架
- **PyQt-Fluent-Widgets** — 现代 Fluent Design 风格控件库
- **pyqtgraph** — 高性能实时图表
- **pyserial** — 串口通信
- **Nuitka** — Python → exe 编译打包

## 致谢

- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) — 提供了精美的 Fluent Design 控件
- [pyqtgraph](https://github.com/pyqtgraph/pyqtgraph) — 高性能科学绘图库

## 许可证

本项目采用 [GPLv3](LICENSE) 许可证开源。
