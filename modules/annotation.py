from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QTextEdit, QApplication, QGraphicsDropShadowEffect,
    QPushButton, QFrame
)
from PySide6.QtCore import (
    Qt, QRect, QRectF, QPoint, QPointF, Signal, QVariantAnimation, QEasingCurve,
    QTimer
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QGuiApplication, QFontMetrics,
    QPainterPath, QPalette, QBrush, QKeyEvent
)
from modules.overlay import BaseOverlay, draw_snapshot
from modules.icons import (
    ICON_RECTANGLE, ICON_FREEFORM, ICON_TEXT, ICON_ERASER, ICON_CLOSE
)
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


def _as_segments(pts):
    """Turn a QPoint list into segment pairs; a lone point becomes a
    zero-length segment so the erase routines don't need a special case."""
    if len(pts) == 1:
        return [(pts[0], pts[0])]
    return list(zip(pts, pts[1:]))


def _point_seg_dist(p, a, b):
    """Distance from point `p` to segment(a,b)."""
    ax, ay = a.x(), a.y()
    bx, by = b.x(), b.y()
    px, py = p.x(), p.y()
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _point_polyline_distance(poly, p):
    """Minimum distance from point `p` to the open polyline `poly`."""
    best = 1e18
    for (a, b) in zip(poly, poly[1:]):
        d = _point_seg_dist(p, a, b)
        if d < best:
            best = d
    return best


def _orient(ax, ay, bx, by, cx, cy):
    return (by - ay) * (cx - bx) - (bx - ax) * (cy - by)


def _segments_intersect(a, b, c, d):
    """Proper segment AB vs CD intersection (strict, orientation test)."""
    o1 = _orient(a.x(), a.y(), b.x(), b.y(), c.x(), c.y())
    o2 = _orient(a.x(), a.y(), b.x(), b.y(), d.x(), d.y())
    o3 = _orient(c.x(), c.y(), d.x(), d.y(), a.x(), a.y())
    o4 = _orient(c.x(), c.y(), d.x(), d.y(), b.x(), b.y())
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def _seg_close_to_rect(a, b, rect, radius):
    """True if segment AB passes within `radius` of the rectangle's border.
    Distance-based (not strict crossing), so a stroke laid right on or over
    the edge reliably deletes it. A stroke purely deep inside the box rarely
    gets near the border, keeping nested inner annotations safe."""
    L, R, T, B = rect.left(), rect.right(), rect.top(), rect.bottom()
    edges = [((L, T), (R, T)), ((R, T), (R, B)),
             ((R, B), (L, B)), ((L, B), (L, T))]
    return any(_segments_close(a, b, QPoint(*c), QPoint(*d), radius)
               for (c, d) in edges)


