"""Shared Nuitka build helpers; intentionally independent of Qt."""
import os
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys


def safe_app_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name or name.lower() in {"main.build", "main.dist", "main.onefile-build"}:
        return "app"
    return name


def build_nuitka_command(project_dir, python_cmd, app_name, version="1.0.0",
                         platform=None):
    platform = platform or sys.platform
    project = Path(project_dir).resolve()
    args = list(python_cmd) + [
        "-m", "nuitka", "--standalone", "--assume-yes-for-downloads",
        "--enable-plugins=pyqt5", "--show-progress",
        f"--output-dir={project / 'build'}",
    ]
    for name in ("logo.png", "logo.ico", "logo.icns"):
        resource = project / name
        if resource.is_file():
            args.append(f"--include-data-files={resource}={name}")

    if platform == "win32":
        args += [
            "--windows-console-mode=disable",
            f"--windows-product-version={version}",
            f"--windows-file-version={version}",
            "--windows-product-name=PyQt UI Designer",
            "--windows-file-description=PyQt UI Designer - HMI Application Builder",
            "--windows-company-name=PyQt-UI-Designer",
        ]
        if (project / "logo.ico").is_file():
            args.append(f"--windows-icon-from-ico={project / 'logo.ico'}")
    elif platform == "darwin":
        args += [
            "--macos-create-app-bundle",
            f"--macos-app-name={app_name}",
            f"--macos-app-version={version}",
        ]
        for name in ("logo.icns", "logo.png"):
            if (project / name).is_file():
                args.append(f"--macos-app-icon={project / name}")
                break

    args.append(str(project / "main.py"))
    return args


def build_environment():
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if sys.platform == "win32":
        env["CL"] = ("/utf-8 " + env.get("CL", "")).strip()
    return env


def archive_build(project_dir, app_name, platform=None):
    """Package the current build, preserving macOS bundle links and permissions."""
    platform = platform or sys.platform
    build_dir = Path(project_dir).resolve() / "build"
    source = build_dir / ("main.app" if platform == "darwin" else "main.dist")
    if not source.is_dir():
        raise FileNotFoundError(f"未找到本次编译产物: {source}")

    name = safe_app_name(app_name)
    final_dir = build_dir / (f"{name}.app" if platform == "darwin" else name)
    if source != final_dir:
        if final_dir.exists():
            shutil.rmtree(final_dir)
        source.rename(final_dir)

    zip_path = build_dir / f"{name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    if platform == "darwin":
        subprocess.run(
            ["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
             str(final_dir), str(zip_path)],
            check=True,
        )
    else:
        shutil.make_archive(str(zip_path.with_suffix("")), "zip",
                            root_dir=str(build_dir), base_dir=final_dir.name)

    digest = hashlib.sha256()
    with zip_path.open("rb") as archive:
        for chunk in iter(lambda: archive.read(1024 * 1024), b""):
            digest.update(chunk)
    zip_path.with_suffix(".zip.sha256").write_text(
        f"{digest.hexdigest()}  {zip_path.name}\n", encoding="utf-8",
    )

    for name in ("main.build", "main.onefile-build"):
        shutil.rmtree(build_dir / name, ignore_errors=True)
    return final_dir, zip_path
