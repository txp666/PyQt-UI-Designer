# coding: utf-8
"""Preview interface — build and run the designed UI in a live window."""
from functools import partial
from pathlib import Path
from copy import deepcopy
import sys

from PyQt5.QtCore import Qt, QProcess, QTimer, QUrl, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QDialog, QFileDialog, QSizePolicy,
)
from PyQt5.QtWidgets import QAbstractSpinBox, QLineEdit, QAbstractButton, QTabBar, QTabWidget
from PyQt5.QtGui import QFontDatabase, QTextCursor, QColor, QDesktopServices
from qfluentwidgets import (
    PrimaryPushButton, PushButton, BodyLabel, InfoBar,
    InfoBarPosition, FluentIcon as FIF, CardWidget, isDarkTheme,
    SwitchButton, StrongBodyLabel, CaptionLabel, TextEdit,
    ProgressBar,
)

from app.common.signal_bus import signalBus
from app.common.build_support import archive_build, build_environment, build_nuitka_command
from app.widgets.basic import create_widget
from app.core.project import ProjectData
from app.core.data_binding import bindingEngine
from app.core.signal_lifetime import SignalConnections
from app.core.slider_release import SendOnRelease
from app.core.command_runtime import (
    command_hex_frame, command_packed_frame, send_modbus_command,
)


