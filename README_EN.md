<p align="center">
  <img src="logo.png" width="120" alt="PyQt UI Designer">
  <h1 align="center">PyQt UI Designer</h1>
  <p align="center">A visual HMI designer for hardware engineers</p>
  <p align="center">
    <a href="https://github.com/txp666/PyQt-UI-Designer/releases/latest"><img src="https://img.shields.io/github/v/release/txp666/PyQt-UI-Designer?style=flat-square" alt="Release"></a>
    <a href="LICENSE"><img src="https://img.shields.io/github/license/txp666/PyQt-UI-Designer?style=flat-square" alt="License"></a>
    <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square" alt="Python">
    <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS-lightgrey?style=flat-square" alt="Platform">
    <a href="https://www.bilibili.com/video/BV13KHG6VEvL"><img src="https://img.shields.io/badge/Video-Bilibili-00A1D6?style=flat-square&logo=bilibili&logoColor=white" alt="Video"></a>
    <a href="https://modusignal.cn/pyqt-ui-designer/"><img src="https://img.shields.io/badge/Website-modusignal.cn-2ea44f?style=flat-square" alt="Website"></a>
  </p>
  <p align="center">
    <a href="https://github.com/txp666/PyQt-UI-Designer/releases/latest"><img src="https://img.shields.io/badge/Download-Latest_Release-blue?style=for-the-badge&logo=windows" alt="Download"></a>
  </p>
  <p align="center">
    English •
    <a href="README.md">简体中文</a> •
    <a href="https://modusignal.cn/pyqt-ui-designer/">Website</a> •
    <a href="https://modusignal.cn/pyqt-ui-designer/guide/">User guide</a> •
    <a href="#demo-video">Demo video</a> •
    <a href="#quick-start">Quick start</a> •
    <a href="#features">Features</a> •
    <a href="docs/protocol.md">Protocol</a> •
    <a href="#faq">FAQ</a> •
    <a href="#c-version-fluenthmi-studio">C++ version</a>
  </p>
</p>

---

**PyQt UI Designer** is a no-code / low-code designer for desktop control and monitoring apps (上位机) for hardware. Drag widgets onto a canvas, set their properties, and bind them to serial, TCP or MQTT data, and it generates a standalone PyQt5 app that it can package as an exe on Windows or an `.app` on macOS. No more writing the UI, the communication code and the protocol parsing from scratch for every hardware project.

> **Language**: the designer's interface, the online user guide and the documents in `docs/` are in Chinese for now.

