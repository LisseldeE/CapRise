"""Shared visual helpers for the floating toolbars.

The capsule bar and the annotation sub-bar are siblings in the same window
"family", so they share one look: a rounded "pill" background with a subtle
vertical gradient (Qt decides the colours from the system palette), the
family hairline border (#505050, same as the clipboard panel), and smooth
animated icon buttons (translucent light-blue highlight on hover/press, a
persistent lit state for toggles, and a 1 px press-down from the reference
AnimatedButton pattern). Keeping this in one module guarantees the two bars
stay visually consistent.
"""
from PySide6.QtCore import (
    Qt, QByteArray, QRectF, QPointF, QEvent, QVariantAnimation, QEasingCurve,
    Signal
)
from PySide6.QtGui import (
    QPainter, QColor, QPixmap, QIcon, QPalette, QLinearGradient, QPen,
    QGuiApplication
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton, QApplication


def screen_dpr():
    """System devicePixelRatio (1.0 at 100% scaling, 1.25 at 125%, ...)."""
    return QGuiApplication.primaryScreen().devicePixelRatio() or 1.0


def make_pixmap(svg_content, color, size):
    """Rasterise an SVG (with color substitution) onto a DPR-scaled buffer.

    The buffer is `size * devicePixelRatio` px and tagged with that DPR, so
    when it's drawn via a DPR-aware painter it displays at its logical size
    while staying crisp on scaled-Windows (HiDPI) displays."""
    colored = svg_content.replace('stroke="currentColor"', f'stroke="{color}"')
    renderer = QSvgRenderer(QByteArray(colored.encode()))
    dpr = screen_dpr()
    pixmap = QPixmap(int(size * dpr), int(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def make_icon(svg_content, color, size=22):
    """Create a QIcon from an SVG string with a color substitution."""
    return QIcon(make_pixmap(svg_content, color, size))


def system_color(role):
    """Hex string for a system palette color."""
    c = QApplication.palette().color(role)
    return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"


def paint_pill(painter, rect, radius):
    """Paint a toolbar pill: gradient body + hairline border.

    The body is a subtle top-to-bottom gradient derived from the system
    window color (no fixed colors — Qt decides), and the hairline is the
    family's #505050 so every window of the app reads as one design. On
    light themes the hairline is dropped — it reads as a harsh black ring.
    """
    painter.setRenderHint(QPainter.Antialiasing)
    bg = QApplication.palette().color(QPalette.Window)
    is_dark = bg.lightness() < 128
    top = bg.lighter(150) if is_dark else bg.lighter(105)
    grad = QLinearGradient(0, 0, 0, rect.height())
    grad.setColorAt(0.0, top)
    grad.setColorAt(1.0, bg)
    painter.setBrush(grad)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(rect, radius, radius)

    painter.setBrush(Qt.NoBrush)
    if is_dark:
        painter.setPen(QPen(QColor(80, 80, 80, 255), 1))
        # Crisp hairline sitting exactly on the pill's edge: inset the path
        # by half the pen width in floating coords (and shrink the radius by
        # the same) so the 1px line aligns to device pixels — left/right
        # symmetric at any DPI scaling and never reads as a stray "line
        # inside the top edge".
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5),
                                radius - 0.5, radius - 0.5)


def _blend(c1, c2, t):
    """Linearly interpolate two QColors by t in [0, 1]."""
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


def _to_hex(c):
    return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"


class GlassIconButton(QPushButton):
    """Icon button with a smooth hover / press / toggle animation.

    Hover and press fade a translucent highlight (the system accent color —
    light blue on Windows) in over 180 ms, the icon color cross-fades to
    that accent, and a click nudges the button 1 px down (the reference
    AnimatedButton pattern). A persistent lit state marks toggles that are
    ON. Emits `rightClicked` on right-click.
    """

    rightClicked = Signal()

    def __init__(self, svg_content, tooltip="", size=44, icon_size=22,
                 hover_color=None, hover_bg_color=None, colorize_icon=True,
                 parent=None):
        super().__init__(parent)
        self._svg = svg_content
        self._size = size
        self._normal = QApplication.palette().color(QPalette.WindowText)
        self._hover = QColor(hover_color) if hover_color else \
            QApplication.palette().color(QPalette.Highlight)
        self._hover_bg = hover_bg_color or \
            QApplication.palette().color(QPalette.Highlight)
        self._icon_size = icon_size
        # When False the SVG icon keeps its original "window text" color under
        # hover/press too — only the background plate animates. Used by the
        # capsule so its icons never take on the accent tint.
        self._colorize_icon = bool(colorize_icon)
        self._original_pos = None
        self._is_pressed = False
        self._active = False
        self._t = 0.0  # interaction intensity: 0 = idle, 1 = fully lit

        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.PreventContextMenu)
        self.setToolTip(tooltip)
        # Flat + no focus so Qt's native pressed/background drawing is fully
        # suppressed — the background is painted ourselves in paintEvent.
        # Using paintEvent instead of per-frame setStyleSheet avoids relayout
        # and the graphics-effect buffer flicker that caused a stray blue
        # plate to flash when a hover ended.
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self._pix_cache = {}  # (argb,size) -> QPixmap of the icon
        self._alpha = 0       # current plate alpha, resolved on each frame
        self._icon_color = self._normal

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._apply_visuals)
        self._apply_visuals()

    # ----- animation -----

    def _animate_to(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(target)
        self._anim.start()

    # Hover/press only ever drive the fade for *inactive* buttons. An active
    # button (clipboard on, annotation mode selected) keeps a fixed stable
    # base plate that must NOT react to hover — otherwise the hover animation
    # would wobble the "selected" indicator's opacity.
    ACTIVE_ALPHA = 150
    HOVER_ALPHA = 82

    def _apply_visuals(self, value=None):
        """Recompute the current plate alpha + icon color from state, then
        repaint. No stylesheet magic — just a repaint, so the fade is
        glitch-free."""
        if value is not None:
            self._t = float(value)
        if self._active:
            # Stable plate: fixed accent plate, but the icon keeps its
            # original "window text" color (white in dark / black in light).
            # A blue icon on the blue plate would be invisible, so selected
            # modes must keep high contrast against the lit background.
            self._alpha = self.ACTIVE_ALPHA
            self._icon_color = self._normal
        else:
            self._alpha = int(self.HOVER_ALPHA * self._t)
            if self._colorize_icon:
                self._icon_color = _blend(self._normal, self._hover, self._t)
            else:
                self._icon_color = self._normal
        self.update()

    def set_active(self, active):
        """Persistent lit background to mark a toggle that is ON.

        Applied instantly (no shared fade): the active plate has a fixed
        opacity, so state changes can't collide with an in-flight hover
        animation and produce a blue flash."""
        self._active = bool(active)
        self._anim.stop()
        if self._active:
            self._t = 1.0
        else:
            self._t = 1.0 if self.underMouse() else 0.0
        self._apply_visuals()

    def set_svg(self, svg_content):
        """Swap the icon glyph (e.g. pause -> play) and drop the cached pixmaps."""
        self._svg = svg_content
        self._pix_cache.clear()
        self.update()

    # ----- painting -----

    def _icon_pixmap(self, color, size):
        key = (color.rgba(), size)
        pm = self._pix_cache.get(key)
        if pm is None:
            pm = make_pixmap(self._svg, _to_hex(color), size)
            self._pix_cache[key] = pm
        return pm

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        alpha = self._alpha
        # Background plate: a translucent "glass chip" that fades in with the
        # interaction intensity — a uniform pale-blue tint (frosted glass)
        # plus a near-white hairline edge, so a hover reads as a small
        # translucent pane instead of a flat tint.
        if alpha > 0:
            r = self._size // 3
            # Theme-aware plate brightness: a dark pill can carry a slightly
            # deeper tint, a light pill needs a brighter one to keep the
            # glass readable against the light background.
            dark = QApplication.palette().color(QPalette.Window).lightness() < 128
            lift = 115 if dark else 145
            plate = QColor(self._hover_bg).lighter(lift)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(plate.red(), plate.green(), plate.blue(), alpha))
            p.drawRoundedRect(rect, r, r)
            # Glass edge: thin near-white hairline on an even-sized inset so
            # the border stays crisp and left/right symmetric at any DPI
            # scaling (an odd inset flattens the left/top arcs).
            p.setBrush(Qt.NoBrush)
            edge = min(255, int(alpha * 0.35) + 10)
            p.setPen(QPen(QColor(255, 255, 255, edge), 1))
            p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), r - 1, r - 1)
        # Icon, centered via the DPR-aware cached pixmap (centre on its
        # LOGICAL size so a DPR-tagged pixmap isn't offset by the scale).
        pm = self._icon_pixmap(self._icon_color, self._icon_size)
        dpr = pm.devicePixelRatio() or 1.0
        w, h = pm.width() / dpr, pm.height() / dpr
        x = max(0.0, (rect.width() - w) / 2.0)
        y = max(0.0, (rect.height() - h) / 2.0)
        p.drawPixmap(QPointF(x, y), pm)
        p.end()

    # ----- events -----

    def enterEvent(self, event):
        if not self._active:
            self._animate_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._active:
            super().leaveEvent(event)
            return
        if not self._is_pressed:
            self._animate_to(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.rightClicked.emit()
            return
        if event.button() == Qt.LeftButton:
            self._original_pos = self.pos()
            self._is_pressed = True
            self._animate_to(1.0)
            super().mousePressEvent(event)
            if self._original_pos is not None:
                self.move(int(self._original_pos.x()),
                          int(self._original_pos.y() + 1))
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._is_pressed = False
            if self._original_pos is not None:
                self.move(self._original_pos)
            self._animate_to(1.0 if self.underMouse() else 0.0)
            super().mouseReleaseEvent(event)
        else:
            super().mouseReleaseEvent(event)

    def event(self, event):
        if event.type() == QEvent.LayoutRequest:
            if not self._is_pressed:
                self._original_pos = None
        return super().event(event)
