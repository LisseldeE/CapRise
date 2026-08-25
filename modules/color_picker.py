"""Full-screen eyedropper color picker.

Launched from the capsule: it hides the capsule, freezes a desktop snapshot,
and covers the screen with a picker overlay. A draggable glass card shows the
color under the cursor in real time (HEX / RGB / HSL) and offers one-click
copy. Left-click samples the hovered pixel (copies its HEX and stays in the
mode for continuous sampling); right-click or ESC exits and restores the
capsule.
"""
from PySide6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QApplication
)
from PySide6.QtCore import Qt, QTimer, QPoint, Signal
from PySide6.QtGui import (
    QPainter, QColor, QPixmap, QGuiApplication, QFont
)
from modules.overlay import BaseOverlay
from modules.widgets import GlassIconButton, paint_pill
from modules.icons import ICON_COPY, ICON_CHECK
from modules.i18n import I18n


class _ColorCard(QWidget):
    """Draggable glass card showing the live HEX / RGB / HSL of the hovered
    pixel, with a one-click copy of the hex value. Position is free to drag
    and is intentionally not persisted."""

    copy_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor(255, 255, 255)
        self._dragging = False
        self._drag_offset = QPoint(0, 0)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(256)
        self._build_ui()
        self.set_color(self._color)

        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move((geo.width() - self.width()) // 2 + geo.x(), geo.y() + 28)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.swatch = QLabel()
        self.swatch.setFixedSize(40, 40)
        self.swatch.setAlignment(Qt.AlignCenter)
        top.addWidget(self.swatch)

        col = QVBoxLayout()
        col.setSpacing(1)
        self.hex_lbl = QLabel()
        self.hex_lbl.setFont(QFont("Consolas", 15, QFont.Bold))
        col.addWidget(self.hex_lbl)
        top.addLayout(col, 1)

        self.copy_btn = GlassIconButton(
            ICON_COPY, I18n.tr("copy"), size=32, icon_size=16,
            colorize_icon=True)
        self.copy_btn.clicked.connect(
            lambda checked=False: self.copy_clicked.emit())
        top.addWidget(self.copy_btn, 0, Qt.AlignTop)
        root.addLayout(top)

        self.rgb_lbl = QLabel()
        self.rgb_lbl.setFont(QFont("Consolas", 10))
        self.rgb_lbl.setStyleSheet("color: rgba(160,160,160,230);")
        root.addWidget(self.rgb_lbl)

        self.hsl_lbl = QLabel()
        self.hsl_lbl.setFont(QFont("Consolas", 10))
        self.hsl_lbl.setStyleSheet("color: rgba(160,160,160,230);")
        root.addWidget(self.hsl_lbl)

        hint = QLabel(I18n.tr("picker_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgba(160,160,160,180); font-size: 11px;")
        root.addWidget(hint)

        self.adjustSize()

    def set_color(self, c):
        self._color = QColor(c)
        self.hex_lbl.setText(self._color.name().upper())
        self.rgb_lbl.setText(
            f"RGB  {self._color.red():3d}  {self._color.green():3d}  "
            f"{self._color.blue():3d}")
        h = self._color.hue()
        h = h if h >= 0 else 0
        s = int(round(self._color.saturation() / 255 * 100))
        v = int(round(self._color.value() / 255 * 100))
        self.hsl_lbl.setText(f"HSL  {h:3d}\u00b0  {s:3d}%  {v:3d}%")
        self.swatch.setStyleSheet(
            f"background: {self._color.name()}; border-radius: 8px;"
            " border: 1px solid rgba(128,128,128,150);")

    def show_copied(self):
        """Flash the copy button into a checkmark as copied feedback, then
        revert it to the copy icon — no extra row, so nothing gets pushed."""
        self.copy_btn.set_svg(ICON_CHECK)
        if not hasattr(self, "_copied_timer"):
            self._copied_timer = QTimer(self)
            self._copied_timer.setSingleShot(True)
            self._copied_timer.timeout.connect(
                lambda: self.copy_btn.set_svg(ICON_COPY))
        self._copied_timer.start(900)

    def paintEvent(self, event):
        painter = QPainter(self)
        paint_pill(painter, self.rect(), 14)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class ColorPickerOverlay(BaseOverlay):
    """Covers the frozen desktop and samples the pixel under the cursor."""

    def __init__(self, parent=None):
        # Freeze the desktop BEFORE the overlay is shown so what the user
        # sees under the crosshair is exactly what the eyedropper reads.
        self.desktop_pixmap = QGuiApplication.primaryScreen().grabWindow(0)
        self.desktop_image = self.desktop_pixmap.toImage()
        self._dpr = self.desktop_pixmap.devicePixelRatio() or 1.0
        self._hover = QColor(255, 255, 255)
        super().__init__(parent)
        # Keep the system-default arrow cursor (the snapshot + card are the
        # only visual feedback; a custom cursor was requested to be dropped).
        self.card = _ColorCard(self)
        self.card.copy_clicked.connect(self._copy_current)
        # The overlay is already shown (via BaseOverlay.__init__); a child
        # created afterwards stays hidden unless show() is called.
        self.card.show()

        self.activateWindow()
        self.setFocus()

    # ----- pixel readout -----

    def _sample_at(self, pos):
        """Read the pixel colour at a logical overlay position and push it
        to the card. Called on click only (not on hover)."""
        x = int(round(pos.x() * self._dpr))
        y = int(round(pos.y() * self._dpr))
        if 0 <= x < self.desktop_image.width() \
                and 0 <= y < self.desktop_image.height():
            self._hover = QColor(self.desktop_image.pixelColor(x, y))
        else:
            self._hover = QColor(255, 255, 255)
        self.card.set_color(self._hover)

    def _copy_current(self, *args):
        QApplication.clipboard().setText(self._hover.name().upper())
        self.card.show_copied()

    # ----- painting / events -----

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        # Show the frozen snapshot 1:1 as the background so the eyedropper's
        # readout always matches what the user sees on screen. drawPixmap at
        # the origin renders the DPR-scaled grab at its logical size.
        painter.drawPixmap(0, 0, self.desktop_pixmap)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.close_overlay()  # right-click exits the picker
            return
        if event.button() == Qt.LeftButton:
            # Sample the colour at the exact click position (not on hover);
            # copying happens only via the copy button.
            self._sample_at(event.position())
        BaseOverlay.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event):
        BaseOverlay.mouseReleaseEvent(self, event)

    def keyPressEvent(self, event):
        # ESC exits the picker (handled by BaseOverlay).
        super().keyPressEvent(event)