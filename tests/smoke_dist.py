"""Validate the archive that will be published, then launch its bundled runtime."""
import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time
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

        env = os.environ.copy()
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX",
                    "QT_PLUGIN_PATH", "QT_QPA_PLATFORM"):
            env.pop(key, None)
        process = subprocess.Popen(
            [str(binary)], cwd=folder, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            time.sleep(5)
            if process.poll() is not None:
                raise RuntimeError(process.communicate()[0].decode("utf-8", errors="replace"))
        finally:
            if process.poll() is None:
                process.terminate()
            output = process.communicate(timeout=15)[0].decode("utf-8", errors="replace")
        assert "Traceback" not in output, output
    print(f"PACKAGED_APP_OK: {archive.name} ({archive.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
