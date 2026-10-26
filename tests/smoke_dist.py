"""Validate the archive that will be published, then launch its bundled runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--version")
    options = parser.parse_args()
    archive = options.archive.resolve()
    checksum = archive.with_suffix(".zip.sha256")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    expected = checksum.read_text(encoding="utf-8").strip()
    assert expected == f"{digest.hexdigest()}  {archive.name}", "Checksum mismatch"

    with tempfile.TemporaryDirectory(prefix="uidesigner-release-") as folder:
        if sys.platform == "darwin":
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), folder], check=True)
            bundles = list(Path(folder).glob("*.app"))
            assert len(bundles) == 1, bundles
            bundle = bundles[0]
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)],
                           check=True)
            info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
            if options.version:
                assert info["CFBundleShortVersionString"] == options.version, info
            assert info["NSHighResolutionCapable"]
            root = bundle / "Contents/MacOS"
            binary = root / info["CFBundleExecutable"]
        else:
            with zipfile.ZipFile(archive) as zipped:
                assert zipped.testzip() is None, "Corrupt archive"
                zipped.extractall(folder)
            binaries = list(Path(folder).glob("*/main.exe"))
            assert len(binaries) == 1, binaries
            binary = binaries[0]
            root = binary.parent
        assert binary.is_file()
        assert (root / "logo.png").is_file(), "Missing runtime icon"

        repository = Path(__file__).resolve().parents[1]
        fixture = Path(folder) / "demo"
        shutil.copytree(repository / "demo", fixture,
                        ignore=shutil.ignore_patterns("__pycache__", ".venv", "build"))
        diagnostics = repository / "build"
        diagnostics.mkdir(exist_ok=True)
        report_path = diagnostics / f"{archive.stem}-smoke.json"
        report_path.unlink(missing_ok=True)
        env = os.environ.copy()
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX",
                    "QT_PLUGIN_PATH", "QT_QPA_PLATFORM"):
            env.pop(key, None)
        process = subprocess.Popen(
            [str(binary), "--smoke-test-project", str(fixture / "project.uidp"),
             "--smoke-test-report", str(report_path)], cwd=folder, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            output = process.communicate(timeout=90)[0].decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            process.kill()
            output = process.communicate(timeout=15)[0].decode("utf-8", errors="replace")
            (diagnostics / f"{archive.stem}-smoke.log").write_text(output, encoding="utf-8")
            raise AssertionError(f"Packaged application did not finish its lifecycle test: {output}")
        report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
        (diagnostics / f"{archive.stem}-smoke.log").write_text(
            output + "\n" + report_text, encoding="utf-8")
        assert process.returncode == 0, f"Packaged application exited {process.returncode}:\n{output}\n{report_text}"
        assert report_text, f"Packaged application did not produce its lifecycle report:\n{output}"
        report = json.loads(report_text)
        assert report["status"] == "passed" and not report["errors"], report
        assert report["compiled_runtime"], "Lifecycle checks did not run inside the compiled application"
        if options.version:
            assert report["version"] == options.version, report
        if "-arm64" in archive.stem:
            assert report["architecture"].lower() in ("arm64", "aarch64"), report
        elif "-x64" in archive.stem:
            assert report["architecture"].lower() in ("x86_64", "amd64"), report
        assert report["cycles"] == 6 and report["preview_cycles"] == 7, report
        assert len(report["widget_types"]) == report["widget_count"] == 29, report
        assert report["exception_count"] == 0, report
        assert report["selected_widget"] == "all_Label", report
        assert "destroyed_selected_scene" in report["steps"], report
        assert report["cancelled_update_check"] and "cancelled_update_check" in report["steps"], report
        assert report["exported"] and "destroyed_window_signals" in report["steps"], report
        assert report["tcp_loopback"] and "tcp_loopback_exchange" in report["steps"], report
        assert not any(text in output for text in (
            "Traceback", "wrapped C/C++ object", "has been deleted", "Exception ignored",
        )), output
    print(f"PACKAGED_APP_OK: {archive.name} ({archive.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
