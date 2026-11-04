# coding: utf-8
"""The new-version dialog: release notes in a scrolling box, so the buttons stay on screen."""
from PyQt5.QtCore import QSize, Qt
from qfluentwidgets import BodyLabel, MessageBoxBase, SubtitleLabel, TextBrowser

from app.core.i18n import language, tr

ENGLISH_HEADING = "## English"


def localized_notes(notes, english):
    """The part of bilingual release notes in the interface language: Chinese comes first, then a
    ``## English`` line and the English notes. Notes without that line are shown whole."""
    lines = notes.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == ENGLISH_HEADING:
            return "\n".join(lines[index + 1:] if english else lines[:index])
    return notes


class UpdateDialog(MessageBoxBase):
    """Asks whether to open the download page for ``latest``.

    The release notes are rendered as Markdown inside a read-only box of fixed height (about
    45 % of the parent window, 160–440 px), so however long they are the dialog never grows past
    the window and its two buttons stay visible. ``exec()`` returns True for the download button.
    Only the part of bilingual notes in the interface language is shown (localized_notes).
    """

    def __init__(self, latest, current, changelog, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(tr("发现新版本"), self.widget)
        self.versionLabel = BodyLabel(tr("最新版本 %1 · 当前 v%2", latest, current), self.widget)
        self.notes = TextBrowser(self.widget)
        self.notes.setReadOnly(True)
        self.notes.setOpenExternalLinks(True)
        notes = localized_notes(changelog or "", language() == "en_US").strip()
        self.notes.setMarkdown(notes or tr("（这个版本没有更新说明）"))
        self.notes.setFocusPolicy(Qt.NoFocus)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.versionLabel)
        self.viewLayout.addWidget(self.notes, 1)
        self.yesButton.setText(tr("前往下载"))
        self.cancelButton.setText(tr("稍后再说"))

        available = parent.size() if parent is not None and parent.width() > 0 else QSize(1000, 700)
        self.widget.setFixedWidth(max(360, min(680, available.width() - 80)))
        self.notes.setFixedHeight(max(160, min(440, int(available.height() * 0.45))))