class PreviewCanvas(QWidget):
    """The actual preview surface that renders widgets at their designed positions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewCanvas")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._widgets = []
        self._asset_base_dir = None
        self._update_style()

    def _update_style(self):
        if isDarkTheme():
            self.setStyleSheet("QWidget#previewCanvas { background: #2b2b2b; border: 1px solid #444; }")
        else:
            self.setStyleSheet("QWidget#previewCanvas { background: white; border: 1px solid #ddd; }")

    def build_from_project(self, project: ProjectData):
        self.clear()
        from app.core.comm_manager import commHub
        commHub.disconnect()
        commHub.configure(project.serial)
        self._update_style()
        self.setFixedSize(project.canvas_width, project.canvas_height)
        self._asset_base_dir = (Path(project.file_path).expanduser().resolve().parent
                                if project.file_path else Path.cwd())

        for wd in project.widgets:
            self._create_widget_recursive(wd, self)

    def _create_widget_recursive(self, wd: dict, parent_widget: QWidget):
        type_name = wd["type"]
        props = wd.get("properties", {})
        if type_name == "ImageDisplay":
            from app.widgets.display import resolved_image_properties
            props = resolved_image_properties(props, self._asset_base_dir)
        geo = wd.get("geometry", {})

        try:
            actual_parent = parent_widget
            if isinstance(parent_widget, QTabWidget):
                from app.widgets.layout import clamp_tab_index
                tab_idx = clamp_tab_index(wd.get("tabIndex", 0), parent_widget.count())
                page = parent_widget.widget(tab_idx)
                if page:
                    actual_parent = page

            widget = create_widget(type_name, props, actual_parent)
            self._enable_interaction(widget)
            geometry = (
                int(geo.get("x", 0)), int(geo.get("y", 0)),
                int(geo.get("w", 120)), int(geo.get("h", 40)),
            )
            if isinstance(parent_widget, QTabWidget):
                from app.core.tab_geometry import place_tab_child
                place_tab_child(parent_widget, widget, *geometry)
            else:
                widget.setGeometry(*geometry)
            widget.show()
            self._widgets.append(widget)

            widget_id = wd.get("id")
            if widget_id:
                bindingEngine.register_widget(widget_id, widget)

            self._wire_commands(widget, type_name, props)

            if type_name == "RealtimeChart" and hasattr(widget, "start_listening"):
                widget.start_listening()

            if props.get("notify"):
                self._wire_notification(widget, type_name, props)

            for child_data in wd.get("children", []):
                self._create_widget_recursive(child_data, widget)
        except (ValueError, KeyError):
            pass

    @staticmethod
    def _enable_interaction(widget: QWidget):
        widget.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        widget.setFocusPolicy(Qt.StrongFocus)
        for child in widget.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            if isinstance(child, (QAbstractSpinBox, QLineEdit, QAbstractButton, QTabBar)):
                child.setFocusPolicy(Qt.StrongFocus)

    _NEWLINE_MAP = {"无": "", "\\r\\n": "\r\n", "\\n": "\n", "\\r": "\r"}
    _FC_MAP = {
        "01 读线圈": 0x01, "02 读离散输入": 0x02,
        "03 读保持寄存器": 0x03, "04 读输入寄存器": 0x04,
        "05 写单线圈": 0x05, "06 写单寄存器": 0x06,
    }

    @staticmethod
    def _command_error(error):
        signalBus.showNotification.emit("提示", str(error), "错误", 2000)

    @staticmethod
    def _send_modbus_frame(props: dict, value: int = None):
        """Send a Modbus request from widget properties over every connected link, framed
        for each link (RTU, or MBAP where the link parses Modbus TCP).
        If value is provided, it overrides mbValue from props."""
        from app.core.comm_manager import commHub
        if not commHub.is_connected:
            signalBus.showNotification.emit("提示", "未连接，命令未发送", "警告", 2000)
            return
        try:
            send_modbus_command(
                commHub,
                props.get("mbSlave", 1),
                PreviewCanvas._FC_MAP.get(props.get("mbFunc", "06 写单寄存器"), 0x06),
                props.get("mbAddress", 0),
                value if value is not None else props.get("mbValue", 1),
            )
        except ValueError as exc:
            PreviewCanvas._command_error(exc)

    @staticmethod
    def _send_serial_bytes(raw: bytes):
        from app.core.comm_manager import commHub
        if not commHub.is_connected:
            signalBus.showNotification.emit("提示", "未连接，命令未发送", "警告", 2000)
            return
        commHub.send(raw)

    @staticmethod
    def _send_command(cmd: str, mode: str, newline: str, props: dict):
        from app.core.comm_manager import commHub
        if not commHub.is_connected:
            signalBus.showNotification.emit("提示", "未连接，命令未发送", "警告", 2000)
            return

        if mode == "Modbus":
            PreviewCanvas._send_modbus_frame(props, cmd)
            return
        elif mode == "HEX":
            try:
                frame = command_hex_frame(
                    cmd, props.get("frameHeader", ""), props.get("frameTail", ""))
            except ValueError as exc:
                PreviewCanvas._command_error(exc)
                return
            commHub.send(frame)
        else:
            suffix = PreviewCanvas._NEWLINE_MAP.get(newline, "\r\n")
            commHub.send_text(cmd + suffix)

    _STRUCT_FMT = {
        "uint8": ("B", int), "int8": ("b", int),
        "uint16": ("H", int), "int16": ("h", int),
        "uint32": ("I", int), "int32": ("i", int),
        "float32": ("f", float),
    }

    @staticmethod
    def _apply_template(tpl: str, value: str, mode: str, newline: str, props: dict):
        """Apply template and send via the appropriate mode.

        For HEX mode with a struct data type, packs the value as binary first,
        then applies the template to the hex representation.
        """
        if mode == "Modbus":
            PreviewCanvas._send_modbus_frame(props, value)
            return
        if mode == "HEX":
            dt = props.get("dataType", "HEX字符串")
            fmt_info = PreviewCanvas._STRUCT_FMT.get(dt)
            if fmt_info:
                fmt_char, cast = fmt_info
                bo = ">" if props.get("byteOrder", "大端(BE)") == "大端(BE)" else "<"
                try:
                    frame = command_packed_frame(
                        value, bo + fmt_char, cast, tpl,
                        props.get("frameHeader", ""), props.get("frameTail", ""))
                except ValueError as exc:
                    PreviewCanvas._command_error(exc)
                    return
                PreviewCanvas._send_serial_bytes(frame)
                return

        cmd = tpl.replace("{value}", value) if "{value}" in tpl else tpl
        PreviewCanvas._send_command(cmd, mode, newline, props)

    @staticmethod
    def _wire_commands(widget: QWidget, type_name: str, props: dict):
        """Connect command properties to sending over the communication hub."""
        mode = props.get("commandMode", "文本")
        newline = props.get("commandNewline", "\\r\\n")
        tpl = props.get("commandTemplate", "{value}")

        if type_name == "PushButton":
            cmd = props.get("command", "").strip()
            if mode == "Modbus":
                settings = {"mbFunc": "03 读保持寄存器", **props}
                widget.clicked.connect(
                    lambda _, p=settings: PreviewCanvas._send_modbus_frame(p))
            elif cmd:
                widget.clicked.connect(
                    lambda _, c=cmd, m=mode, n=newline, p=props, t=tpl:
                        PreviewCanvas._apply_template(t, c, m, n, p))

        elif type_name == "ToggleSwitch":
            on_cmd = props.get("onCommand", "").strip()
            off_cmd = props.get("offCommand", "").strip()
            if on_cmd or off_cmd or mode == "Modbus":
                sw = widget.findChild(SwitchButton)
                if sw:
                    def _on_toggle(checked, _on=on_cmd, _off=off_cmd,
                                   _m=mode, _n=newline, _p=props, _t=tpl):
                        if _m == "Modbus":
                            val = 0xFF00 if checked else 0x0000
                            PreviewCanvas._send_modbus_frame(
                                {**_p, "mbFunc": "05 写单线圈"}, val)
                        else:
                            c = _on if checked else _off
                            if c:
                                PreviewCanvas._apply_template(_t, c, _m, _n, _p)
                    sw.checkedChanged.connect(_on_toggle)

        elif type_name == "LineEdit" and (props.get("sendOnEnter") or mode == "Modbus"):
            def _on_enter(_w=widget, _m=mode, _n=newline, _p=props, _t=tpl):
                text = _w.text().strip()
                if text or _m == "Modbus":
                    PreviewCanvas._apply_template(_t, text, _m, _n, _p)
            widget.returnPressed.connect(_on_enter)

        elif type_name == "ComboBox" and (props.get("sendOnSelect") or mode == "Modbus"):
            cmd_lines = [s.strip() for s in
                         props.get("commands", "").split("\n")]

            def _on_select(idx, _w=widget, _m=mode, _n=newline,
                           _p=props, _cmds=cmd_lines, _t=tpl):
                if idx < 0:
                    return
                raw = _cmds[idx] if idx < len(_cmds) and _cmds[idx] else _w.currentText()
                if raw:
                    PreviewCanvas._apply_template(_t, raw, _m, _n, _p)
            widget.currentIndexChanged.connect(_on_select)

        elif type_name in ("Slider", "SpinBox") and (props.get("sendOnChange") or mode == "Modbus"):
            def _on_value_changed(val, _tpl=tpl, _m=mode, _n=newline, _p=props):
                PreviewCanvas._apply_template(_tpl, str(val), _m, _n, _p)
            if type_name == "Slider":  # a drag sends once, when it lets go
                SendOnRelease(widget, _on_value_changed)
            else:
                widget.valueChanged.connect(_on_value_changed)

    @staticmethod
    def _wire_notification(widget: QWidget, type_name: str, props: dict):
        title = props.get("notifyTitle", "提示")
        content = props.get("notifyContent", "")
        ntype = props.get("notifyType", "信息")
        duration = int(props.get("notifyDuration", 3000))
        emit = partial(signalBus.showNotification.emit,
                       title, content, ntype, duration)

        if type_name == "PushButton":
            widget.clicked.connect(emit)
        elif type_name == "ToggleSwitch":
            sw = widget.findChild(SwitchButton)
            if sw:
                sw.checkedChanged.connect(lambda _: emit())

    def clear(self):
        for w in self._widgets:
            if hasattr(w, "stop_listening"):
                w.stop_listening()
            w.deleteLater()
        self._widgets.clear()


class NuitkaPackDialog(QDialog):
    """Dialog that runs Nuitka packaging with real-time terminal output."""

    def __init__(self, project_dir: str, app_name: str = "上位机", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuitka 打包")
        self.resize(800, 560)
        self.setMinimumSize(640, 400)
        self._project_dir = project_dir
        self._app_name = app_name
        self._process = None
        self._pip_process = None
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        hdr = QHBoxLayout()
        self._title = StrongBodyLabel("Nuitka 打包")
        self._status = CaptionLabel("就绪")
        self._status.setStyleSheet("color:#888;")
        hdr.addWidget(self._title)
        hdr.addStretch()
        hdr.addWidget(self._status)
        root.addLayout(hdr)

        self._progress = ProgressBar()
        self._progress.setRange(0, 0)
        self._progress.hide()
        root.addWidget(self._progress)

        self._terminal = TextEdit()
        self._terminal.setReadOnly(True)
        self._terminal.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self._terminal.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #cccccc; "
            "border: 1px solid #333; border-radius: 6px; padding: 8px; }"
        )
        root.addWidget(self._terminal, 1)

        btn_row = QHBoxLayout()
        self._start_btn = PrimaryPushButton("开始打包")
        self._start_btn.clicked.connect(self._start_pack)
        self._cancel_btn = PushButton("取消")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._open_dir_btn = PushButton("打开输出目录")
        self._open_dir_btn.clicked.connect(self._open_output_dir)
        self._open_dir_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._open_dir_btn)
        root.addLayout(btn_row)

    def _append_text(self, text: str, color: str = None):
        cursor = self._terminal.textCursor()
        cursor.movePosition(QTextCursor.End)
        if color:
            fmt = cursor.charFormat()
            fmt.setForeground(QColor(color))
            cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self._terminal.setTextCursor(cursor)
        self._terminal.ensureCursorVisible()

    @staticmethod
    def _find_python(project_dir=None) -> tuple:
        """Find Python 3.10+ with build dependencies, including Finder launches."""
        import sys
        import os
        import shutil
        import subprocess
        from pathlib import Path

        CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
        _kw = dict(stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)

        def _py_ver(cmd: list) -> bool:
            try:
                out = subprocess.check_output(
                    cmd + ["-c", "import sys; print(sys.version_info.major, sys.version_info.minor)"], timeout=5, **_kw
                ).decode().strip()
                major, minor = map(int, out.split())
                return major == 3 and minor >= 10
            except Exception:
                return False

        def _has_nuitka(cmd: list) -> bool:
            try:
                subprocess.check_output(
                    cmd + ["-c", "import nuitka, ordered_set, PyQt5, qfluentwidgets, serial, pyqtgraph, paho.mqtt, truststore"
                           + (", imageio, PIL" if sys.platform == "darwin" else "")],
                    timeout=15, **_kw
                )
                return True
            except Exception:
                return False

        all_candidates = []

        if not getattr(sys, "frozen", False) and "__compiled__" not in globals():
            all_candidates.append([sys.executable])

        venv_dirs = []
        if project_dir:
            venv_dirs.extend(Path(project_dir) / name for name in (".build-venv", ".venv"))
        for base in (Path.home(), Path(os.environ.get("USERPROFILE", ""))):
            for name in (".venv", "venv", ".conda"):
                d = base / name
                if d.exists():
                    venv_dirs.append(d)
        for env_var in ("VIRTUAL_ENV", "CONDA_PREFIX"):
            v = os.environ.get(env_var)
            if v:
                venv_dirs.append(Path(v))
        for vd in venv_dirs:
            for sub in ("Scripts/python.exe", "bin/python", "python.exe"):
                exe = vd / sub
                if exe.exists():
                    all_candidates.append([str(exe)])

        for name in [["python3"], ["python"], ["python3.14"], ["python3.13"], ["python3.12"], ["python3.11"], ["python3.10"]]:
            if shutil.which(name[0]):
                all_candidates.append(name)
        if sys.platform == "win32":
            for name in [["py", "-3"], ["py", "-3.12"]]:
                if shutil.which(name[0]):
                    all_candidates.append(name)

        if sys.platform == "darwin":
            for prefix in (Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
                for name in ("python3", "python3.14", "python3.13", "python3.12"):
                    if (prefix / name).is_file():
                        all_candidates.append([str(prefix / name)])

        first_valid_py = None
        for cmd in all_candidates:
            if _py_ver(cmd):
                if _has_nuitka(cmd):
                    return cmd, True
                if first_valid_py is None:
                    first_valid_py = cmd

        if first_valid_py:
            return first_valid_py, False

        return [], False

    def _build_nuitka_args(self) -> list:
        return build_nuitka_command(
            self._project_dir, self._python_cmd, self._app_name,
        )

    def _start_pack(self):
        from pathlib import Path

        main_py = Path(self._project_dir) / "main.py"
        if not main_py.exists():
            self._append_text("错误: 找不到 main.py，请先导出代码\n", "#f44")
            return

        self._start_btn.setEnabled(False)
        self._open_dir_btn.setEnabled(False)
        self._progress.show()
        self._terminal.clear()
        self._status.setText("正在查找 Python 环境...")
        self._status.setStyleSheet("color:#0078d4;")

        py_cmd, has_nuitka = self._find_python(self._project_dir)

        if not py_cmd:
            self._append_text(
                "错误: 未找到 Python 3.10 或更新版本\n\n"
                "请安装 Python 3.10+ 并确保已加入系统 PATH。\n",
                "#f44",
            )
            self._start_btn.setEnabled(True)
            self._progress.hide()
            self._status.setText("未找到 Python")
            self._status.setStyleSheet("color:#f44;")
            return

        self._python_cmd = py_cmd
        py_display = " ".join(py_cmd)

        if not has_nuitka:
            self._append_text(
                f"检测到 Python: {py_display}\n"
                f"打包依赖不完整，正在安装...\n\n", "#dcdcaa"
            )
            self._status.setText("正在安装打包依赖...")
            self._prepare_build_environment(py_cmd)
            return

        self._append_text(f"Python: {py_display}\n", "#6a9955")
        self._do_pack()

    def _prepare_build_environment(self, py_cmd: list):
        """Homebrew Python is externally managed: install only in a build venv."""
        from pathlib import Path
        venv = Path(self._project_dir).resolve() / ".build-venv"
        self._build_python = venv / ("Scripts/python.exe" if sys.platform == "win32"
                                     else "bin/python")
        self._append_text(f"创建打包虚拟环境: {venv}\n", "#569cd6")
        self._pip_process = QProcess(self)
        self._pip_process.setProcessEnvironment(self._to_qenv(build_environment()))
        self._pip_process.setProcessChannelMode(QProcess.MergedChannels)
        self._pip_process.readyReadStandardOutput.connect(
            lambda: self._append_text(
                bytes(self._pip_process.readAllStandardOutput()).decode("utf-8", errors="replace")
            )
        )
        self._pip_process.errorOccurred.connect(self._on_process_error)
        self._pip_process.finished.connect(self._on_venv_finished)
        args = list(py_cmd) + ["-m", "venv", str(venv)]
        self._pip_process.start(args[0], args[1:])

    def _on_venv_finished(self, exit_code, status):
        if exit_code != 0 or status != QProcess.NormalExit:
            self._progress.hide()
            self._start_btn.setEnabled(True)
            self._status.setText("虚拟环境创建失败")
            self._append_text("请检查 Python venv 支持和输出目录写入权限。\n", "#f44")
            return
        self._python_cmd = [str(self._build_python)]
        self._install_nuitka_then_pack(self._python_cmd)

    def _install_nuitka_then_pack(self, py_cmd: list):
        import os
        pip_args = list(py_cmd) + [
            "-m", "pip", "install",
            "nuitka>=4.0.7", "ordered-set",
            "PyQt5", "PyQt-Fluent-Widgets", "pyserial", "paho-mqtt", "truststore", "pyqtgraph",
        ]
        if sys.platform == "darwin":
            pip_args.extend(["imageio", "Pillow"])
        self._append_text(f"$ {' '.join(pip_args)}\n\n", "#569cd6")

        self._pip_process = QProcess(self)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        self._pip_process.setProcessEnvironment(self._to_qenv(env))
        self._pip_process.readyReadStandardOutput.connect(
            lambda: self._append_text(
                bytes(self._pip_process.readAllStandardOutput()).decode("utf-8", errors="replace")
            )
        )
        self._pip_process.readyReadStandardError.connect(
            lambda: self._append_text(
                bytes(self._pip_process.readAllStandardError()).decode("utf-8", errors="replace"),
                "#f44",
            )
        )
        self._pip_process.finished.connect(self._on_pip_finished)
        self._pip_process.errorOccurred.connect(self._on_process_error)
        self._pip_process.start(pip_args[0], pip_args[1:])

    def _on_pip_finished(self, exit_code, status):
        if exit_code != 0 or status != QProcess.NormalExit:
            self._append_text(
                f"\nNuitka 安装失败 (exit code: {exit_code})\n"
                "请检查网络和日志中的依赖安装错误。\n", "#f44"
            )
            self._start_btn.setEnabled(True)
            self._progress.hide()
            self._status.setText("Nuitka 安装失败")
            self._status.setStyleSheet("color:#f44;")
            return

        self._append_text("\n✓ Nuitka 安装成功，开始打包...\n\n", "#4ec9b0")
        self._do_pack()

    def _do_pack(self):
        self._status.setText("打包中...")
        self._status.setStyleSheet("color:#0078d4;")

        args = self._build_nuitka_args()
        self._append_text(f"$ {' '.join(args)}\n\n", "#569cd6")

        env = build_environment()

        self._process = QProcess(self)
        self._process.setWorkingDirectory(self._project_dir)
        self._process.setProcessEnvironment(self._to_qenv(env))
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_process_error)
        self._process.start(args[0], args[1:])

    @staticmethod
    def _to_qenv(env: dict):
        from PyQt5.QtCore import QProcessEnvironment
        qenv = QProcessEnvironment()
        for k, v in env.items():
            qenv.insert(k, v)
        return qenv

    def _on_stdout(self):
        data = self._process.readAllStandardOutput()
        text = bytes(data).decode("utf-8", errors="replace")
        self._append_text(text)

    def _on_stderr(self):
        data = self._process.readAllStandardError()
        text = bytes(data).decode("utf-8", errors="replace")
        self._append_text(text, "#e8a838")

    def _on_finished(self, exit_code, status):
        self._progress.hide()
        self._start_btn.setEnabled(True)
        if exit_code == 0 and status == QProcess.NormalExit:
            self._append_text("\n✓ Nuitka 编译成功!\n", "#2ecc71")
            self._post_build_cleanup()
        else:
            self._status.setText(f"打包失败 (exit {exit_code})")
            self._status.setStyleSheet("color:#e74c3c;")
            self._append_text(f"\n✗ 打包失败, exit code: {exit_code}\n", "#e74c3c")

    def _post_build_cleanup(self):
        try:
            bundle, archive = archive_build(self._project_dir, self._app_name)
        except Exception as error:
            self._append_text(f"产物整理失败: {error}\n", "#e74c3c")
            self._status.setText("打包失败")
            self._status.setStyleSheet("color:#e74c3c;")
            return
        size_mb = archive.stat().st_size / (1024 * 1024)
        self._append_text(f"✓ {bundle.name}\n✓ {archive.name} ({size_mb:.1f} MB)\n", "#2ecc71")
        self._status.setText("打包完成")
        self._status.setStyleSheet("color:#2ecc71;")
        self._open_dir_btn.setEnabled(True)

    def _on_process_error(self, error):
        if error == QProcess.FailedToStart:
            self._progress.hide()
            self._start_btn.setEnabled(True)
            self._status.setText("进程启动失败")
            self._append_text("无法启动 Python，请检查解释器路径和执行权限。\n", "#f44")

    def _on_cancel(self):
        running = False
        for process in (self._pip_process, self._process):
            if process and process.state() != QProcess.NotRunning:
                running = True
                process.kill()
                process.waitForFinished(3000)
        if running:
            self._append_text("\n用户取消打包\n", "#f39c12")
            self._status.setText("已取消")
            self._status.setStyleSheet("color:#f39c12;")
        else:
            self.close()

    def _open_output_dir(self):
        from pathlib import Path
        build_dir = Path(self._project_dir).resolve() / "build"
        if not build_dir.exists():
            self._append_text("输出目录不存在\n", "#f44")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(build_dir))):
            self._append_text("无法打开输出目录\n", "#f44")

    def closeEvent(self, event):
        for process in (self._pip_process, self._process):
            if process and process.state() != QProcess.NotRunning:
                process.kill()
                process.waitForFinished(3000)
        super().closeEvent(event)


class PreviewInterface(QWidget):
    """Preview page with start/stop controls and the preview canvas."""

    projectDataRequested = pyqtSignal()

    _NOTIFY_TYPE_MAP = {
        "成功": "success", "信息": "info", "警告": "warning", "错误": "error",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewInterface")
        self._project_data = None
        self._running = False
        self._init_ui()
        self._external_connections = SignalConnections(self)
        self._external_connections.connect(
            signalBus.showNotification, self._show_notification)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # controls
        ctrl_layout = QHBoxLayout()
        self._run_btn = PrimaryPushButton(FIF.PLAY, "运行预览")
        self._stop_btn = PushButton(FIF.CLOSE, "停止")
        self._stop_btn.setEnabled(False)
        self._status_label = BodyLabel("未运行")

        self._run_btn.clicked.connect(self._start_preview)
        self._stop_btn.clicked.connect(self._stop_preview)

        self._pack_btn = PushButton(FIF.ZIP_FOLDER, "一键打包")
        self._pack_btn.clicked.connect(self._on_pack)

        ctrl_layout.addWidget(self._run_btn)
        ctrl_layout.addWidget(self._stop_btn)
        ctrl_layout.addWidget(self._status_label)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(self._pack_btn)
        layout.addLayout(ctrl_layout)

        # scroll area for canvas
        scroll = self._scroll = QScrollArea()
        scroll.setObjectName("previewScroll")
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)

        self._preview_canvas = PreviewCanvas()
        scroll.setWidget(self._preview_canvas)
        layout.addWidget(scroll, 1)

        self._placeholder = BodyLabel("在设计器中设计界面后，点击「运行预览」查看效果")
        self._placeholder.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._placeholder)
        self.on_theme_changed()

    def set_project_data(self, data: ProjectData):
        # ProjectManager reuses and mutates its ProjectData during export/save.
        # Keep the running design independent so same-object edits are detected.
        if self._running and (
            self._project_data is None
            or self._project_data.to_dict() != data.to_dict()
            or self._project_data.file_path != data.file_path
        ):
            self._stop_preview()
            self._status_label.setText("设计已更改，请重新运行预览")
        self._project_data = deepcopy(data)

    def invalidate_project(self, message="已停止", disconnect=False):
        """Retire a running design before its commands can target another project."""
        if self._running or disconnect:
            self._stop_preview()
        self._project_data = None
        self._status_label.setText(message)

    def _show_notification(self, title: str, content: str,
                           ntype: str, duration: int):
        if not self._running:
            return
        method_name = self._NOTIFY_TYPE_MAP.get(ntype, "info")
        method = getattr(InfoBar, method_name, InfoBar.info)
        method(
            title=title,
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=duration,
            parent=self,
        )

    def _start_preview(self):
        self.projectDataRequested.emit()
        if not self._project_data or not self._project_data.widgets:
            InfoBar.warning(
                "提示", "当前没有可预览的控件，请先在设计器中添加控件",
                parent=self, position=InfoBarPosition.TOP, duration=3000,
            )
            return

        bindingEngine.stop()
        bindingEngine.clear()

        self._preview_canvas.build_from_project(self._project_data)

        bindingEngine.load_bindings_from_project(self._project_data.widgets)
        bindingEngine.start()

        self._preview_canvas.setEnabled(True)
        self._placeholder.hide()
        self._running = True
        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status_label.setText("● 运行中")
        signalBus.previewStarted.emit()

    def _stop_preview(self):
        bindingEngine.stop()
        bindingEngine.clear()

        self._preview_canvas.setEnabled(False)
        from app.core.comm_manager import commHub
        commHub.disconnect()
        self._preview_canvas.clear()
        self._placeholder.show()
        self._running = False
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_label.setText("已停止")
        signalBus.previewStopped.emit()

    def _on_pack(self):
        self.projectDataRequested.emit()
        if not self._project_data or not self._project_data.widgets:
            InfoBar.warning(
                "提示", "当前没有可打包的控件，请先在设计器中添加控件",
                parent=self, position=InfoBarPosition.TOP, duration=3000,
            )
            return

        directory = QFileDialog.getExistingDirectory(self, "选择打包输出目录")
        if not directory:
            return

        try:
            from app.core.code_generator import generate_project
            generate_project(self._project_data, directory)
        except Exception as e:
            InfoBar.error(
                "导出失败", str(e),
                parent=self, position=InfoBarPosition.TOP, duration=5000,
            )
            return

        app_name = self._project_data.app_name if self._project_data else "上位机"
        dlg = NuitkaPackDialog(directory, app_name, self)
        dlg.exec_()

    def on_theme_changed(self):
        self._preview_canvas._update_style()
        background = "#202020" if isDarkTheme() else "#f5f5f5"
        self._scroll.setStyleSheet(
            f"QScrollArea#previewScroll {{ background: {background}; border: none; }}")
