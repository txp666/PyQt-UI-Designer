# 第一次 S7 PLC 联调：读数、曲线与写入

这是 S7 视频教程的配套实操说明。从已摆好控件的工程开始，连接本地 PLC 模拟器，读取 REAL/INT、绘制压力曲线，再写入 BOOL 启停位和 INT 转速。

**版本对齐日期：2026-11-16。** FluentHMI Studio **0.7.0**、PyQt UI Designer **0.7.0**、FluentPLC Simulator **0.1.1**，工程格式 **UIDP 1.1**。本次在 macOS arm64 上通过真实的本机 S7 连接验证，不代表已验证物理西门子 PLC。

[视频与图文教程](https://hmi.modusignal.cn/tutorials/12-s7-plc/?lang=zh)

## 配套文件与预期结果

- [中文 HMI 工程](../../examples/tutorials/13-S7PLC联调.uidp)
- [英文 HMI 工程](../../examples/tutorials/13-S7-PLC-Monitor-en.uidp)
- [模拟器工程](../../examples/tutorials/13-s7-first-plc.plcsim.json)

两个 HMI 工程的 ID、地址和命令完全相同，只翻译可见文字。两款桌面 HMI 都能打开；网页版编辑器当前不支持该 S7 后端。

| 数据 | 地址 / 类型 | 行为 |
| --- | --- | --- |
| 泵启停 | `DB1.DBX0.0 / BOOL` | 手动值，初始关闭；开关读写同一位 |
| 邻位 | `DB1.DBX0.7 / BOOL` | 初始开启，启停切换后保持开启 |
| 转速反馈 | `DB1.DBW2 / INT` | 初值 900 rpm，输入框和预设按钮写入 |
| 温度 | `DB1.DBD4 / REAL` | 固定 23.5 °C，数值显示与仪表共用 |
| 压力 | `DB1.DBD8 / REAL` | 8 秒周期正弦规则，0.8–1.6 bar，驱动数值与曲线 |

本地验证记录：C++0.7.0的设计器预览与导出Runtime在1102实例实际读写；Py0.7.0原生PreviewCanvas使用同工程的临时21112副本独立验证，读到REAL23.5和5个曲线样本，INT900→1500→900、BOOL128→129→128且邻位保留，4次UI写入由独立客户端核对。本期正式截图与视频实录C++界面，没有在本期编译或录制Py导出应用。

## 1. 启动本地模拟器

下载 [FluentPLC Simulator 0.1.1](https://github.com/txp666/FluentPLC-Simulator/releases/tag/v0.1.1)。先停止服务，再打开配套 `.plcsim.json` 工程。确认绑定地址 `127.0.0.1`、端口 `1102`，然后启动。载入或应用工程会恢复工程初值。

安装包中的命令行程序也能运行同一份工程：

```sh
FluentPLCServer --project 13-s7-first-plc.plcsim.json --listen 127.0.0.1 --port 1102
```

Windows 使用 `FluentPLCServer.exe`；macOS 的程序在模拟器应用的 `Contents/MacOS/` 内。本地示例使用非特权端口 1102；真实 PLC 常用 102。端口改动时，HMI 卡片也要同步修改。

模拟器模拟的是 S7 通信和数据变化，不执行梯形图、STEP 7 或 TIA Portal 工程。

## 2. 打开 HMI 并连接

使用 [FluentHMI Studio 0.7.0](https://github.com/txp666/FluentHMI-Studio/releases/tag/v0.7.0) 或 [PyQt UI Designer 0.7.0](https://github.com/txp666/PyQt-UI-Designer/releases/tag/v0.7.0)。安装包随附原生 S7 库。

打开 `.uidp` 工程。连接卡片 ID 为 `lesson-plc`，显示标题可改，绑定依靠的是 ID。检查这些连接属性：

| 设置 | 值 |
| --- | --- |
| 地址 | `127.0.0.1` |
| 端口 | `1102` |
| 机架 / 插槽 | `0 / 1` |
| 连接类型 | `PG (1)` |
| 默认轮询周期 | `200 ms` |
| 超时 | `1000 ms` |
| 自动连接 | 关闭 |

进入预览、运行预览，再点 S7 卡片的「连接」。应读到温度 **23.5 °C**、转速 **900 rpm**，压力在 **0.8–1.6 bar** 间变化。工程默认不自动连接，单纯打开不会连接设备。

![C++ 0.7.0 导出应用连接本地模拟器的实际画面，明亮主题](https://hmi.modusignal.cn/tutorials/assets/12-s7-plc/v070/zh/preview-light.webp)

*实际截图来自 C++ 0.7.0 导出应用；设计器预览共用相同的 S7 运行逻辑。*

## 3. 按地址和类型读取

选中温度卡片，数据绑定的解析模式为 **S7**、数据源为 **lesson-plc**、地址 **DB1.DBD4**、类型 **REAL**。右侧仪表也读取同一个点。

```json
{"parseMode":"S7","sourceCardId":"lesson-plc",
 "s7":{"address":"DB1.DBD4","dataType":"REAL","period":0}}
```

`DB1` 是数据块；`DBD4` 表示从字节 4 读取四个字节。转速用 `DB1.DBW2 / INT`，从字节 2 读取两个字节；BOOL 用 `DB1.DBX0.0` 这样的位地址。地址宽度要匹配数据类型。采集周期填 `0` 表示跟随连接卡片，也能给某个点单独设置毫秒周期。

## 4. 绘制压力曲线

第一条曲线选择 **S7**、数据源 **lesson-plc**、地址 **DB1.DBD8 / REAL**。曲线通过真实 S7 响应读到模拟器的正弦值，界面本身不生成压力数据。

```json
{"_curve_0_parseMode":"S7","_curve_0_sourceCardId":"lesson-plc",
 "_curve_0_s7":{"address":"DB1.DBD8","dataType":"REAL","period":0}}
```

## 5. 写入启停与转速

接收绑定和发送配置分开设置。开关绑定 `DB1.DBX0.0 / BOOL` 读取反馈，S7 发送目标也选 `lesson-plc` 的同一位，开启写 `1`，关闭写 `0`。

```json
{"commandMode":"S7","commandTargetId":"lesson-plc",
 "s7Command":{"address":"DB1.DBX0.0","dataType":"BOOL",
              "value":"1","onValue":"1","offValue":"0"}}
```

拨动开关后，状态从 PLC 读回；模拟器里的邻位 `DB1.DBX0.7` 仍保持开启。BOOL 采用原生单个位写入，避免整字节覆盖其他位。

在转速输入框输入 **1500** 并按回车。其发送模式为 S7，目标是 `DB1.DBW2 / INT`。上方应读回 **1500 rpm**。点击「恢复 900 rpm」写入固定值 `900`，压力曲线继续变化。

## 6. 保存和导出

保存工程后，C++ 版可以直接导出独立运行时应用，无需现场编译；Py 版可导出可编辑源码或一键编译打包。S7 导出同时携带平台原生库和许可文件，按目标操作系统与架构导出或构建。

含 S7 的工程使用 **UIDP 1.1**，须用具备 S7 功能的新桌面版打开；旧版会拒绝读取。未使用 S7 的工程仍保存为 UIDP 1.0。

## 排错与适用范围

| 现象 | 检查 |
| --- | --- |
| 连不上 | 服务是否启动，地址/端口是否一致，机架与插槽 |
| 连上但读数不对 | 数据源、DB 号、字节/位地址、数据类型 |
| 写入后数值又变回去 | 目标点是否受动态规则驱动；可写控件应指向手动点 |
| 界面变化但 PLC 没变化 | 检查发送模式与目标卡片，不能只设置接收绑定 |

当前是经典绝对地址 S7comm，主要面向 S7-300/400；兼容的 S7-1200/1500 配置需要允许 PUT/GET、使用非优化全局 DB。不包含 S7CommPlus、优化 DB 或符号访问。连接真实设备前参阅 [S7 配置与范围](../s7.md)。

配置依据：[Snap7 客户端与 S7-1200/1500 说明](https://snap7.sourceforge.net/snap7_client.html)、[西门子 PUT 指令文档](https://docs.tia.siemens.cloud/r/en-us/v20/s7-communication-s7-1200-s7-1500/put-write-data-to-a-remote-cpu-s7-1200-s7-1500)。实机请以对应 CPU 和固件手册为准。
