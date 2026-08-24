"""Floating clipboard history card (glassmorphism).

A frameless Qt.Tool window that floats above other windows. Shows the
clipboard history list with per-item copy/delete, a clear-all button, a
connection-status line, and is draggable by its header. It is registered
as a "family window" so interacting with it does NOT make the capsule收起.

Position: appears near the cursor on first show (clamped to screen), then
persists across drags (emitted via `position_changed`).
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QApplication, QSizePolicy
)
from PySide6.QtCore import (
    Qt, Signal, QPoint, QSize, QPropertyAnimation, QEasingCurve, QTimer,
    QEvent
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QPalette, QCursor, QGuiApplication, QMouseEvent,
    QWheelEvent
)

from modules.icons import ICON_CLIPBOARD, ICON_COPY, ICON_TRASH, ICON_MINUS
from modules.i18n import I18n
from modules.family import FamilyWindowRegistry


def _make_text_icon(svg, color, size=16):
    """Tiny helper kept local — the capsule has its own _make_icon.

    Rasterised on a devicePixelRatio-scaled buffer so it stays crisp on
    scaled-Windows (HiDPI) displays."""
    from PySide6.QtCore import QByteArray, QRectF
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtGui import QPixmap, QIcon, QGuiApplication
    colored = svg.replace('stroke="currentColor"', f'stroke="{color}"')
    renderer = QSvgRenderer(QByteArray(colored.encode()))
    dpr = QGuiApplication.primaryScreen().devicePixelRatio() or 1.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return QIcon(pm)


def _system_color(role):
    c = QApplication.palette().color(role)
    return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"


# Pixel height of one item row + its spacing. Kept in sync with
# ClipboardItemWidget.setFixedHeight(56) + list_layout.setSpacing(4) = 60.
# Used by SmoothScrollArea to scroll one item per wheel notch instead of
# the default viewport-height page step (which feels like "page flipping").
_ITEM_ROW_H = 60


class SmoothScrollArea(QScrollArea):
    """QScrollArea whose mouse-wheel scroll is per-item AND animated.

    The default QScrollArea wheel behavior scrolls by pageStep (~viewport
    height ≈ 6 items per notch) with no animation — that feels like "page
    flipping" and is visually jarring. We override wheelEvent so each wheel
    notch advances one item row (60px) via a QPropertyAnimation (250ms
    OutCubic), giving the "fixed-height panel, smooth per-item scroll" UX.

    Consecutive wheel notches accumulate: if a second notch arrives mid-
    animation, we stop the current animation and start a new one from the
    current scroll value to the new target — no jumps, no lost deltas.

    Keyboard / scrollbar-button navigation uses the same single-item step
    via setSingleStep in _init_ui."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scroll_anim = QPropertyAnimation(self.verticalScrollBar(), b"value")
        self._scroll_anim.setDuration(250)
        self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)
        # Pending target in pixels. Wheel notches that arrive mid-animation
        # accumulate here, so a fast scroll-wheel flick still travels the
        # full intended distance.
        self._pending_target = None

    def wheelEvent(self, event: QWheelEvent):
        # angleDelta.y() returns eighths of a degree; one wheel notch = 120.
        # Many mice/touchpads deliver smaller deltas — preserve sub-notch
        # precision by scaling proportionally instead of flooring.
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            return super().wheelEvent(event)
        # Each 120-unit notch = one item row. Sub-notch deltas scale linearly.
        steps = delta_y / 120 * _ITEM_ROW_H
        sb = self.verticalScrollBar()
        # Determine the starting value for the new animation:
        #   - If an animation is running, continue from its target so the
        #     user feels accumulation, not a sudden snap-back to the
        #     animation's current pixel position.
        #   - Otherwise start from the current scroll value.
        if self._scroll_anim.state() == QPropertyAnimation.Running and \
                self._pending_target is not None:
            base = self._pending_target
        else:
            base = sb.value()
        # Negative delta scrolls down (toward newer items at bottom of
        # history); we want wheel-down to move the view DOWN, so subtract.
        target = base - steps
        # Clamp to valid range; QScrollBar clamps too, but pre-clamping
        # here means the animation doesn't try to animate past the ends.
        target = max(sb.minimum(), min(sb.maximum(), target))
        self._pending_target = target
        # Restart the animation from the current value to the new target.
        # QPropertyAnimation.stop() is safe mid-run; the new startValue is
        # the actual current scroll position, so there's no visual jump.
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(sb.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.start()
        event.accept()

    def viewportEvent(self, event):
        # Let the base class do its scroll-bar range update first…
        result = super().viewportEvent(event)
        # …then force our per-item steps back. QAbstractScrollArea resets
        # pageStep to viewport height inside its viewportEvent handler; we
        # undo that so PageUp/PageDown also advances one item row.
        sb = self.verticalScrollBar()
        if sb.singleStep() != _ITEM_ROW_H:
            sb.setSingleStep(_ITEM_ROW_H)
        if sb.pageStep() != _ITEM_ROW_H:
            sb.setPageStep(_ITEM_ROW_H)
        return result


class ClipboardItemWidget(QWidget):
    """A single history row: click to copy, hover-delete button."""

    copy_requested = Signal(str)       # content
    delete_requested = Signal(int)     # item id

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self._content = item["content"]
        self._id = item["id"]
        self.setFixedHeight(56)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        is_local = item.get("source", "local") == "local"
        dot_color = "#339af0" if is_local else "#37b24d"

        # Elided preview (single line) + full content on tooltip
        preview = self._content.replace("\n", " ").replace("\r", " ").strip()
        if len(preview) > 90:
            preview = preview[:89] + "…"

        self.setStyleSheet(f"""
            ClipboardItemWidget {{
                background-color: transparent;
                border: none;
                border-radius: 8px;
            }}
            ClipboardItemWidget:hover {{
                background-color: rgba(51, 154, 240, 38);
            }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8)
        lay.setSpacing(10)

        # Source dot
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"background-color: {dot_color}; border-radius: 4px; border: none;"
        )
        lay.addWidget(dot)

        text = QLabel(preview)
        text.setToolTip(self._content)
        text.setStyleSheet("color: palette(text); border: none; background: transparent; font-size: 13px;")
        text.setWordWrap(False)
        text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(text, 1)

        del_btn = QPushButton()
        del_btn.setFixedSize(26, 26)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setIcon(_make_text_icon(ICON_TRASH, _system_color(QPalette.WindowText), 14))
        del_btn.setIconSize(QSize(14, 14))
        del_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: rgba(224, 49, 49, 60); }
        """)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._id))
        lay.addWidget(del_btn)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.copy_requested.emit(self._content)
        super().mousePressEvent(event)


