"""Exercise real native windows; run on a logged-in macOS/Windows desktop."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt5.QtCore import QEvent, QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import Theme, qconfig, setTheme
from app.core.code_generator import generate_project
from app.core.project import ProjectData
from app.core.theme_runtime import ThemeController
from app.core.widget_registry import registry
from app.view.main_window import MainWindow
from app.view.preview_interface import NuitkaPackDialog

app = QApplication([])
theme_controller = ThemeController(app, qconfig.get(qconfig.themeMode))
window = MainWindow()
app.processEvents()
assert not window.windowIcon().isNull()
if sys.platform == "darwin":
    assert not window.setting_interface.micaCard.isEnabled()
python_cmd, ready = NuitkaPackDialog._find_python()
assert python_cmd and ready, (python_cmd, ready)

with tempfile.TemporaryDirectory() as folder:
    dialog = NuitkaPackDialog(folder, "构建环境验证")
    loop = QEventLoop()
    selected_python = []
    dialog._install_nuitka_then_pack = lambda cmd: (selected_python.extend(cmd), loop.quit())
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    try:
        dialog._prepare_build_environment([sys.executable])
        # A loaded runner can take longer to install pip into the fresh venv.
        # Finish on the actual process result, with a bounded failure deadline.
        dialog._pip_process.finished.connect(loop.quit)
        dialog._pip_process.errorOccurred.connect(loop.quit)
        deadline.start(120000)
        loop.exec()
        assert selected_python and Path(selected_python[0]).is_file(), (
            "Build venv did not finish successfully",
            dialog._terminal.toPlainText(),
        )
        prefix = subprocess.check_output(
            selected_python + ["-c", "import sys; print(sys.prefix)"],
            text=True, timeout=30,
        ).strip()
        assert Path(prefix).resolve() == (Path(folder) / ".build-venv").resolve()
    finally:
        deadline.stop()
        # Stop owned processes before TemporaryDirectory removes their files.
        dialog.close()

project = ProjectData()
for index, meta in enumerate(registry.all()):
    project.widgets.append({
        "id": f"widget_{index}", "type": meta.type_name,
        "properties": meta.get_default_props(),
        "geometry": {"x": 20 + (index % 4) * 280, "y": 20 + (index // 4) * 180,
                     "w": 260, "h": 160},
    })

window.preview_interface.set_project_data(project)
window.preview_interface._start_preview()
app.processEvents()
(ROOT / "build").mkdir(exist_ok=True)
for theme in (Theme.DARK, Theme.LIGHT):
    setTheme(theme, save=False)
    app.processEvents()
    assert not window.grab().isNull()
window.grab().save(str(ROOT / "build" / "macos-smoke.png"))
window.preview_interface._stop_preview()

with tempfile.TemporaryDirectory() as folder:
    generate_project(project, folder)
    for source in Path(folder).glob("*.py"):
        compile(source.read_text(encoding="utf-8"), str(source), "exec")
    subprocess.run([sys.executable, "-c", """
import runpy
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme
original_exec = QApplication.exec
def smoke_exec(self):
    QTimer.singleShot(100, lambda: setTheme(Theme.DARK, save=False))
    QTimer.singleShot(350, lambda: setTheme(Theme.LIGHT, save=False))
    QTimer.singleShot(700, self.quit)
    return original_exec()
QApplication.exec = smoke_exec
runpy.run_path('main.py', run_name='__main__')
"""], cwd=folder, check=True, timeout=30)

QTimer.singleShot(300, app.quit)
app.exec()
window.deleteLater()
theme_controller.deleteLater()
app.sendPostedEvents(None, QEvent.DeferredDelete)
print(f"NATIVE_GUI_EXPORT_OK: {len(project.widgets)} widget types, Python {sys.version.split()[0]}")
