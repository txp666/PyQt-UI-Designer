"""The 发现新版本 dialog keeps its buttons on screen however long the release notes are."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QWidget

from app.view.update_dialog import UpdateDialog

app = QApplication.instance() or QApplication([])


class UpdateDialogTests(unittest.TestCase):
    def test_long_notes_scroll_and_buttons_stay_inside_the_window(self):
        window = QWidget()
        window.resize(1000, 700)
        window.show()
        self.addCleanup(window.close)
        notes = "**不兼容变更**：第一段。\n\n" + "\n".join(f"- 第 {i} 条：" + "很长的说明 " * 30 for i in range(60))
        dialog = UpdateDialog("v9.9.9", "0.2.1", notes, window)
        dialog.show()
        app.processEvents()
        self.assertLessEqual(dialog.widget.height(), window.height())
        self.assertLessEqual(dialog.notes.height(), int(window.height() * 0.45))
        self.assertGreater(dialog.notes.verticalScrollBar().maximum(), 0, "long notes should scroll")
        self.assertTrue(dialog.yesButton.isVisible() and dialog.cancelButton.isVisible())
        self.assertLessEqual(dialog.buttonGroup.geometry().bottom(), dialog.widget.height())
        self.assertEqual((dialog.yesButton.text(), dialog.cancelButton.text()), ("前往下载", "稍后再说"))
        # Markdown is rendered, not shown raw.
        self.assertNotIn("**", dialog.notes.toPlainText())
        self.assertIn("不兼容变更", dialog.notes.toPlainText())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
