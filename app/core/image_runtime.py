"""Image display shared by the designer, the preview and exported applications."""
import math

from PyQt5.QtCore import Qt, QPointF, QRectF, QSize
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QTransform
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import CaptionLabel, isDarkTheme, qconfig

from .signal_lifetime import SignalConnections
from .i18n import tr

SCALE_FIT, SCALE_STRETCH, SCALE_ORIGINAL = "适应", "拉伸", "原始大小"  # i18n: value
SCALE_MODES = (SCALE_FIT, SCALE_STRETCH, SCALE_ORIGINAL)


def image_transform(box_w, box_h, img_w, img_h, rotation, mirror_h, mirror_v, scale_mode) -> QTransform:
    """Where an img_w x img_h picture goes in a box_w x box_h widget: picture pixel coordinates to widget
    coordinates. Mirrored in its own frame, the picture turns ``rotation`` degrees clockwise about the box
    centre and is scaled so that all of it stays inside the box, which never changes: SCALE_FIT as large as
    fits, SCALE_STRETCH from the box's size (swapped near a quarter turn, so it still fills the box),
    SCALE_ORIGINAL at its pixel size, or smaller when that does not fit."""
    theta = int(rotation) % 360
    if theta % 90 == 0:  # exact for quarter turns
        cos, sin = ((1, 0), (0, 1), (-1, 0), (0, -1))[theta // 90]
    else:
        cos, sin = math.cos(math.radians(theta)), math.sin(math.radians(theta))
    c, n = abs(cos), abs(sin)
    if scale_mode == SCALE_STRETCH:
        bw, bh = (box_h, box_w) if 45 < theta % 180 < 135 else (box_w, box_h)
    else:
        bw, bh = img_w, img_h
    k = min(box_w / (bw * c + bh * n), box_h / (bw * n + bh * c))  # fits the turned rect's bounding box
    if scale_mode == SCALE_ORIGINAL:
        k = min(1.0, k)
    sx = (-k if mirror_h else k) * bw / img_w
    sy = (-k if mirror_v else k) * bh / img_h
    # Qt applies the last step first: centre the picture on the origin, scale and mirror it, then turn it
    # clockwise on screen and move it to the box centre.
    transform = QTransform(cos, sin, -sin, cos, box_w / 2, box_h / 2)
    transform.scale(sx, sy)
    transform.translate(-img_w / 2, -img_h / 2)
    return transform


class ImageDisplay(QWidget):
    """A static picture placed by image_transform, or a placeholder card when there is none."""

    # Each .uidp property, the setter that applies it and its default.
    PROPERTY_SETTERS = (
        ("imagePath", "set_image_path", ""),
        ("scaleMode", "set_scale_mode", SCALE_FIT),
        ("rotation", "set_rotation", 0),
        ("mirrorH", "set_mirror_h", False),
        ("mirrorV", "set_mirror_v", False),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._image = QImage()
        self._scale_mode = SCALE_FIT
        self._rotation = 0
        self._mirror_h = False
        self._mirror_v = False
        self._placeholder = CaptionLabel(tr("未选择图片"), self)
        self._placeholder.setTextColor(QColor("#606060"), QColor("#b3b3b3"))
        self._placeholder.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._placeholder, 0, Qt.AlignCenter)
        self._theme_connections = SignalConnections(self)
        self._theme_connections.connect(qconfig.themeChangedFinished, self.update)

    def set_image_path(self, path):
        self._path = path
        self._image = QImage(path) if path else QImage()
        self._placeholder.setText(tr("无法加载图片") if path else tr("未选择图片"))
        self._placeholder.setVisible(self._image.isNull())
        self.update()

    def set_scale_mode(self, mode):
        self._scale_mode = mode
        self.update()

    def set_rotation(self, degrees):
        self._rotation = int(degrees)
        self.update()

    def set_mirror_h(self, on):
        self._mirror_h = bool(on)
        self.update()

    def set_mirror_v(self, on):
        self._mirror_v = bool(on)
        self.update()

    def sizeHint(self):
        return QSize(200, 150)

    def minimumSizeHint(self):
        return QSize(1, 1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._image.isNull():
            dark = isDarkTheme()
            painter.setPen(QPen(QColor("#606060" if dark else "#c8c8c8"), 1, Qt.DashLine))
            painter.setBrush(QColor("#292929" if dark else "#f5f5f5"))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            return
        if self.width() <= 0 or self.height() <= 0:
            return
        # Drawn from the original picture through the transform, so it stays sharp on a 2x screen and zoomed.
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setTransform(image_transform(
            self.width(), self.height(), self._image.width(), self._image.height(),
            self._rotation, self._mirror_h, self._mirror_v, self._scale_mode))
        painter.drawImage(QPointF(0, 0), self._image)