def _segments_close(a, b, c, d, radius):
    """True if segment AB comes within `radius` of segment CD."""
    if _segments_intersect(a, b, c, d):
        return True
    for v, seg in ((a, (c, d)), (b, (c, d)), (c, (a, b)), (d, (a, b))):
        if _point_seg_dist(v, seg[0], seg[1]) <= radius:
            return True
    return False


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
    # 8px spacing): 10|strip0|8|color40|8|div1|8|rect40|8|free40|8|text40|8|eraser40|8|close40|10
    BASE_W = 10 + 8 + BTN + 8 + 1 + 8 + BTN * 5 + 8 * 4 + 10

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
        # (0..3) that the selection plate glides across as it moves between
        # buttons — linear travel with slow-fast-slow easing (InOutCubic).
        self._modes = ["rectangle", "freeform", "text", "eraser"]
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
            ("eraser", ICON_ERASER, I18n.tr("eraser")),
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
        self._drag_ann_idx = None  # annotation currently being moved
        self._drag_offset = None   # grab point offset from the annotation origin
        self._last_drag_pos = None
        self.annotation_color = QColor(ANNOTATION_COLORS["white"])
        self._pending_text_color = None  # colour captured when a text box is drawn
        # Eraser stroke currently being swept (transient, overlay coords).
        self._eraser_points = None
        self._hint_show = True
        self._hint = I18n.tr("annotate_hint")
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(1500)
        self._hint_timer.timeout.connect(self._hide_hint)
        self._hint_timer.start()
        self.activateWindow()
        self.setFocus()
        self.setup_toolbar()

    def _hide_hint(self):
        self._hint_show = False
        self.update()

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
        self._clear_drag()
        self.is_drawing = False
        self.current_shape = None
        self._drag_start = None
        self._eraser_points = None
        self.toolbar.set_selected(mode)
        self.update()

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
        # Transient erase stroke being swept.
        if self.current_mode == "eraser" and self._eraser_points:
            pts = self._eraser_points
            painter.setPen(QPen(QColor(255, 82, 82, 190), self.ERASE_W,
                                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            if len(pts) == 1:
                painter.drawPoint(pts[0])
            else:
                for a, b in zip(pts, pts[1:]):
                    painter.drawLine(a, b)
        # One-shot "左键绘制，右键移动" hint fading with the entry timer.
        if self._hint_show:
            self._draw_hint(painter)

    def _draw_hint(self, painter):
        fm = QFontMetrics(painter.font())
        tw = fm.horizontalAdvance(self._hint)
        pad_x, pad_y = 18, 9
        w = tw + pad_x * 2
        h = fm.height() + pad_y * 2
        x = (self.width() - w) // 2
        # Place just below the annotation toolbar (top=60, height=BAR_H) with a small gap.
        y = 60 + AnnotationToolbar.BAR_H + 8
        rect = QRect(int(x), int(y), int(w), int(h))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 20, 24, 215))
        painter.drawRoundedRect(rect, h / 2, h / 2)
        painter.setPen(QColor(245, 245, 248))
        font = painter.font()
        font.setPixelSize(int(fm.height() * 0.9))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self._hint)

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

    # ---- moving (right-drag) & eraser ----

    HIT_TOL = 10  # px tolerance when grabbing a freeform by its line

    def _grab_target(self, pos):
        """Topmost annotation under `pos` for a right-hold move. Rects/text
        grab by their whole box (the inside works too — move is a dedicated
        gesture now), freeform grabs near its drawn polyline."""
        for i in range(len(self.annotations) - 1, -1, -1):
            ann = self.annotations[i]
            if ann[0] in ("rectangle", "text"):
                if ann[1].contains(pos):
                    return i
            elif ann[0] == "freeform":
                if len(ann[1]) >= 2 and _point_polyline_distance(ann[1], pos) <= self.HIT_TOL:
                    return i
        return None

    def _grab_annotation(self, idx, pos):
        """Start moving a stored annotation: remember its index and the grab
        offset from its origin so the move tracks the cursor in place."""
        self._drag_ann_idx = idx
        ref = (self.annotations[idx][1][0] if
               self.annotations[idx][0] == "freeform"
               else self.annotations[idx][1].topLeft())
        self._drag_offset = pos - ref
        self._last_drag_pos = pos

    def _clear_drag(self):
        self._drag_ann_idx = None
        self._drag_offset = None
        self._last_drag_pos = None

    def _move_annotation(self, idx, delta):
        """Translate a stored annotation by `delta` (QPoint)."""
        ann = self.annotations[idx]
        if ann[0] == "freeform":
            ann[1][:] = [pt + delta for pt in ann[1]]
        else:
            ann[1].translate(delta)

    # ---- eraser ----

    ERASE_R = 10  # hit radius for freeform (px)
    ERASE_W = 4   # drawn stroke width (px) — thinner than the hit radius

    def _erase_annotations(self, stroke):
        """Delete the topmost-first list of every annotation the erase stroke
        swept over, then repaint and keep focus for continued sweeping."""
        doomed = [i for i, ann in enumerate(self.annotations)
                  if self._stroke_hits_annotation(stroke, ann)]
        for i in reversed(doomed):
            self.annotations.pop(i)
        self.update()
        self.setFocus()

    def _stroke_hits_annotation(self, stroke, ann):
        """True if the erase `stroke` (list of QPoint) touches `ann`."""
        segs = _as_segments(stroke)
        ann_type = ann[0]
        if ann_type in ("rectangle", "text"):
            rect = ann[1]
            return any(_seg_close_to_rect(a, b, rect, self.ERASE_R)
                       for (a, b) in segs)
        if ann_type == "freeform":
            poly = ann[1]
            if len(poly) < 2:
                return False
            return any(_segments_close(a, b, c, d, self.ERASE_R)
                       for (a, b) in segs for (c, d) in zip(poly, poly[1:]))
        return False

    def _is_text_double_click(self, pos):
        """Check if position is inside an existing text annotation (for double-click edit)"""
        for ann in self.annotations:
            if ann[0] == "text":
                rect = ann[1]
                if rect.contains(pos):
                    return ann
        return None

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        # Right-hold = move: drag the annotation under the cursor. Left is
        # always reserved for drawing/erasing, so move never collides.
        if event.button() == Qt.RightButton:
            if self.toolbar and self.toolbar._ext > 0.5:
                self.toolbar.collapse_color_strip()
                return
            target = self._grab_target(pos)
            if target is not None:
                self._finish_text_edit()
                self._grab_annotation(target, pos)
                self.update()
            return

        if event.button() == Qt.LeftButton:
            # A click anywhere on the overlay while the color strip is open
            # collapses it first (does not start a new annotation).
            if self.toolbar and self.toolbar._ext > 0.5:
                self.toolbar.collapse_color_strip()
                return

            # Eraser mode: begin sweeping a transient erase stroke.
            if self.current_mode == "eraser":
                if self.text_editor:
                    self._finish_text_edit()
                self.is_drawing = True
                self._eraser_points = [pos]
                self.update()
                return

            # If a text editor is active and user clicks outside it, finish
            if self.text_editor:
                if not self.text_editor.geometry().contains(pos):
                    self._finish_text_edit()
                else:
                    super().mousePressEvent(event)
                    return

            # Start drawing a new annotation (left always draws, even over an
            # existing one — moving is the right-button's job).
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
                # A single-click press may have begun a move — cancel it and
                # edit the text instead.
                self._clear_drag()
                self.is_drawing = False
                self.current_shape = None
                self._drag_start = None
                idx = self.annotations.index(existing)
                self._start_text_edit(existing[1], existing[2], idx)
                return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        # Move: right-hold dragging the annotation grabbed at the cursor.
        if self._drag_ann_idx is not None and self._last_drag_pos is not None:
            delta = pos - self._last_drag_pos
            self._move_annotation(self._drag_ann_idx, delta)
            self._last_drag_pos = pos
            self.update()
            return
        # Eraser: extend the transient erase stroke.
        if self.current_mode == "eraser" and self.is_drawing:
            self._eraser_points.append(pos)
            self.update()
            return
        # Drawing a new annotation.
        if self.is_drawing and self._drag_start and self.current_shape:
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
        # Finish moving a right-dragged annotation.
        if event.button() == Qt.RightButton and self._drag_ann_idx is not None:
            self._clear_drag()
            self.update()
            return

        # Eraser: on release, delete every annotation the stroke swept over.
        if event.button() == Qt.LeftButton and self.current_mode == "eraser" \
                and self._eraser_points:
            pts = self._eraser_points
            self._eraser_points = None
            self.is_drawing = False
            self._erase_annotations(pts)
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