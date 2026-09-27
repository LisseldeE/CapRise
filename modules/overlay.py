"""
覆盖层基类
全屏覆盖层基类与 HiDPI 像素绘制辅助
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QPainter, QColor, QGuiApplication


def pixel_source(pixmap, dip_rect):
    """Map a Qt device-independent (logical) rect into a screen-grab pixmap's
    PIXEL coordinates.

    `QPixmap.copy()` and `QPainter.drawPixmap` interpret their source rect in
    the pixmap's device (pixel) coordinates. But all mouse coordinates and the
    overlay geometry are in Qt logical units. On HiDPI displays the grab from
    `QScreen.grabWindow` has `devicePixelRatio() > 1` (e.g. 1.25 at 125%
    scaling), so a logical rect must be scaled up by the DPR — otherwise the
    boxed content is read from a too-small, shifted pixel region and renders
    enlarged and offset. `round()` (rather than `int()`) keeps the boundary
    centred instead of always truncating toward zero."""
    dpr = pixmap.devicePixelRatio() or 1.0
    return QRect(
        round(dip_rect.x() * dpr), round(dip_rect.y() * dpr),
        round(dip_rect.width() * dpr), round(dip_rect.height() * dpr),
    )


def draw_snapshot(painter, pixmap, dip_rect):
    """Draw a 1:1 pixel-exact slice of a HiDPI screen grab into a logical rect.

    A logical rect times the pixmap's DPR is usually non-integer (e.g. 62.5 px
    at 125%). Painting the grab from a separately rounded source rect makes Qt
    scale by a non-1 factor and, while the user drags the selection, the
    truncated source step is uneven (1 or 2 physical px per logical px), so
    text inside the selection visibly wobbles up/down.

    Fix: round both the destination and the source to the SAME physical-pixel
    rect and paint in physical-pixel space. Source == destination, so the map
    is exactly 1:1 — no sub-pixel scaling, and the content advances one
    physical pixel at a time."""
    dpr = pixmap.devicePixelRatio() or 1.0
    phys = QRect(
        round(dip_rect.x() * dpr), round(dip_rect.y() * dpr),
        round(dip_rect.width() * dpr), round(dip_rect.height() * dpr),
    )
    painter.save()
    painter.scale(1.0 / dpr, 1.0 / dpr)
    painter.drawPixmap(phys, pixmap, phys)
    painter.restore()


class BaseOverlay(QWidget):
    """Full-screen dark overlay base class"""
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        # Cover all monitors
        virtual_geo = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(virtual_geo)
        self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_overlay()
        super().keyPressEvent(event)

    def close_overlay(self):
        self.closed.emit()
        self.close()
        self.deleteLater()