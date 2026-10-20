"""Source resources for exporting the same runtimes used by the designer."""
import json
from pathlib import Path

RUNTIME_FILES = ("theme_runtime.py", "protocol_parser.py", "serial_runtime.py",
                 "chart_history.py", "chart_runtime.py", "serial_card.py",
                 "binding_values.py", "command_runtime.py", "tab_geometry.py")
ROOT = Path(__file__).resolve().parents[2]


def runtime_source(name):
    if name not in RUNTIME_FILES:
        raise ValueError(name)
    if "__compiled__" not in globals():
        return (ROOT / "app" / "core" / name).read_text(encoding="utf-8")
    return json.loads((ROOT / "runtime_sources.json").read_text(encoding="utf-8"))[name]


def bundle_runtime_sources(project):
    """Keep source available after Nuitka removes the original Python files."""
    project = Path(project)
    source_dir = project / "app" / "core"
    bundle = project / "build" / "runtime_sources.json"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(json.dumps({
        name: (source_dir / name).read_text(encoding="utf-8") for name in RUNTIME_FILES
    }, ensure_ascii=False), encoding="utf-8")
    return bundle
