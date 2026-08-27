from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QTextEdit, QApplication, QGraphicsDropShadowEffect,
    QPushButton, QFrame
)
from PySide6.QtCore import (
    Qt, QRect, QRectF, QPoint, QPointF, Signal, QVariantAnimation, QEasingCurve
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QGuiApplication, QFontMetrics,
    QPainterPath, QPalette, QBrush, QKeyEvent
)
from modules.overlay import BaseOverlay, draw_snapshot
from modules.icons import ICON_RECTANGLE, ICON_FREEFORM, ICON_TEXT, ICON_CLOSE
from modules.i18n import I18n
from modules.widgets import GlassIconButton, paint_pill


# Annotation drawing colours: white, black, and the standard seven colours.
# The toolbar shows these as a swatch picker; white is the default.
ANNOTATION_COLORS = {
    "white": "#ffffff",
    "black": "#000000",
    "red": "#ff3b30",
    "orange": "#ff9500",
    "yellow": "#ffcc00",
    "green": "#34c759",
    "blue": "#007aff",
    "indigo": "#5856d6",
    "purple": "#af52de",
}
ANNOTATION_COLOR_ORDER = [
    "white", "black", "red", "orange", "yellow",
    "green", "blue", "indigo", "purple",
]


def _accent():
    hl = QApplication.palette().color(QPalette.Highlight)
    return hl


class ColorButton(QPushButton):
    """Round toolbar button displaying the current annotation color.

    Hover grows a translucent accent ring (the same 180 ms language as the
    GlassIconButton) so it reads as part of the annotation pill family."""

    def __init__(self, color="#ffffff", parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(I18n.tr("color"))
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self._color = QColor(color)
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def animation_color(self):
        return self._color

    def _on_anim(self, v):
        self._t = float(v)
        self.update()

    def enterEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        cx, cy = self.width() / 2.0, self.height() / 2.0
        # Hover ring behind the swatch.
        if self._t > 0:
            hl = _accent()
            r = side / 2.0 - 1
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(hl.red(), hl.green(), hl.blue(),
                              int(46 * self._t)))
            p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        # The swatch itself.
        r = side / 2.0 - 6
        p.setPen(QPen(QColor(128, 128, 128, 130), 1))
        p.setBrush(self._color)
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        p.end()


class ColorStripArea(QWidget):
    """Leading spacer of the annotation toolbar that hosts the color swatches.

    Grows 0 -> SW_EXT as the capsule extends leftward, pushing the control
    buttons along with it. It is transparent to mouse events, so clicks pass
    straight through to the toolbar, which hit-tests the swatch rects in its
    own paint coordinates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedWidth(0)


class TextEditWidget(QTextEdit):
    """Inline text editor for annotation text.
    Created after dragging a rectangle in text mode.
    Press Enter to finish, double-click existing text to re-edit."""

    def __init__(self, rect, text="", parent=None):
        super().__init__(parent)
        self.setGeometry(rect)
        self.setPlainText(text)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QTextEdit {
                background-color: rgba(0, 0, 0, 140);
                color: #ffffff;
                border: 2px solid #c8c8c8;
                border-radius: 2px;
                padding: 6px;
                font-size: 16px;
                font-family: 'Segoe UI';
            }
        """)
        self.setFocus()
        self.selectAll()

    def keyPressEvent(self, event: QKeyEvent):
        # Ctrl+Enter to finish editing
        if event.key() == Qt.Key_Return and event.modifiers() & Qt.ControlModifier:
            self.parent()._finish_text_edit()
            return
        # ESC to cancel
        if event.key() == Qt.Key_Escape:
            self.parent()._cancel_text_edit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        # Finish editing when clicking outside
        self.parent()._finish_text_edit()
        super().focusOutEvent(event)