class PanelHeader(QWidget):
    """Panel header: title + status + clear + close.

    The panel is NOT draggable — it always appears next to the current
    cursor position (see ClipboardPanel._place_near_cursor). Removing the
    drag handler also removes the "drop position" error path the user ran
    into after a drag."""

    def __init__(self, parent_panel):
        super().__init__(parent_panel)
        self._panel = parent_panel
        self.setFixedHeight(40)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            PanelHeader { background: transparent; border: none; }
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 6, 8, 6)
        lay.setSpacing(8)

        icon_lbl = QLabel()
        ic = _make_text_icon(ICON_CLIPBOARD, _system_color(QPalette.WindowText), 16)
        icon_lbl.setPixmap(ic.pixmap(16, 16))
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(icon_lbl)

        title = QLabel(I18n.tr("clipboard"))
        title.setStyleSheet(
            "color: palette(text); background: transparent; border: none;"
            " font-size: 13px; font-weight: 600;"
        )
        lay.addWidget(title)

        # Current room code (hidden until a room is configured). Kept terse
        # so it does not crowd the header's status area.
        self.room_label = QLabel("")
        self.room_label.setVisible(False)
        self.room_label.setStyleSheet(
            "color: #339af0; background: transparent; border: none;"
            " font-size: 11px;"
        )
        lay.addWidget(self.room_label)

        self.status_label = QLabel(I18n.tr("clipboard_status_disconnected"))
        self.status_label.setStyleSheet(
            "color: palette(placeholder-text); background: transparent;"
            " border: none; font-size: 11px;"
        )
        lay.addWidget(self.status_label, 1)

        clear_btn = QPushButton()
        clear_btn.setFixedSize(26, 26)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setIcon(_make_text_icon(ICON_TRASH, _system_color(QPalette.WindowText), 14))
        clear_btn.setIconSize(QSize(14, 14))
        clear_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: rgba(255,255,255,30); }
        """)
        clear_btn.setToolTip(I18n.tr("clipboard_clear_all"))
        clear_btn.clicked.connect(parent_panel.clear_requested)
        lay.addWidget(clear_btn)

        # Collapse button: "-" icon (was "X"). The button collapses the panel
        # card only — it does NOT disable the clipboard feature. That's an
        # intentional distinction from the capsule button's left-click
        # (which DOES disable when expanded). Hover stays neutral (no red),
        # since this is a "minimize" action, not a destructive one.
        collapse_btn = QPushButton()
        collapse_btn.setFixedSize(26, 26)
        collapse_btn.setCursor(Qt.PointingHandCursor)
        collapse_btn.setIcon(_make_text_icon(ICON_MINUS, _system_color(QPalette.WindowText), 14))
        collapse_btn.setIconSize(QSize(14, 14))
        collapse_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: rgba(255, 255, 255, 30); }
        """)
        collapse_btn.clicked.connect(parent_panel.collapse_requested)
        lay.addWidget(collapse_btn)

    def set_status(self, text):
        self.status_label.setText(text)

    def set_room(self, code):
        code = (code or "").strip()
        self.room_label.setVisible(bool(code))
        if code:
            self.room_label.setText(code)


