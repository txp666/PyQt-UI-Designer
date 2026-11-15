"""Build the pinned native Snap7 library for this Python's platform/architecture."""
import argparse
import pathlib
import platform
import shutil
import subprocess
import sys


COMMIT = "30f37da3114024a71ba93f7fd855c680b97a406f"


def build(root):
    root = pathlib.Path(root).resolve()
    upstream = root / "third_party" / "snap7"
    revision = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if revision != COMMIT:
        raise RuntimeError("Snap7 submodule must be pinned to " + COMMIT)
    work = root / "build" / "snap7-native"
    source = work / "source"
    shutil.rmtree(source, ignore_errors=True)
    source.mkdir(parents=True)
    shutil.copytree(upstream / "src", source / "src")
    patches = (["snap7-macos.patch"] if sys.platform == "darwin" else []) + ["snap7-connect-timeout.patch"]
    for name in patches:
        subprocess.run(["git", "apply", "--unsafe-paths", "--directory=" + str(source),
                        str(root / "patches" / name)], cwd=root, check=True)
    arguments = ["cmake", "-S", str(root / "native"), "-B", str(work / "build"), "-G", "Ninja",
                 "-DCMAKE_BUILD_TYPE=Release", "-DSNAP7_SOURCE_ROOT=" + str(source)]
    if sys.platform == "darwin":
        arguments += ["-DCMAKE_OSX_ARCHITECTURES=" + platform.machine(), "-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0"]
    subprocess.run(arguments, check=True)
    subprocess.run(["cmake", "--build", str(work / "build"), "--parallel", "4"], check=True)
    name = "snap7.dll" if sys.platform == "win32" else "libsnap7.dylib" if sys.platform == "darwin" else "libsnap7.so"
    destination = root / "app" / "resource" / "native"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(work / "build" / "lib" / name, destination / name)
    for name in ("lgpl-3.0.txt", "gpl.txt"):
        shutil.copy2(upstream / name, destination / name)
    (destination / "SOURCE.txt").write_text(
        "Snap7 https://github.com/davenardella/snap7\nCommit: " + COMMIT
        + "\nLGPL-3.0-or-later. Build-copy patches: " + ", ".join(patches) + "\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=pathlib.Path(__file__).resolve().parents[1])
    print(build(parser.parse_args().project_root))
