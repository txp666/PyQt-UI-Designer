# coding: utf-8
"""Check for new releases from GitHub repository."""
import json
import re
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from PyQt5.QtCore import QThread, pyqtSignal

GITHUB_REPO = "txp666/PyQt-UI-Designer"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"


def _parse_version(v: str) -> tuple:
    """'v0.2.1' or '0.2.1' -> (0, 2, 1)"""
    nums = re.findall(r"\d+", v)
    return tuple(int(n) for n in nums) if nums else (0,)


class UpdateCheckThread(QThread):
    """Background thread to query GitHub release API.

    Signals:
        result(has_new: bool, latest_ver: str, current_ver: str,
               release_url: str, changelog: str, error: str)
    """
    result = pyqtSignal(bool, str, str, str, str, str)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self._current = current_version

    def run(self):
        try:
            req = Request(API_URL, headers={"Accept": "application/vnd.github.v3+json"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            tag = data.get("tag_name", "")
            body = data.get("body", "") or ""
            html_url = data.get("html_url", RELEASE_URL)

            latest = _parse_version(tag)
            current = _parse_version(self._current)
            has_new = latest > current

            self.result.emit(has_new, tag, self._current, html_url, body, "")
        except HTTPError as e:
            if e.code == 404:
                self.result.emit(False, "", self._current, "", "", "")
            else:
                self.result.emit(False, "", self._current, "", "",
                                 f"服务器错误: HTTP {e.code}")
        except URLError as e:
            self.result.emit(False, "", self._current, "", "", f"网络错误: {e.reason}")
        except Exception as e:
            self.result.emit(False, "", self._current, "", "", f"检查失败: {e}")
