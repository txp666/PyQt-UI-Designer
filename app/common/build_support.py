"""Shared Nuitka build helpers; intentionally independent of Qt."""
import os
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys

from app.core.i18n import tr


def safe_app_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name or name.lower() in {"main.build", "main.dist", "main.onefile-build"}:
        return "app"
    return name


def bundle_identifier(app_name: str) -> str:
    """An ASCII reverse-DNS identifier of an exported application's own, from its name."""
    digest = hashlib.sha1(app_name.encode("utf-8")).hexdigest()[:10]
    return f"io.github.txp666.pyqtuidesigner.app{digest}"


def build_nuitka_command(project_dir, python_cmd, app_name, version="1.0.0",
                         platform=None, bundle_id=None, description=None, company=None):
    """An exported application is named after itself (app_name, bundle_identifier); the designer's
    own build passes its identifier, description and company."""
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

    assets = project / "assets"
    if assets.is_dir():
        args.append(f"--include-data-dir={assets}=assets")

    icons = project / "app" / "resource" / "widget_icons"
    if icons.is_dir():  # the designer's palette icons
        args.append(f"--include-data-dir={icons}=app/resource/widget_icons")

    english = project / "app" / "resource" / "i18n" / "en.json"
    if english.is_file():  # the designer's English texts, also written into its exports
        args.append(f"--include-data-files={english}=app/resource/i18n/en.json")

    if (project / "app" / "core" / "serial_runtime.py").is_file():
        from app.common.runtime_sources import bundle_runtime_sources
        bundle = bundle_runtime_sources(project)
        args.append(f"--include-data-files={bundle}=runtime_sources.json")

    if platform == "win32":
        args += [
            "--windows-console-mode=disable",
            f"--windows-product-version={version}",
            f"--windows-file-version={version}",
            f"--windows-product-name={app_name}",
            f"--windows-file-description={description or app_name}",
        ]
        if company:
            args.append(f"--windows-company-name={company}")
        if (project / "logo.ico").is_file():
            args.append(f"--windows-icon-from-ico={project / 'logo.ico'}")
    elif platform == "darwin":
        args += [
            "--macos-create-app-bundle",
            f"--macos-app-name={app_name}",
            # Nuitka writes this as CFBundleIdentifier (and signs with it); without it the identifier is the name.
            f"--macos-signed-app-name={bundle_id or bundle_identifier(app_name)}",
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
        raise FileNotFoundError(tr("未找到本次编译产物: %1", source))

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

    # On macOS Nuitka also leaves an empty main.dist beside main.app.
    for name in ("main.build", "main.onefile-build", "main.dist"):
        shutil.rmtree(build_dir / name, ignore_errors=True)
    return final_dir, zip_path
