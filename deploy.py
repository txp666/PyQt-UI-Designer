# coding: utf-8
"""
Nuitka 打包脚本 —— PyQt UI Designer

使用方式：
  1. 激活虚拟环境
     $ conda activate YOUR_ENV_NAME   （或 .venv\\Scripts\\activate）
  2. 确保已安装 Nuitka
     $ pip install nuitka
  3. 在项目根目录执行
     $ python deploy.py

建议 Python 3.11–3.12 + MinGW64；Python 3.13+ 需 MSVC（不可用 --mingw64）。
MSVC + 系统代码页 936 时，Windows 元数据仅用 ASCII 以避免 C4819/C2001。
"""

import os
import subprocess
import sys
from pathlib import Path
from shutil import copy, copytree
try:
    from distutils.sysconfig import get_python_lib
except ModuleNotFoundError:
    import sysconfig
    def get_python_lib():
        return sysconfig.get_path("purelib")

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
from app.common.config import APP_VERSION

_VERSION_NUM = (
    APP_VERSION.lstrip("v")
    if isinstance(APP_VERSION, str) and APP_VERSION.startswith("v")
    else APP_VERSION
)

_icon = _ROOT / "logo.ico"
_build = _ROOT / "build"
_main = _ROOT / "main.py"

args = [
    sys.executable,
    "-m",
    "nuitka",
    "--standalone",
    "--assume-yes-for-downloads",
]

if sys.platform == "win32" and sys.version_info < (3, 13):
    args.append("--mingw64")

icon_args = []
if _icon.exists():
    icon_args.append(f"--windows-icon-from-ico={_icon}")

args.extend(
    icon_args
    + [
        "--enable-plugins=pyqt5",
        "--windows-console-mode=disable",
        '--windows-product-name=PyQt UI Designer',
        f"--windows-product-version={_VERSION_NUM}",
        f"--windows-file-version={_VERSION_NUM}",
        '--windows-file-description=PyQt UI Designer - HMI Application Builder',
        '--windows-company-name=PyQt-UI-Designer',
        "--show-progress",
        "--show-memory",
        f"--output-dir={_build}",
        str(_main),
    ]
)

dist_folder = _build

copied_site_packages = []

copied_standard_packages = []

# 执行 Nuitka 打包
_env = os.environ.copy()
_env["CL"] = ("/utf-8 " + _env.get("CL", "")).strip()
r = subprocess.run(args, cwd=str(_ROOT), env=_env)
if r.returncode != 0:
    sys.exit(r.returncode)

# 复制 site-packages 依赖到 dist 目录
site_packages = Path(get_python_lib())

for src in copied_site_packages:
    src = site_packages / src
    dist = dist_folder / src.name

    print(f"Copying site-packages `{src}` to `{dist}`")

    try:
        if src.is_file():
            copy(src, dist)
        else:
            copytree(src, dist)
    except Exception:
        pass

# 复制标准库文件
for file in copied_standard_packages:
    src = site_packages.parent / file
    dist = dist_folder / src.name

    print(f"Copying standard library `{src}` to `{dist}`")

    try:
        if src.is_file():
            copy(src, dist)
        else:
            copytree(src, dist)
    except Exception:
        pass
