# coding: utf-8
"""The "发现新版本" dialog: release notes in a scrolling box, so the buttons stay on screen."""
from PyQt5.QtCore import QSize, Qt
from qfluentwidgets import BodyLabel, MessageBoxBase, SubtitleLabel, TextBrowser


class UpdateDialog(MessageBoxBase):
    """Asks whether to open the download page for ``latest``.

    The release notes are rendered as Markdown inside a read-only box of fixed height (about
    45 % of the parent window, 160–440 px), so however long they are the dialog never grows past
    the window and 前往下载 / 稍后再说 stay visible. ``exec()`` returns True for 前往下载.
    """

    def __init__(self, latest, current, changelog, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("发现新版本", self.widget)
        self.versionLabel = BodyLabel(f"最新版本 {latest} · 当前 v{current}", self.widget)
        self.notes = TextBrowser(self.widget)
        self.notes.setReadOnly(True)
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown((changelog or "").strip() or "（这个版本没有发布说明）")
        self.notes.setFocusPolicy(Qt.NoFocus)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.versionLabel)
        self.viewLayout.addWidget(self.notes, 1)
        self.yesButton.setText("前往下载")
        self.cancelButton.setText("稍后再说")

        available = parent.size() if parent is not None and parent.width() > 0 else QSize(1000, 700)
        self.widget.setFixedWidth(max(360, min(680, available.width() - 80)))
        self.notes.setFixedHeight(max(160, min(440, int(available.height() * 0.45))))
