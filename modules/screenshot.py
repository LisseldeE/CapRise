from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QDialog, QFileDialog, QApplication
)
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QPixmap, QGuiApplication, QFont, QPalette
from modules.overlay import BaseOverlay, pixel_source, draw_snapshot
from modules.i18n import I18n
from datetime import datetime


def _selection_color():
    """Return border color for selection rect based on theme.
    Dark mode → light gray, Light mode → dark gray."""
    bg = QApplication.palette().color(QPalette.Window)
    is_dark = bg.lightness() < 128
    return QColor(200, 200, 200) if is_dark else QColor(80, 80, 80)


class ScreenshotOverlay(BaseOverlay):
    """Screenshot overlay with region selection"""
    image_captured = Signal(object)

    def __init__(self, parent=None):
        # Capture desktop before creating overlay
        self.desktop_pixmap = QGuiApplication.primaryScreen().grabWindow(0)
        self.start_point = None
        self.end_point = None
        self.is_dragging = False
        super().__init__(parent)
        self.setCursor(Qt.CrossCursor)  # precise crosshair while framing
        self.activateWindow()
        self.setFocus()  # Ensure ESC key works

    def paintEvent(self, event):
        painter = QPainter(self)
        # Dark overlay
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))

        if self.start_point and self.end_point and self.is_dragging:
            sel_rect = QRect(self.start_point, self.end_point).normalized()

            # Cut out the selection area - show desktop content. Painted 1:1
            # from the grab's physical pixels so HiDPI scaling never makes
            # the text inside wobble while dragging.
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            draw_snapshot(painter, self.desktop_pixmap, sel_rect)

            # Draw selection border (theme-aware color, no corner handles)
            border_color = _selection_color()
            painter.setPen(QPen(border_color, 2))
            painter.setBrush(QColor(0, 0, 0, 0))
            painter.drawRect(sel_rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_point = event.position().toPoint()
            self.end_point = self.start_point
            self.is_dragging = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            self.end_point = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_dragging:
            self.is_dragging = False
            sel_rect = QRect(self.start_point, self.end_point).normalized()

            if sel_rect.width() > 5 and sel_rect.height() > 5:
                captured = self.desktop_pixmap.copy(
                    pixel_source(self.desktop_pixmap, sel_rect))
                # Emit closed signal before closing (so CapRise clears active_overlay)
                self.closed.emit()
                # Close overlay first
                self.close()
                self.deleteLater()
                # Show preview as modal
                preview = ScreenshotPreview(captured)
                preview.exec()
            else:
                # Selection too small, cancel
                self.close_overlay()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_overlay()
        super().keyPressEvent(event)


class ScreenshotPreview(QDialog):
    """Preview window for captured screenshot"""

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.pixmap = pixmap
        self.setWindowTitle(I18n.tr("screenshot_preview"))
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint
        )
        self.setModal(True)
        self.setup_ui()
        self.center_on_screen()

    def setup_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: palette(window);
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # Image display
        screen_geo = QGuiApplication.primaryScreen().availableGeometry()
        max_w = int(screen_geo.width() * 0.6)
        max_h = int(screen_geo.height() * 0.6)

        scaled = self.pixmap.scaled(
            max_w, max_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        self.image_label = QLabel()
        self.image_label.setPixmap(scaled)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("""
            QLabel {
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 4px;
                background-color: palette(base);
            }
        """)
        layout.addWidget(self.image_label)

        # Info text
        info = QLabel(f"{self.pixmap.width()} x {self.pixmap.height()} px")
        info.setAlignment(Qt.AlignCenter)
        info.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        layout.addWidget(info)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        self.btn_copy = QPushButton(I18n.tr("copy"))
        self.btn_copy.setFixedSize(100, 34)
        self.btn_copy.setStyleSheet("""
            QPushButton {
                border: 1px solid palette(mid);
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: palette(light);
            }
            QPushButton:pressed {
                padding-top: 7px;
                padding-bottom: 5px;
            }
        """)
        self.btn_copy.clicked.connect(self.copy_image)
        btn_layout.addWidget(self.btn_copy)

        self.btn_save = QPushButton(I18n.tr("save"))
        self.btn_save.setFixedSize(100, 34)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #339af0;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #228be6;
            }
            QPushButton:pressed {
                padding-top: 7px;
                padding-bottom: 5px;
            }
        """)
        self.btn_save.clicked.connect(self.save_image)
        btn_layout.addWidget(self.btn_save)

        layout.addLayout(btn_layout)

        # Adjust dialog size
        img_w = scaled.width() + 48
        img_h = scaled.height() + 120
        self.setFixedSize(max(300, min(img_w, max_w + 48)),
                          max(200, min(img_h, max_h + 120)))

    def center_on_screen(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2
        )

    def save_image(self):
        default_name = f"{I18n.tr('screenshot')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, I18n.tr("save_as"), default_name,
            f"{I18n.tr('png_files')} (*.png)"
        )
        if path:
            self.pixmap.save(path, "PNG")
            self.accept()

    def copy_image(self):
        QApplication.clipboard().setPixmap(self.pixmap)
        self.accept()