class AnnotationToolbar(QWidget):
    """Floating annotation sub-bar: color selector + mode buttons + close.

    Clicking the color button extends the capsule LEFTWARD into a long row
    of color swatches (the ColorStripArea leading spacer grows), and it
    collapses back once a color is picked (or the button is toggled again).

    Painted with the same pill look as the capsule bar (shared paint_pill),
    so both read as one design family; floats over the dark overlay with a
    soft drop shadow."""

    mode_changed = Signal(str)
    close_clicked = Signal()
    color_selected = Signal(str)  # emits the new annotation color hex

    BTN = 40
    RADIUS = 26
    BAR_H = 52

    # Swatch strip geometry (horizontal row, left-to-right).
    SW = 30
    GAP = 8
    SW_PAD = 6
    SW_EXT = SW_PAD + len(ANNOTATION_COLOR_ORDER) * (SW + GAP)

    # Collapsed width incl. the leading strip (even at 0px it adds one
    # 8px spacing): 10|strip0|8|color40|8|div1|8|rect40|8|free40|8|text40|8|close40|10
    BASE_W = 10 + 8 + BTN + 8 + 1 + 8 + BTN * 4 + 8 * 3 + 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedHeight(self.BAR_H)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 90))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        # Mode order = left-to-right button order. `_slide` is a float index
        # (0..2) that the selection plate glides across as it moves between
        # buttons — linear travel with slow-fast-slow easing (InOutCubic).
        self._modes = ["rectangle", "freeform", "text"]
        self._slide = 0.0
        self._slide_anim = QVariantAnimation(self)
        self._slide_anim.setDuration(280)
        self._slide_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._slide_anim.valueChanged.connect(self._on_slide)

        # Color strip expansion: 0 = collapsed, 1 = fully extended left.
        self._ext = 0.0
        self._sel_hex = ANNOTATION_COLORS["white"]
        self._ext_anim = QVariantAnimation(self)
        self._ext_anim.setDuration(250)
        self._ext_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._ext_anim.valueChanged.connect(self._on_ext)

        # Per-swatch hover: each swatch owns an independent fade so a fast
        # sweep lights them all up — no shared progress that stalls mid-flight
        # because every state change was restarting the same animation. The
        # colour behind the hovered swatch grows a translucent accent ring
        # (same 180 ms language as the ColorButton ring).
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover)
        self._hover_idx = -1
        self._hover_t = [0.0] * len(ANNOTATION_COLOR_ORDER)
        self._hover_anims = []
        for i in range(len(ANNOTATION_COLOR_ORDER)):
            anim = QVariantAnimation(self)
            anim.setDuration(180)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(lambda v, idx=i: self._set_hover_t(idx, v))
            self._hover_anims.append(anim)

        self.setup_ui()
        self.set_selected("rectangle")

    # ---- color strip expand / collapse ----

    def _on_ext(self, value):
        self._ext = float(value)
        self._apply_ext()

    def _apply_ext(self):
        """Grow the leading strip + the toolbar, shifting x left so the
        right (control) edge stays put — the bar extends to the LEFT."""
        ext = int(self.SW_EXT * self._ext)
        self._color_strip.setFixedWidth(ext)
        new_w = self.BASE_W + ext
        delta = new_w - self.width()
        if delta:
            self.setFixedWidth(new_w)
            self.move(max(8, self.x() - delta), self.y())
        self.update()

    def toggle_color_strip(self):
        if self._ext > 0.5:
            self.collapse_color_strip()
        else:
            self.expand_color_strip()

    def expand_color_strip(self):
        if self._ext >= 1.0:
            return
        self._ext_anim.stop()
        self._ext_anim.setStartValue(self._ext)
        self._ext_anim.setEndValue(1.0)
        self._ext_anim.start()

    def collapse_color_strip(self):
        if self._ext <= 0.0:
            return
        self._ext_anim.stop()
        self._ext_anim.setStartValue(self._ext)
        self._ext_anim.setEndValue(0.0)
        self._ext_anim.start()

    # ---- swatch geometry (toolbar-local coordinates) ----

    def _swatch_rect(self, index):
        # The strip is the first layout item, anchored at the left margin
        # (10px). Swatches sit inside it, pushed PAST the layout margin.
        x = 10 + self.SW_PAD + index * (self.SW + self.GAP)
        y = (self.BAR_H - self.SW) / 2.0
        return QRectF(x, y, self.SW, self.SW)

    def _swatch_at(self, pos):
        for i in range(len(ANNOTATION_COLOR_ORDER)):
            if self._swatch_rect(i).contains(pos):
                return i
        return -1

    # ---- swatch hover animation ----

    def _set_hover_t(self, index, value):
        self._hover_t[index] = float(value)
        self.update()

    def _set_hover(self, index):
        """Fade the ring in on the newly hovered swatch while the previous
        one fades out — each animates independently, so a fast sweep never
        stalls by resuming a shared mid-flight value."""
        prev = self._hover_idx
        self._hover_idx = index
        if prev >= 0 and prev != index:
            self._run_hover(prev, 0.0)
        if index >= 0:
            self._run_hover(index, 1.0)
        self.update()

    def _run_hover(self, index, target):
        anim = self._hover_anims[index]
        anim.stop()
        anim.setStartValue(self._hover_t[index])
        anim.setEndValue(target)
        anim.start()

    def _hover_track(self, pos):
        index = self._swatch_at(pos) if self._ext > 0.5 else -1
        if index != self._hover_idx:
            self._set_hover(index)
        self.setCursor(Qt.PointingHandCursor if index >= 0 else Qt.ArrowCursor)
        return index

    def mouseMoveEvent(self, event):
        self._hover_track(event.position())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_track(QPointF(-1, -1))
        super().leaveEvent(event)

    def _select_color_at(self, index):
        key = ANNOTATION_COLOR_ORDER[index]
        hex_color = ANNOTATION_COLORS[key]
        self._sel_hex = hex_color
        self.btn_color.set_color(hex_color)
        self.color_selected.emit(hex_color)
        self.collapse_color_strip()

    def set_selected(self, mode):
        """Glide the selection plate to the given mode's button position."""
        if mode not in self.mode_buttons:
            return
        target = float(self._modes.index(mode))
        self._slide_anim.stop()
        self._slide_anim.setStartValue(self._slide)
        self._slide_anim.setEndValue(target)
        self._slide_anim.start()

    def _on_slide(self, value):
        self._slide = float(value)
        self.update()

    def set_annotation_color(self, color):
        self._sel_hex = color
        self.btn_color.set_color(color)

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 6, 10, 6)

        # Leading spacer that hosts the color swatches. Grows on expand.
        self._color_strip = ColorStripArea(self)
        layout.addWidget(self._color_strip)

        # --- color switch section, split from the modes by a "|" ---
        self.btn_color = ColorButton(ANNOTATION_COLORS["white"], self)
        self.btn_color.setFixedSize(self.BTN, self.BTN)
        self.btn_color.clicked.connect(self.toggle_color_strip)
        layout.addWidget(self.btn_color)

        divider = QFrame(self)
        divider.setFixedSize(1, self.BTN - 12)
        divider.setStyleSheet(
            "background: rgba(130,130,130,150); border-radius: 1px;")
        layout.addWidget(divider)

        # Mode buttons keep their original icon colour (only the shared slide
        # plate highlights them), hence colorize_icon=False.
        self.mode_buttons = {}
        for mode, svg, tip in [
            ("rectangle", ICON_RECTANGLE, I18n.tr("rectangle")),
            ("freeform", ICON_FREEFORM, I18n.tr("freeform")),
            ("text", ICON_TEXT, I18n.tr("text")),
        ]:
            btn = GlassIconButton(svg, tip, size=self.BTN, icon_size=20,
                                  colorize_icon=False)
            btn.clicked.connect(
                lambda checked, m=mode: self._on_mode_clicked(m))
            self.mode_buttons[mode] = btn
            layout.addWidget(btn)

        self.btn_close = GlassIconButton(
            ICON_CLOSE, I18n.tr("close"), size=self.BTN, icon_size=20,
            hover_color="#e03131", hover_bg_color=QColor(224, 49, 49))
        self.btn_close.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.btn_close)

        self.setFixedWidth(self.BASE_W)

    def _on_mode_clicked(self, mode):
        # Picking a mode is a clear "done with colors" signal — collapse the
        # strip so a stray open strip doesn't linger.
        if self._ext > 0.5:
            self.collapse_color_strip()
        self.mode_changed.emit(mode)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._ext > 0.5:
            idx = self._swatch_at(event.position())
            if idx >= 0:
                self._select_color_at(idx)
                return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        paint_pill(painter, self.rect(), self.RADIUS)

        # --- color swatches revealed as the strip extends left ---
        if self._ext > 0:
            visible_ext = 10 + int(self.SW_EXT * self._ext)
            painter.save()
            painter.setOpacity(self._ext)
            hl = _accent()
            for i, key in enumerate(ANNOTATION_COLOR_ORDER):
                rect = self._swatch_rect(i)
                if rect.left() > visible_ext:
                    break
                cx, cy = rect.center().x(), rect.center().y()
                color = QColor(ANNOTATION_COLORS[key])

                # Hover halo: a translucent accent disc grows out from the
                # swatch (radius & alpha both animate), read as a soft lift.
                # Painted per-swatch so a fading-out neighbour keeps its glow
                # while the newly hovered one fades in.
                if self._hover_t[i] > 0:
                    t = self._hover_t[i]
                    hr = (rect.width() / 2.0 - 1) + 5 * t
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(
                        QColor(hl.red(), hl.green(), hl.blue(),
                               int(46 * t)))
                    painter.drawEllipse(QRectF(cx - hr, cy - hr, 2 * hr, 2 * hr))

                sr = rect.width() / 2.0 - 1
                painter.setPen(QPen(QColor(128, 128, 128, 130), 1))
                painter.setBrush(color)
                painter.drawEllipse(QRectF(cx - sr, cy - sr, 2 * sr, 2 * sr))

                selected = (ANNOTATION_COLORS[key] == self._sel_hex)
                if selected:
                    painter.setPen(QPen(hl, 2))
                    painter.setBrush(Qt.NoBrush)
                    rr = rect.width() / 2.0
                    painter.drawEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))
            painter.restore()

        # Selection plate gliding behind the active mode button. The mode
        # buttons are transparent (never set_active), so this plate shows
        # through them and slides linearly with slow-fast-slow easing.
        spacing = 8
        ms = self.btn_color.x() + self.BTN + 8 + 1 + 8  # where modes begin
        x = int(ms + self._slide * (self.BTN + spacing))
        slider = QRect(x, 6, self.BTN, self.BTN)
        if slider.intersects(self.rect()):
            painter.setPen(Qt.NoPen)
            hl = QApplication.palette().color(QPalette.Highlight)
            painter.setBrush(QColor(hl.red(), hl.green(), hl.blue(), 150))
            painter.drawRoundedRect(slider, self.BTN // 3, self.BTN // 3)


class AnnotationOverlay(BaseOverlay):
    """Screen annotation overlay with rectangle, freeform, and text tools"""
    finished = Signal()

    def __init__(self, parent=None):
        # Capture desktop before overlay is shown
        self.desktop_pixmap = QGuiApplication.primaryScreen().grabWindow(0)
        super().__init__(parent)
        self.annotations = []
        self.current_mode = "rectangle"
        self.current_shape = None
        self.is_drawing = False
        self.text_editor = None  # active inline text editor
        self._text_edit_idx = None  # index of text annotation being edited, None for new
        self._drag_start = None  # start point of current drag (like screenshot approach)
        # Per-annotation corner beans: delete (red) + move (white) dots.
        self._delete_rects = {}
        self._drag_rects = {}
        self._drag_ann_idx = None  # annotation currently being moved
        self._drag_offset = None   # grab point offset from the annotation origin
        self._last_drag_pos = None
        self.annotation_color = QColor(ANNOTATION_COLORS["white"])
        self._pending_text_color = None  # colour captured when a text box is drawn
        self.activateWindow()
        self.setFocus()
        # Hover tracking for the macOS-style corner beans (a faint pair that
        # light up together — white for move, red for delete — when the
        # cursor is over either of them).
        self.setMouseTracking(True)
        self._hover_ann = None   # (x, y, w, h) of the lit bean pair's annotation
        self.setup_toolbar()

    def setup_toolbar(self):
        """Create the floating annotation sub-bar (same pill style as capsule)."""
        self.toolbar = AnnotationToolbar(self)
        self.toolbar.mode_changed.connect(self._set_mode)
        self.toolbar.close_clicked.connect(self._on_close_clicked)
        self.toolbar.color_selected.connect(self._set_color)

        screen = QGuiApplication.primaryScreen().availableGeometry()
        tw = self.toolbar.width()
        tx = (screen.width() - tw) // 2
        self.toolbar.setGeometry(int(tx), 60, tw, AnnotationToolbar.BAR_H)
        self.toolbar.show()

    def _set_color(self, color):
        """Apply a selected swatch colour to the annotation drawing."""
        self.annotation_color = QColor(color)
        self.toolbar.set_annotation_color(color)

    def _on_close_clicked(self):
        self.finished.emit()
        self.close_overlay()

    def _set_mode(self, mode):
        self.current_mode = mode
        self.toolbar.set_selected(mode)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Freeze the frame: paint the static desktop snapshot as an opaque
        # base so live changes behind the translucent overlay never bleed
        # through. Both the dimmed surroundings and the bright boxed cutouts
        # then come from the same snapshot and update together — no more
        # "background refreshes, selection stays frozen" mismatch.
        painter.drawPixmap(self.rect(), self.desktop_pixmap,
                           QRect(self.desktop_pixmap.rect()))
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))
        for ann in self.annotations:
            self._draw_annotation(painter, ann, is_temp=False)
        if self.current_shape and self.is_drawing:
            # During drag, text shape has no text content — only draw the rect
            self._draw_annotation(painter, self.current_shape, is_temp=True)

    def _draw_annotation(self, painter, ann, is_temp=False):
        ann_type = ann[0]
        # Each annotation keeps the brush colour it was drawn with, so
        # changing the palette never recolours shapes already on the canvas
        # (like switching a pen mid-sketch — existing strokes stay as-is).
        border_color = QColor(ann[-1])
        painter.setPen(QPen(border_color, 2))

        if ann_type == "rectangle":
            rect = ann[1]
            # Cut out the overlay - show desktop content inside the rectangle.
            # 1:1 physical-pixel paint so HiDPI scaling never wobbles the
            # text while the rectangle is being drawn.
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            draw_snapshot(painter, self.desktop_pixmap, rect)
            # Draw border only (no fill)
            painter.setPen(QPen(border_color, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            if not is_temp:
                self._draw_handles(painter, rect.topRight(), rect)

        elif ann_type == "freeform":
            points = ann[1]
            if len(points) < 2:
                return
            path = QPainterPath()
            path.moveTo(points[0])
            for pt in points[1:]:
                path.lineTo(pt)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            if not is_temp:
                bounds = path.boundingRect().toRect()
                self._draw_handles(painter, bounds.topRight(), bounds)

        elif ann_type == "text":
            rect = ann[1]
            # Draw border
            painter.setPen(QPen(border_color, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            if not is_temp and len(ann) > 2:
                # Draw text inside the rect (only for saved annotations)
                text = ann[2]
                painter.setFont(QFont("Segoe UI", 14))
                painter.setPen(border_color)
                painter.drawText(rect.adjusted(6, 6, -6, -6), Qt.AlignLeft | Qt.AlignTop, text)
                self._draw_handles(painter, rect.topRight(), rect)

    def _handle_rects(self, top_right, annotation_rect):
        """Layout the two corner controls of an annotation, top-right:
           [drag grip] [delete]. Both sit INSIDE the annotation's right edge
           so they never poke out beyond the content. If the corner is too
           close to the top edge, both controls drop below the annotation."""
        btn_size = 11
        spacing = 4
        margin = 6
        y = top_right.y() - btn_size - margin
        if y < 0:
            y = annotation_rect.bottom() + margin
        # Right-align: delete's right edge touches the content's right edge;
        # the drag grip sits to its left.
        left_limit = annotation_rect.left() + margin
        xd = max(int(top_right.x() - btn_size), int(left_limit))
        delete_rect = QRect(int(xd), int(y), btn_size, btn_size)
        xg = max(int(xd - btn_size - spacing), int(left_limit))
        drag_rect = QRect(int(xg), int(y), btn_size, btn_size)
        return drag_rect, delete_rect

    def _draw_handles(self, painter, top_right, annotation_rect):
        """Draw two small rounded beans at the annotation's top-right corner,
        macOS-traffic-light style. Both sit as a faint neutral grey pair; when
        the cursor is over EITHER bean of the same annotation, both light up —
        white for move (drag), red for delete. Records both hit rects."""
        drag_rect, delete_rect = self._handle_rects(top_right, annotation_rect)
        ann_key = (annotation_rect.x(), annotation_rect.y(),
                   annotation_rect.width(), annotation_rect.height())
        self._delete_rects[ann_key] = delete_rect
        self._drag_rects[ann_key] = drag_rect

        painter.setRenderHint(QPainter.Antialiasing)
        lit = self._hover_ann == ann_key
        # While actively dragging an annotation, keep its bean pair lit even
        # if the cursor drifts off the beans (the box follows the mouse).
        if not lit and self._drag_ann_idx is not None:
            idx = self._drag_ann_idx
            if 0 <= idx < len(self.annotations):
                dcorner = self._annotation_corner(self.annotations[idx])
                if dcorner is not None:
                    dr = dcorner[1]
                    if (dr.x(), dr.y(), dr.width(), dr.height()) == ann_key:
                        lit = True
        self._beam_to(painter, drag_rect, QColor(255, 255, 255), lit)
        self._beam_to(painter, delete_rect, QColor(255, 95, 87), lit)

    def _beam_to(self, painter, bean_rect, lit_color, lit):
        """Paint a single corner bean: faint grey when idle, `lit_color` when
        its annotation's bean pair is hovered. A soft thin ring keeps the bean
        legible over the dark canvas."""
        if lit:
            fill = QColor(lit_color)
            ring = QColor(255, 255, 255, 70)
        else:
            # Idle beans stay very faint so they barely cover the capture.
            fill = QColor(255, 255, 255, 18)
            ring = QColor(255, 255, 255, 55)
        painter.setPen(QPen(ring, 1))
        painter.setBrush(fill)
        painter.drawEllipse(bean_rect)

    def _update_handle_hover(self, pos):
        """Track which annotation's bean pair the cursor is over; both beans
        of that pair light together."""
        hovered = None
        for ann in self.annotations:
            corner = self._annotation_corner(ann)
            if corner is None:
                continue
            drag_rect, delete_rect = self._handle_rects(*corner)
            # Union the two beans so moving between them (over the gap)
            # keeps the pair lit instead of flickering.
            if drag_rect.united(delete_rect).contains(pos):
                r = corner[1]
                hovered = (r.x(), r.y(), r.width(), r.height())
                break
        if hovered != self._hover_ann:
            self._hover_ann = hovered
            self.update()

    def leaveEvent(self, event):
        # Moving out of the window clears any lit bean pair.
        if self._hover_ann is not None:
            self._hover_ann = None
            self.update()
        super().leaveEvent(event)

    def _get_delete_rects(self):
        result = {}
        for i, ann in enumerate(self.annotations):
            corner = self._annotation_corner(ann)
            if corner is not None:
                result[i] = self._handle_rects(*corner)[1]
        return result

    def _get_drag_rects(self):
        result = {}
        for i, ann in enumerate(self.annotations):
            corner = self._annotation_corner(ann)
            if corner is not None:
                result[i] = self._handle_rects(*corner)[0]
        return result

    def _annotation_corner(self, ann):
        """Return (top_right, annotation_rect) for a stored annotation,
        or None if it has no usable geometry."""
        ann_type = ann[0]
        if ann_type in ("rectangle", "text"):
            rect = ann[1]
            return (rect.topRight(), rect)
        if ann_type == "freeform":
            points = ann[1]
            if len(points) >= 2:
                path = QPainterPath()
                path.moveTo(points[0])
                for pt in points[1:]:
                    path.lineTo(pt)
                bounds = path.boundingRect().toRect()
                return (bounds.topRight(), bounds)
        return None

    def _is_text_double_click(self, pos):
        """Check if position is inside an existing text annotation (for double-click edit)"""
        for ann in self.annotations:
            if ann[0] == "text":
                rect = ann[1]
                if rect.contains(pos):
                    return ann
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()

            # A click anywhere on the overlay while the color strip is open
            # collapses it first (does not start a new annotation).
            if self.toolbar and self.toolbar._ext > 0.5:
                self.toolbar.collapse_color_strip()
                return

            # Check delete buttons first
            delete_rects = self._get_delete_rects()
            for idx, rect in delete_rects.items():
                if rect.contains(pos):
                    self._finish_text_edit()
                    self.annotations.pop(idx)
                    self._delete_rects = {}
                    self._drag_rects = {}
                    self.update()
                    return

            # Drag handle: grab an existing annotation to move it.
            if self._drag_ann_idx is None:
                for idx, rect in self._get_drag_rects().items():
                    if rect.contains(pos):
                        self._finish_text_edit()
                        ann = self.annotations[idx]
                        ref = (ann[1][0] if ann[0] == "freeform"
                               else ann[1].topLeft())
                        self._drag_ann_idx = idx
                        self._drag_offset = pos - ref
                        self._last_drag_pos = pos
                        self.update()
                        return

            # If text editor is active and user clicks outside it, finish editing
            if self.text_editor:
                if not self.text_editor.geometry().contains(pos):
                    self._finish_text_edit()
                else:
                    super().mousePressEvent(event)
                    return

            # Start drawing (same approach as screenshot: store start_point)
            self._drag_start = pos
            self.is_drawing = True
            brush = self.annotation_color.name()  # colour frozen at draw-time
            if self.current_mode == "rectangle":
                self.current_shape = ("rectangle", QRect(pos, pos), brush)
            elif self.current_mode == "freeform":
                self.current_shape = ("freeform", [pos], brush)
            elif self.current_mode == "text":
                self.current_shape = ("text", QRect(pos, pos), brush)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Double-click on existing text annotation to edit"""
        if event.button() == Qt.LeftButton and self.current_mode == "text":
            pos = event.position().toPoint()
            existing = self._is_text_double_click(pos)
            if existing:
                # Cancel the drawing started by the first click
                self.is_drawing = False
                self.current_shape = None
                self._drag_start = None
                idx = self.annotations.index(existing)
                self._start_text_edit(existing[1], existing[2], idx)
                return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        # Keep the corner beans lit as they're hovered (before any early
        # return below, so the state stays current while dragging too).
        self._update_handle_hover(pos)
        # Dragging an existing annotation through its grip handle.
        if self._drag_ann_idx is not None and self._last_drag_pos is not None:
            ann = self.annotations[self._drag_ann_idx]
            if ann[0] == "freeform":
                delta = pos - self._last_drag_pos
                pts = ann[1]  # translate the shared list in place (tuple-immutable)
                pts[:] = [pt + delta for pt in pts]
                self._last_drag_pos = pos
            else:
                ann[1].moveTopLeft(pos - self._drag_offset)
            self._drag_rects = {}
            self._delete_rects = {}
            self.update()
            return

        if self.is_drawing and self._drag_start and self.current_shape:
            pos = event.position().toPoint()
            brush = self.current_shape[-1]  # keep the draw-time colour
            if self.current_mode == "rectangle":
                # Same approach as screenshot: QRect(start, end).normalized()
                self.current_shape = ("rectangle", QRect(self._drag_start, pos).normalized(), brush)
            elif self.current_mode == "freeform":
                self.current_shape[1].append(pos)
            elif self.current_mode == "text":
                self.current_shape = ("text", QRect(self._drag_start, pos).normalized(), brush)
            self.update()

    def mouseReleaseEvent(self, event):
        # Finish an annotation move started from the grip handle.
        if event.button() == Qt.LeftButton and self._drag_ann_idx is not None:
            self._drag_ann_idx = None
            self._drag_offset = None
            self._last_drag_pos = None
            self._drag_rects = {}
            self._delete_rects = {}
            # Re-evaluate hover at the release point, otherwise the bean
            # pair stays dark even though the cursor is still over it.
            self._update_handle_hover(event.position().toPoint())
            self.update()
            return

        if event.button() == Qt.LeftButton and self.is_drawing:
            self.is_drawing = False
            if self.current_shape:
                mode = self.current_mode
                if mode == "rectangle":
                    rect = self.current_shape[1]
                    if rect.width() > 5 and rect.height() > 5:
                        self.annotations.append(self.current_shape)
                elif mode == "freeform":
                    if len(self.current_shape[1]) >= 3:
                        self.annotations.append(self.current_shape)
                elif mode == "text":
                    rect = self.current_shape[1]
                    if rect.width() > 5 and rect.height() > 5:
                        # Remember the draw-time colour for the new text box.
                        self._pending_text_color = self.current_shape[-1]
                        # Create inline text editor
                        self._start_text_edit(rect, "", None)
            self.current_shape = None
            self._drag_start = None
            self._delete_rects = {}
            self.update()

    def _start_text_edit(self, rect, text, edit_idx):
        """Create an inline text editor at the given rect"""
        self._finish_text_edit()  # finish any existing editor first
        self._text_edit_idx = edit_idx
        self.text_editor = TextEditWidget(rect, text, self)
        self.text_editor.show()
        self.text_editor.setFocus()

    def _finish_text_edit(self):
        """Save text from the active editor and destroy it"""
        if self.text_editor is None:
            return
        text = self.text_editor.toPlainText().strip()
        rect = self.text_editor.geometry()
        self.text_editor.deleteLater()
        self.text_editor = None
        if text:
            if self._text_edit_idx is not None:
                # Re-editing an existing text — keep its original colour.
                color = self.annotations[self._text_edit_idx][-1]
                self.annotations[self._text_edit_idx] = ("text", rect, text, color)
            else:
                # New text — use the colour captured when its box was drawn.
                color = self._pending_text_color or self.annotation_color.name()
                self.annotations.append(("text", rect, text, color))
        self._text_edit_idx = None
        self._pending_text_color = None
        self.update()
        # Re-focus the overlay for keyboard events
        self.setFocus()

    def _cancel_text_edit(self):
        """Cancel text editing and destroy the editor"""
        if self.text_editor:
            self.text_editor.deleteLater()
            self.text_editor = None
        self._text_edit_idx = None
        self.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.is_drawing:
                self.is_drawing = False
                self.current_shape = None
                self._drag_start = None
                self.update()
            else:
                self.finished.emit()
                self.close_overlay()
        super().keyPressEvent(event)