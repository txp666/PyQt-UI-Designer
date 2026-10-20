# coding: utf-8
"""Build the designer on the target OS: .app on macOS, .exe on Windows."""
import argparse
from pathlib import Path
import subprocess
import sys

from app.common.build_support import (
    archive_build, build_environment, build_nuitka_command,
)
from app.common.metadata import APP_NAME, APP_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=APP_VERSION, help="Bundle version")
    parser.add_argument("--archive-name", default=APP_NAME, help="Output name")
    options = parser.parse_args()
    root = Path(__file__).resolve().parent
    result = subprocess.run(
        build_nuitka_command(root, [sys.executable], APP_NAME, options.version),
        cwd=str(root), env=build_environment(),
    )
    if result.returncode:
        return result.returncode
    bundle, archive = archive_build(root, options.archive_name)
    print(f"Application: {bundle}\nArchive: {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