class ClipboardPanel(QWidget):
    """Floating clipboard history card.

    NOT draggable — always positions itself next to the current cursor on
    every show (see _place_near_cursor). This matches the "click history
    item to paste at caret" workflow: the panel appears where the user is
    already working, and a paste auto-collapses it."""

    copy_requested = Signal(str)
    delete_requested = Signal(int)
    clear_requested = Signal()
    hide_family_requested = Signal()      # focus left family -> hide capsule + card
    collapse_requested = Signal()         # X button -> collapse card only

    WIDTH = 340
    MAX_HEIGHT = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Never steal focus (on show OR on click) — the user's caret stays in
        # their input field so clicking a history item copies and Ctrl+V
        # pastes at the original cursor. WS_EX_NOACTIVATE is applied in
        # showEvent once the HWND exists.
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(self.WIDTH)

        self._animating = False
        self._pending_hide = False  # True when hide_panel was triggered mid-show

        self._init_ui()
        self._init_anim()
        self.hide()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        # Card container (rounded background painted in paintEvent)
        self.header = PanelHeader(self)
        root.addWidget(self.header)

        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Single-step = one item row for keyboard arrows + scrollbar buttons.
        # Wheel scrolling is handled in SmoothScrollArea.wheelEvent (one item
        # per notch, independent of this singleStep).
        self.scroll.verticalScrollBar().setSingleStep(_ITEM_ROW_H)
        # pageStep = one item too, so PageUp/Down also advances one item
        # (matches the per-item scroll model).
        self.scroll.verticalScrollBar().setPageStep(_ITEM_ROW_H)
        self.scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: transparent; width: 8px; margin: 4px 2px;
            }
            QScrollBar::handle:vertical {
                background: palette(mid); border-radius: 4px; min-height: 24px;
            }
            QScrollBar::handle:vertical:hover { background: palette(dark); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)

        self.list_container = QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 4, 0, 4)
        self.list_layout.setSpacing(4)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_container)
        root.addWidget(self.scroll, 1)

        # Empty-state label (centered)
        self.empty_label = QLabel(I18n.tr("clipboard_empty"))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            "color: palette(placeholder-text); background: transparent; border: none; padding: 24px;"
        )
        self.empty_label.setFixedHeight(120)
        root.addWidget(self.empty_label)

    def _init_anim(self):
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        # A single finished-handler resets _animating for both show & hide.
        self.opacity_anim.finished.connect(self._on_opacity_anim_finished)

    def paintEvent(self, event):
        # Two-layer paint:
        #   1. Feathered shadow: 3 concentric rounded rects with rising
        #      alpha in the 2..8 px ring around the card. Painted in-bounds
        #      (QGraphicsDropShadowEffect made the dirty region exceed the
        #      translucent Qt.Tool window and triggered
        #      UpdateLayeredWindowIndirect "参数错误"). This gives the card
        #      visual lift without making the card itself translucent.
        #   2. Opaque card (alpha=255) + 1px white border for edge definition
        #      against any backdrop. Opaque (was 238) — readability first;
        #      text must not be clouded by desktop content bleeding through.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        shadow = QColor(0, 0, 0, 90)
        for inset, alpha in ((2, 18), (4, 28), (6, 42)):
            c = QColor(shadow)
            c.setAlpha(alpha)
            painter.setBrush(c)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(self.rect().adjusted(inset, inset, -inset, -inset), 16, 16)
        # Opaque card background
        bg = self.palette().color(QPalette.Window)
        bg.setAlpha(255)
        painter.setBrush(bg)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect().adjusted(8, 8, -8, -8), 14, 14)
        # 1px dark gray border (matches capsule). #505050 reads on both
        # light and dark themes without the harshness of pure white — but on
        # a light theme it comes across as a black ring, so it is dropped.
        painter.setBrush(Qt.NoBrush)
        if self.palette().color(QPalette.Window).lightness() < 128:
            painter.setPen(QPen(QColor(80, 80, 80, 255), 1))
            # Inset 1px further than the body (9 vs 8) and shrink the radius
            # to match, so the hairline sits fully inside the card edge like
            # the capsule's. Keeping both dimensions even avoids Qt's AA
            # rendering the top-left arc flatter than the top-right one.
            painter.drawRoundedRect(self.rect().adjusted(9, 9, -9, -9), 13, 13)

    def showEvent(self, event):
        # Apply WS_EX_NOACTIVATE once the HWND exists so mouse clicks on the
        # panel never steal focus from the user's input field.
        FamilyWindowRegistry.refresh_hwnd(self)
        FamilyWindowRegistry.set_no_activate(self)
        super().showEvent(event)

    # ----- public API -----

    def set_items(self, items):
        # Clear existing item widgets (keep the trailing stretch)
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for it in items:
            row = ClipboardItemWidget(it)
            row.copy_requested.connect(self.copy_requested)
            row.delete_requested.connect(self.delete_requested)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self.empty_label.setVisible(not items)
        self.scroll.setVisible(bool(items))
        # Resize height to fit content (clamped)
        self._adjust_height(len(items))

    def set_status(self, text, peer_count=0):
        self.header.set_status(text)

    def set_room(self, code):
        self.header.set_room(code)

    def _adjust_height(self, n):
        header_h = 40 + 24  # header + margins
        item_h = 56 + 4     # item + spacing
        content_h = header_h + min(n, 6) * item_h + 24
        self.setFixedHeight(min(self.MAX_HEIGHT, max(220, content_h)))

    def show_panel(self):
        """Show the panel, interrupting any in-progress hide animation by
        reversing from the current opacity. Safe to call when already fully
        shown (no-op) or while hiding (reverses).

        Every show repositions the panel next to the current cursor — there
        is no "remembered" position. This matches the paste-at-caret workflow:
        the panel always appears where the user is currently working."""
        # Already fully shown and not hiding → nothing to do.
        if self.isVisible() and not self._pending_hide:
            return

        first_show = not self.isVisible()
        if first_show:
            # Always reposition on a fresh show — never use a saved pos.
            self._place_near_cursor()
            FamilyWindowRegistry.add(self)
            self.setWindowOpacity(0.0)
            self.show()
            FamilyWindowRegistry.refresh_hwnd(self)
            self.raise_()
            start_opacity = 0.0
        else:
            # Reverse from wherever the hide animation currently is.
            start_opacity = self.windowOpacity()

        self.opacity_anim.stop()
        self.opacity_anim.setStartValue(start_opacity)
        self.opacity_anim.setEndValue(1.0)
        self._animating = True
        self._pending_hide = False
        self.opacity_anim.start()

    def hide_panel(self):
        """Hide the panel, interrupting any in-progress show animation by
        reversing from the current opacity. Safe to call when already hidden
        (no-op) or while showing (reverses).

        Qt's QAbstractAnimation.stop() does NOT emit finished, so reversing
        mid-show is safe — the unified _on_opacity_anim_finished handler
        only fires when this new hide animation completes."""
        if not self.isVisible():
            # Already hidden; ensure registry state is consistent.
            FamilyWindowRegistry.remove(self)
            return
        self.opacity_anim.stop()
        self.opacity_anim.setStartValue(self.windowOpacity())
        self.opacity_anim.setEndValue(0.0)
        self._animating = True
        self._pending_hide = True
        self.opacity_anim.start()

    def _on_opacity_anim_finished(self):
        """Unified handler for both show & hide animation completion."""
        self._animating = False
        if self._pending_hide:
            self._pending_hide = False
            self.hide()
            FamilyWindowRegistry.remove(self)

    def hide_immediately(self):
        """Hide instantly — no animation. Used when entering screenshot/
        annotation overlays where the panel must disappear before the
        overlay captures the screen (otherwise the panel would be in the
        screenshot). Symmetric with CapsuleBar.hide_immediately.
        """
        self.opacity_anim.stop()
        self._animating = False
        self._pending_hide = False
        self.hide()
        FamilyWindowRegistry.remove(self)

    def _place_near_cursor(self):
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = cursor.x() + 12
        y = cursor.y() + 12
        if x + self.WIDTH > geo.right():
            x = cursor.x() - self.WIDTH - 12
        if y + self.height() > geo.bottom():
            y = geo.bottom() - self.height() - 8
        x = max(geo.x(), x)
        y = max(geo.y(), y)
        self.move(x, y)