> **Try the C++ version, [FluentHMI Studio](https://github.com/txp666/FluentHMI-Studio)**: it opens the same `.uidp` projects, with a smaller download and faster startup, and exports an app in under a second without Python or a compiler. See [C++ version: FluentHMI Studio](#c-version-fluenthmi-studio) below.

## Demo video

<a href="https://www.bilibili.com/video/BV13KHG6VEvL"><img src="images/video-cover.jpg" width="720" alt="PyQt UI Designer demo video"></a>

Click the image to watch it on Bilibili (narrated in Chinese). The video walks through the whole workflow, from drag-and-drop design, data binding and live preview to export and packaging; every shot is a screen recording of the software itself.

## Screenshots

### Designer

Drag widgets onto the canvas, and edit their properties and data bindings on the right:

![Designer](images/designer.jpg)

### Live preview

The same project runs live once it is connected to a device (the data in the screenshot comes from a simulated MQTT device):

![Live preview](images/preview.jpg)

## C++ version: FluentHMI Studio

[FluentHMI Studio](https://github.com/txp666/FluentHMI-Studio) is a C++/Qt 6 rewrite of this project with a UI built on [FluentQtWidgets](https://github.com/txp666/FluentQtWidgets); its current version is 0.1.0. It reads and writes the same `.uidp` projects, and its widgets, properties, parser modes, data bindings and command encoding match this project one to one, so a project made here can be opened, previewed and exported there as it is. Compared with this project:

- **Exporting needs no Python or compiler**: export copies a prebuilt runner and adds the project and its images, which takes about 0.3 s. This project first generates Python source and then compiles it with Nuitka, and the downloaded designer needs Python and build tools installed separately before it can package.
- **The preview is the finished app**: the preview and the exported app are the same runner, so what you see in the preview is what you get after export.
- **Smaller downloads**: 16.7 MB on Windows (this project: 54.2 MB); on macOS a single 32.7 MB universal package covers both Apple Silicon and Intel, and the apps it exports are universal too (this project has one package per architecture, 53.8 / 62.8 MB).
- **Faster startup, less memory**: on the same Mac it takes 0.7–1.1 s to show its window (this project: 1.5–2.2 s) and uses 71–85 MB of memory after startup (this project: 126–137 MB).
- **In-app updates**: it checks for new versions from the settings page or at startup, downloads them and verifies the SHA-256, and swaps in the new version when you restart or quit.

What it doesn't have yet: exporting a source project you can keep editing, and the live chart's cursor and data save / load. If you need those, keep using this project. For the full comparison and how it was measured, see [Compared with the Python version](https://github.com/txp666/FluentHMI-Studio/blob/main/README_EN.md#compared-with-the-python-version) in the FluentHMI Studio README.

## Quick start

### Download and run

Download the archive for your platform from [Releases](https://github.com/txp666/PyQt-UI-Designer/releases/latest) or the [website](https://modusignal.cn/pyqt-ui-designer/#downloads). The archives include Python and Qt, so there is nothing else to install.

| Platform | File | How to run |
| --- | --- | --- |
| Windows 10/11 | `PyQt-UI-Designer-vX.Y.Z-windows-x64.zip` | Unzip and run `main.exe` |
| macOS (Apple Silicon) | `PyQt-UI-Designer-vX.Y.Z-macos-arm64.zip` | Unzip and open the `.app` |
| macOS (Intel) | `PyQt-UI-Designer-vX.Y.Z-macos-x64.zip` | Unzip and open the `.app` |

Each archive comes with a `.sha256` checksum file. The packages are not code-signed, so the system may block them the first time you open them; see the [FAQ](#faq) for what to do.

### Try it without hardware

The [demo](demo/README.md) in this repository contains an editable `.uidp` project, the complete code the designer exported from it, and a simulated serial device. After installing the dependencies as described in [Run from source](#run-from-source), run this from the repository root:

```bash
python demo/simulate.py
```

Choose the `DEMO` port and connect to see temperature and pressure readings, a two-channel live chart, the running status and command sending. To connect a real device, run `python demo/main.py`. The whole `demo` folder can also be copied out of the repository and run on its own.

### Run from source

Requirements: Python 3.10+, Windows 10/11 or macOS (Apple Silicon / Intel).

Windows:

```bash
git clone https://github.com/txp666/PyQt-UI-Designer.git
cd PyQt-UI-Designer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

macOS:

```bash
git clone https://github.com/txp666/PyQt-UI-Designer.git
cd PyQt-UI-Designer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

On Apple Silicon use a native arm64 Python; on an Intel Mac use an x86_64 Python. The requirements file already has the conditions that pick a Qt 5 runtime with Apple Silicon support, so don't pin an older Qt that only has Intel packages.

## Features

### Visual design

- Drag-and-drop UI design, what you see is what you get
- Grid snapping and alignment helpers (align left / right / top / bottom, distribute horizontally / vertically)
- Any canvas size, with zoom
- Dark and light themes, Mica effect on Windows 11
- Projects saved and loaded as `.uidp` files

### 29 widgets

| Category | Widgets |
| --- | --- |
| **Basic** | Button, label, line edit, combo box, switch, slider, spin box |
| **Layout** | Horizontal layout, vertical layout, flex layout, group box, tab widget, separator, card container |
| **Display** | LED indicator, numeric display, progress bar, progress ring, image |
| **Charts** | Live chart (multiple channels, cursor, data save / load), gauge |
| **Communication** | Data table |
| **Composite** | Serial config card, TCP config card, MQTT config card, send card, receive card, Modbus config card, log box |

### Receiving and binding data

- **Serial ports**: scans ports automatically; baud rate, data bits, parity, stop bits and flow control are configurable
- **TCP client / server**: connect to a device as a client, or listen on a port and let devices connect in; the server accepts several devices at once and frames each connection separately
- **MQTT subscribe / publish**: connect to a broker and subscribe to one or more topics (with `+` and `#` wildcards) to receive data, and publish commands to a chosen topic; supports username and password, QoS 0/1/2 and TLS
- All three links share the same parser modes, data bindings, charts, tables and logs, and commands go to every connected link
- **Key-value matching**: parses `key1=value1,key2=value2`, top-level JSON fields, or CSV (channels are named `ch0`, `ch1`… automatically)
- **JSON path**: parses JSON data, including nested paths
- **HEX byte extraction**: extracts data from binary frames by offset, with several data types
- **Modbus RTU**: full register parsing with several data types, byte orders and function code filtering; the CRC is checked on both normal and exception responses
- **Modbus TCP**: frames by the MBAP header and outputs exactly the same dictionary as RTU, so the same binding settings work for both
- **Modbus ASCII**: frames by `:` and `\r\n` and checks the LRC, with the same output as RTU; Modbus commands are framed as ASCII on a `modbus_ascii` link
- **Binding by register address**: read requests sent from here are remembered, so the registers in a response are also named by address (holding register 100 is `hr100`) and a binding can pick a register table and an address; polling several address blocks of a PLC doesn't mix them up
- Serial, TCP and MQTT all offer five parser modes (line text, binary HEX frame, Modbus RTU, Modbus TCP, Modbus ASCII) and can detect the format of a line protocol automatically; binary HEX frames are framed by header and footer, length field, checksum, fixed length or idle gap, set for the project or for each link card

### Sending commands

- **Text mode**: optional line ending
- **HEX mode**: frame header and trailer, and packing values by data type
- **Modbus mode**: builds frames automatically and can poll; the frame format is chosen per link: links whose parser mode is `modbus_tcp` send MBAP frames, `modbus_ascii` links send ASCII frames, the others send RTU frames with a CRC. FC16 write multiple registers writes int16, 32-bit integers and float32 values by data type
- **Automatic Modbus polling**: bind widgets to register addresses and they are read, with no polling card needed: once the link connects, neighbouring addresses are merged into read blocks and the widgets on screen are read at each binding's own period; control writes go out between two reads instead of colliding with them. The Modbus card is optional: it sets the polling parameters, shows the status (missing replies, the exception codes a device returns) and sends requests by hand
- **Command templates**: insert a widget's current value with the `{value}` placeholder

### Export and packaging

- One-click export to a standalone Python project (`main.py`, `ui.py`, `comm_hub.py`, `serial_handler.py`, `tcp_handler.py`, `mqtt_handler.py`, `data_binding.py`, `theme_support.py`)
- Built-in one-click packaging with Nuitka, showing the compiler output live; when it finishes it cleans up the build cache, renames the output and zips it
- A custom app name, used for the window title and the packaged output

### Let AI write the project

A `.uidp` file is JSON. Give Claude, Codex or another AI your requirements together with this link, and it can write the project file directly:

```text
https://raw.githubusercontent.com/txp666/PyQt-UI-Designer/main/docs/uidp-format.md
```

This is the raw text of [docs/uidp-format.md](docs/uidp-format.md), which an AI can read in one go without opening a web page or cloning the repository. The guide is written in Chinese, and AI assistants can read it as it is. It has the rules, a complete example and a list of widgets; every property of every widget is in [docs/uidp-widgets.md](docs/uidp-widgets.md), which is generated from the widget definitions and linked from the guide for when it's needed. When the file is written, check it with `python tools/check_uidp.py project.uidp` (it also points out misspelt property names and options, which opening the file doesn't report), then open, preview and export it in the designer.

## Supported protocols

| Protocol | Status | Notes |
| --- | --- | --- |
| **Serial** | ✅ Supported | RS-232/485/TTL, with line text, HEX frame and Modbus RTU parsing |
| **TCP Client/Server** | ✅ Supported | TCP client or server; the server accepts several devices. Same parser modes as serial, plus Modbus TCP (MBAP): with `modbus_tcp` selected, Modbus commands are framed as MBAP automatically |
| **MQTT** | ✅ Supported | Subscribe / publish, with wildcard topics, username and password, QoS 0/1/2 and TLS; each message is parsed as one frame, and a payload that is just a number can be bound by its topic name |
| **UDP** | 📋 Planned | UDP datagrams |
| **Bluetooth** | 📋 Planned | Bluetooth serial (SPP) / BLE |

The communication layer is modular: every link implements the same set of signals, and `CommHub` gathers them for bindings, charts, tables and logs, which makes it easy to add more protocols. PRs are welcome. See [docs/protocol.md](docs/protocol.md#六传输链路串口tcpmqtt) for details of each link.

## How to use it

The full illustrated guide is on the [website](https://modusignal.cn/pyqt-ui-designer/guide/), and the protocol formats are in [docs/protocol.md](docs/protocol.md). The interface is in Chinese, so the names of buttons and fields below are followed by their Chinese labels.

1. **Design the UI**: drag widgets from the widget panel on the left onto the canvas, and set their properties in the property editor on the right.
2. **Bind data**: select a display widget (numeric display, LED, progress bar and so on) and set its binding key (绑定键, the field name in the device's data) and parse mode (解析模式: key-value matching, JSON path, HEX byte extraction or Modbus).
3. **Configure commands**: select an interactive widget (button, switch, slider and so on) and set the send mode (text, HEX or Modbus), the command, and optionally a `{value}` command template.
4. **Preview**: switch to the Preview page (预览运行) and click Run preview (运行预览), then connect to the device with a serial, TCP or MQTT config card to test it live.
5. **Export and package**: the shortcut for exporting code is `Ctrl+Shift+E` on Windows and `⌘⇧E` on a Mac, or click Export code (导出代码) in the navigation bar. On the Preview page, click Package (一键打包) and choose a folder; it exports, compiles with Nuitka and zips the result automatically. Packaging needs a C/C++ compiler on the machine: the Xcode Command Line Tools on macOS, and on Windows a compiler that Nuitka supports (MSVC for Python 3.13+).

<details>
<summary><b>Data parsing rules</b></summary>

Line text ends with the line terminator (LF `\n` by default, CRLF works too; the frame format can change it to `;` and so on), and JSON is split where its brackets close, without a terminator. A partial packet waits for the next bytes, and several frames in one batch are all processed in order. An escaped `\n` inside a JSON string stays part of the content. The CRC is checked on both normal and exception Modbus responses, and a corrupted frame doesn't update any widget.

Sliders, spin boxes, progress bars, progress rings and gauges ignore data that can't be converted: integer widgets reject values outside Qt's integer range, and gauges reject NaN and Infinity, while the other bindings in the same frame keep updating. Switches accept explicit boolean text and numbers, and unknown text leaves their state unchanged; an LED's custom on and off values take precedence. The preview and standalone exports follow the same rules, and odd-length hex text in a HEX frame header or trailer gets a leading zero.

The default parser mode (默认解析模式) of the serial, TCP and MQTT config cards can be `line`, `hex`, `modbus`, `modbus_tcp`, `modbus_ascii` or project settings (项目设置). Project settings uses `serial.parser` / `parserConfig` from the `.uidp`, which defaults to line text, and the three links share this one frame format configuration. Data bits, parity, stop bits, flow control and the parser mode use the same implementation in the preview and in exported programs. Switching to another parser mode uses that mode's configuration, and choosing project settings brings back the project's.

The TCP server frames each connected device separately, and commands are written to every connected device. MQTT treats each message as one frame: in line text mode, payloads without a trailing line terminator are parsed too; a payload that is a single plain number is also given a second time with the topic name as its key, so you can bind to the topic name directly; HEX frames buffer partial packets per topic. When several links are connected at once, commands go to every connected link.

</details>

<details>
<summary><b>Live chart and history</b></summary>

The live chart redraws in batches about every 33 ms, and its display buffer holds up to 10,000 points per channel. Every sample is also written to a temporary file, so Save (保存) exports the full history as CSV or JSON, including what no longer fits in the display buffer. Clearing the chart, stopping the preview or closing the widget releases the temporary record, so save the data you want to keep first. CSV is recommended for large files; loading CSV and exporting history are both streamed.

Loading a history file keeps the current acquisition bindings, parser mode and which curves are shown or hidden (click a curve's line in the chart legend to switch). A chart that is already configured requires the file's channel names and count to match, though unique names may come in any order; if they don't match, it reports an error and keeps its data. A blank default chart that hasn't been configured can still import new channels.

An invalid value doesn't interrupt the other chart channels in the same frame, and isn't written to the history. History files containing non-finite or invalid values are rejected, and the current data stays as it was. When channel names are unique, JSON still uses an object that maps names to sample arrays; channels with duplicate names use an ordered array of `name` / `values` entries so that duplicate keys don't lose data, and the old format can still be read.

</details>

<details>
<summary><b>Preview, commands and project editing</b></summary>

Switches, sliders and spin boxes can be updated from received data. Updates from the device don't send commands, while user actions still send as configured. When you disconnect and reconnect quickly, data and errors queued from the old connection are ignored.

Changing the design, opening another project or creating a new one stops the old preview and disconnects; running it again uses the current design, so old commands are never sent. Stopping the preview releases the widgets along with their timers and signal connections, so it can be started and stopped repeatedly.

A Modbus button only uses the protocol settings currently visible, and an invalid address, quantity or value isn't sent. HEX content, frame headers and trailers and binary values use the same encoding rules in the preview and in exports. The Modbus card shows "sent" (已发送) only after the whole command has been written; a failed or short write reports a failure. "Sent" doesn't mean the device has confirmed it: when a link parses `modbus` / `modbus_tcp` / `modbus_ascii`, the card shows "device replied" (设备已响应) or the exception code it returned once the device answers, and "no reply" (无响应) after the timeout. A Modbus switch sends an FC05 write single coil command in both the preview and exports.

New, Open and Quit offer Save / Discard / Cancel. Cancelling the save, or a failed save, stops the switch. Projects are validated before saving and loading, and a failure keeps the current canvas and the existing file. Saving replaces the file atomically through a temporary file in the same folder, so an interrupted write can't corrupt the original. Resizing respects each widget's minimum width and height, and each tab page keeps its own layout and child widget positions.

A tab name is applied when you leave the edit box, or when you save, preview or export, so a half-typed name doesn't change which page a widget belongs to. When the number of pages is reduced, widgets on the removed pages move to the last page; an empty name keeps one default page. Aligning across containers uses canvas coordinates, and children of automatic layouts stay managed by their layout.

</details>

<details>
<summary><b>Export details and themes</b></summary>

Exports keep a button's disabled state, a line edit's default text and read-only state, and a combo box's default item. Custom properties of the send, receive, table, log and Modbus widgets and of the serial / TCP / MQTT config cards carry over to the exported program. Tables and logs receive data from all links automatically, and text such as `<` and `>` in the receive area is shown as it is.

Exports and packages inherit the light, dark or follow system mode currently set on the Settings page. Follow system updates when the standalone program starts and when the system appearance changes. Switching themes updates the design canvas, the running preview, native Qt widgets and chart colors together, and keeps widget values, chart history, check states and custom font sizes and colors; the receive and log terminals keep a dark background so that existing colored messages stay readable.

Local files used by image widgets are copied to `assets/` in the export folder, so they still load after the whole project is moved. Relative image paths are resolved against the folder of the saved project, or the current working directory for an unsaved one. If an image file doesn't exist or can't be read, export reports an error.

Widget IDs in imported projects may contain spaces, quotes and Chinese characters, and export keeps them as dictionary keys. Files are written to the target folder only after code generation and the syntax check have finished, so a configuration error never overwrites existing exported files.

</details>

<details>
<summary><b>macOS tips</b></summary>

- New, Open and Save are `⌘N`, `⌘O` and `⌘S`.
- Select a widget on the canvas and press `Delete (⌫)` to delete it; `Fn+Delete` works too.
- Scroll with two fingers on the trackpad to pan the canvas, and hold `⌘` while scrolling to zoom.
- Serial ports usually appear as `/dev/cu.usbserial-*` or `/dev/cu.usbmodem*`, and the device path's case is kept. Install USB-to-serial drivers as the chip vendor requires.
- Open output folder (打开输出目录) uses Finder; the Mica effect is only available on Windows 11.
- When running from source, one-click packaging prefers the current virtual environment. One-click packaging in the standalone `.app` still needs Python and build tools installed separately; you can activate a virtual environment with this project's dependencies in Terminal and start the app from there.
- If the Python it finds is missing the packaging dependencies, it creates `.build-venv` in the export folder and installs them there, which works with Homebrew's protection of its system Python; later packaging can reuse that environment.

</details>

## FAQ

**Windows says "Windows protected your PC"**: the exe has no digital signature (code-signing certificates cost money); it is not a virus. Click "More info" → "Run anyway".

**macOS says the developer can't be verified**: the `.app` isn't signed with an Apple Developer ID or notarized. After it's blocked the first time, go to System Settings → Privacy & Security and click "Open Anyway".

For more questions (no serial port found, widgets not updating, saving chart data and so on), see the [FAQ on the website](https://modusignal.cn/pyqt-ui-designer/guide/#faq).

## Development

### Running the tests

```bash
python -m unittest discover -s tests -v
python tests/smoke_gui.py
```

The second one needs a working desktop session: it opens the designer and an exported test program, then quits by itself. The frameless window on macOS relies on Cocoa, so the Qt `offscreen` plugin can't stand in for checking the native window.

### Packaging the designer itself

```bash
python deploy.py
```

Before packaging on macOS for the first time, install the build tools:

```bash
xcode-select --install
source .venv/bin/activate
python deploy.py
open "build/PyQt UI Designer.app"
```

The output is `build/PyQt UI Designer.app` and a zip of the same name; on Windows it is `build/PyQt UI Designer/main.exe` and a zip of the same name. Both include Python, Qt and the icon resources, so they run without Python installed. Packaging builds for the architecture of the local Python, and building the Mac app on Windows isn't supported. The minimum macOS version depends on the Python, Qt and build tools used for the build; check the Nuitka build log.

The `.app` is zipped with macOS `ditto`, which keeps executable permissions and framework symlinks. The default build isn't signed with an Apple Developer ID or notarized; do that separately before distributing it.

### Releasing a new version

Bring the version in `app/common/metadata.py` and `docs/release-notes/vX.Y.Z.md` in line, commit, then push the matching `vX.Y.Z` tag. GitHub Actions builds for all three platforms, verifies the archive checksums and that the unpacked apps start, and only publishes the GitHub Release when everything passes.

### Project structure

```
PyQt-UI-Designer/
├── main.py              # Entry point
├── deploy.py            # Packages the designer itself (Nuitka)
├── requirements.txt     # Dependencies
├── app/
│   ├── common/          # Config, version info, packaging support, update check
│   ├── core/            # Project I/O, data binding, protocol parsing, serial / TCP / MQTT runtime, code generation
│   ├── designer/        # Design canvas, widget panel, property editor, selection and alignment
│   ├── view/            # Main window, and the designer, preview and settings pages
│   └── widgets/         # Widget definitions: basic, layout, display, chart, communication, composite
├── demo/                # Standalone exported example, its source project and a simulated device
├── examples/tutorials/  # Projects built in the video tutorials (.uidp) and their data formats
├── docs/
│   ├── protocol.md      # Communication protocol reference
│   ├── uidp-format.md   # Project format guide, for writing projects by hand or with AI
│   ├── uidp-widgets.md  # Every property of every widget, generated from the widget definitions
│   └── release-notes/   # Release notes for each version
├── images/              # README images
├── tools/               # check_uidp.py checks a project; uidp_reference.py regenerates the widget reference and list
└── tests/               # Unit and smoke tests
```

## Built with

- [PyQt5](https://www.riverbankcomputing.com/software/pyqt/): GUI framework
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets): Fluent Design widget library
- [pyqtgraph](https://github.com/pyqtgraph/pyqtgraph): fast live charts
- [pyserial](https://github.com/pyserial/pyserial): serial communication
- [paho-mqtt](https://github.com/eclipse-paho/paho.mqtt.python): MQTT client
- [truststore](https://github.com/sethmlarson/truststore): verifies HTTPS and MQTT TLS connections with the operating system's certificate store
- [Nuitka](https://nuitka.net/): compiles and packages Python into a Windows exe / macOS `.app`

## Feedback and contributing

Bug reports and feature requests are welcome as [Issues](https://github.com/txp666/PyQt-UI-Designer/issues). Protocols such as UDP and Bluetooth are planned, and PRs are welcome too.

## License

This project is open source under the [GPLv3](LICENSE) license.
