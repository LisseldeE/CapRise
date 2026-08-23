"""Region-select translation.

Flow: full-screen dark overlay -> drag to select a rectangular region ->
OCR (Windows built-in engine via WinRT) + online translation (Google's free
endpoint, no API key) run in a background daemon thread. A rounded card fades
in below the selection: it first plays the state-1 scanning animation
(theme-aware), then resizes to show only the translated result with a copy
icon pinned to its top-right corner.

The network/OCR work runs in a plain daemon thread and delivers results to the
Qt main thread through a QObject signal bridge — the same pattern used by
clipboard_network.py, so no QThread lifecycle management is required.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import (
    Qt, QRect, QRectF, QObject, Signal, QTimer, QPointF, QBuffer, QByteArray,
    QPropertyAnimation, QEasingCurve, QSize
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QPixmap, QIcon, QGuiApplication, QPalette,
    QLinearGradient, QPainterPath, QFontMetrics
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QApplication,
    QGraphicsOpacityEffect, QScrollArea, QFrame
)
from PySide6.QtSvg import QSvgRenderer

from modules.overlay import BaseOverlay, pixel_source, draw_snapshot
from modules.i18n import I18n
from modules.config import Config
from modules.icons import ICON_COPY, ICON_CHECK

# Google free translation endpoints (no API key). Multiple hosts so a
# transient network failure on one falls back to the other.
GOOGLE_URLS = [
    "https://translate.googleapis.com/translate_a/single",
    "https://translate.google.com/translate_a/single",
]

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0")

# Minimum delay between outgoing translation requests, shared across every
# worker thread. Google's free endpoint rate-limits unauthenticated requests;
# spacing them out prevents the bursts that trip HTTP 429 and can get the IP
# temporarily blocked.
MIN_REQUEST_INTERVAL = 0.6

_last_request_ts = 0.0
_request_lock = threading.Lock()


def _throttle():
    """Space translation requests at least MIN_REQUEST_INTERVAL apart."""
    global _last_request_ts
    with _request_lock:
        now = time.monotonic()
        wait = MIN_REQUEST_INTERVAL - (now - _last_request_ts)
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


def _selection_color():
    """Return border color for selection rect based on theme.
    Dark mode -> light gray, Light mode -> dark gray."""
    bg = QApplication.palette().color(QPalette.Window)
    is_dark = bg.lightness() < 128
    return QColor(200, 200, 200) if is_dark else QColor(80, 80, 80)


def _make_icon(svg_content, color, size=16):
    """Create a QIcon from an SVG string with theme color substitution.

    Rasterised on a devicePixelRatio-scaled buffer so it stays crisp on
    scaled-Windows (HiDPI) displays."""
    colored = svg_content.replace('stroke="currentColor"', f'stroke="{color}"')
    renderer = QSvgRenderer(QByteArray(colored.encode()))
    dpr = QGuiApplication.primaryScreen().devicePixelRatio() or 1.0
    pixmap = QPixmap(int(size * dpr), int(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)


# ----- translation (pure functions, no Qt) -----

def _google_translate(text, lang):
    """Translate via Google's free endpoint. No API key needed.

    Retries across the known hosts because the endpoint is flaky on some
    networks (connection succeeds but the read times out). Every request is
    throttled so rapid successive translations don't trip the rate limit;
    on HTTP 429 the code backs off exponentially (1s, 2s) before retrying
    instead of hammering the endpoint and risking an IP block."""
    params = urllib.parse.urlencode({
        "client": "gtx", "sl": "auto", "tl": lang, "dt": "t", "q": text,
    })
    errors = []
    for attempt in range(2):  # two passes over the host list
        for url in GOOGLE_URLS:
            _throttle()
            try:
                req = urllib.request.Request(
                    f"{url}?{params}", headers={"User-Agent": _UA})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                segs = [block[0] for block in data[0] if block and block[0]]
                return "".join(segs)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    # Rate-limited: back off before the next attempt.
                    time.sleep(1 << attempt)  # 1s, then 2s
                    errors.append(f"HTTP 429 (rate limited): {url}")
                else:
                    errors.append(f"{e}")
            except Exception as e:  # noqa: BLE001 - try next host/attempt
                errors.append(f"{e}")
    raise RuntimeError("; ".join(errors[-3:]) or "google translate failed")


def translate_text(text, lang):
    """Translate text to the target language via Google's free endpoint."""
    return _google_translate(text, lang)


# ----- OCR (Windows built-in engine via the WinRT API directly) -----
# natocr was tried first but its Windows backend is incompatible with the
# winrt 3.x packages (Language moved to winrt.windows.globalization), so we
# call Windows.Media.Ocr ourselves. Same underlying engine, no fragile
# wrapper. The imports are lazy so the app still runs if WinRT is missing.

def _pixmap_to_png(pixmap):
    """Convert a QPixmap to PNG bytes (must be called on the GUI thread)."""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    pixmap.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def ocr_image(png_bytes):
    """Recognize text from PNG bytes using the Windows built-in OCR engine."""
    import asyncio
    return asyncio.run(_ocr_async(png_bytes))


async def _ocr_async(png_bytes):
    import winrt.windows.media.ocr as wocr
    import winrt.windows.graphics.imaging as imaging
    import winrt.windows.storage.streams as streams
    import winrt.windows.globalization as globalization

    stream = streams.InMemoryRandomAccessStream()
    writer = streams.DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)

    decoder = await imaging.BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    # English first (fits the 英译中 use case), fall back to the user's
    # profile language pack if the en-US pack is not installed.
    engine = wocr.OcrEngine.try_create_from_language(
        globalization.Language("en-US"))
    if engine is None:
        engine = wocr.OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("no Windows OCR engine available")

    result = await engine.recognize_async(bitmap)
    lines = [line.text for line in result.lines if line.text.strip()]
    return "\n".join(lines).strip()


# ----- loading animation (state 1: one-way scan + pulsing trail, theme-aware) -----

class LoadingWidget(QWidget):
    """State-1 loader from Lisselde_E-loading.py, adapted to the system theme.

    State 1 = a one-way left-to-right scan beam plus a pulsing trail beneath.
    Both are drawn as true parallelograms (top edge shifted right by the skew
    — not inset on both sides, which would render a trapezoid)."""

    SCAN_H = 8
    TRAIL_H = 3
    GAP = 6
    SCAN_W = 80

    def __init__(self, parent=None):
        super().__init__(parent)
        skew = self.SCAN_H * 0.36
        # +1 avoids clipping the top-right corner of the skewed track, exactly
        # like the reference ScannerWidget (int(80 + skew) + 1).
        self.setFixedSize(int(self.SCAN_W + skew) + 1, self.SCAN_H + self.GAP + self.TRAIL_H)
        self._progress = 0.0
        self._trail_delays = [0.0, 0.10, 0.20, 0.30]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._progress += 16 / 1200.0
        if self._progress >= 1.0:
            self._progress = 0.0
        self.update()

    def _scan_path(self):
        skew = self.SCAN_H * 0.36
        w = self.SCAN_W
        path = QPainterPath()
        path.moveTo(skew, 0)          # top-left
        path.lineTo(w + skew, 0)      # top-right (shifted right by skew)
        path.lineTo(w, self.SCAN_H)   # bottom-right
        path.lineTo(0, self.SCAN_H)   # bottom-left
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bg = QApplication.palette().color(QPalette.Window)
        painter.fillPath(self._scan_path(), QColor(bg.red(), bg.green(), bg.blue(), 200))
        painter.setClipPath(self._scan_path())

        # One-way left->right scan beam (state 1, no reverse loop).
        scan_pos = -30 + self._progress * 160
        beam_w = self.SCAN_W * 0.3
        skew = self.SCAN_H * 0.36
        bx = (scan_pos / 100.0) * self.SCAN_W - beam_w / 2 + skew
        ac = QApplication.palette().color(QPalette.Highlight)
        grad = QLinearGradient(QPointF(bx, 0), QPointF(bx + beam_w, 0))
        grad.setColorAt(0.0, QColor(ac.red(), ac.green(), ac.blue(), 0))
        grad.setColorAt(0.5, QColor(ac.red(), ac.green(), ac.blue(), 230))
        grad.setColorAt(1.0, QColor(ac.red(), ac.green(), ac.blue(), 0))
        painter.fillRect(QRectF(bx, 0, beam_w, self.SCAN_H), grad)
        painter.setClipping(False)

        self._paint_trail(painter)

    def _paint_trail(self, painter):
        y = self.SCAN_H + self.GAP
        h = self.TRAIL_H
        tw = 12
        gap = 4
        skew = h * 0.36
        # Center the trail beneath the scan track — mirrors the reference,
        # which centers its TrailWidget under the scanner. This keeps the
        # pulsing blocks in line with the scan beam instead of hugging the
        # left edge.
        span = 4 * tw + 3 * gap + skew
        start_x = (self.width() - span) / 2.0
        ac = QApplication.palette().color(QPalette.Highlight)
        dim = QApplication.palette().color(QPalette.Window)
        for i in range(4):
            phase = (self._progress - self._trail_delays[i]) % 1.0
            if phase < 0.35:
                pulse = self._ease_in_out(phase / 0.35)
            elif phase < 0.7:
                pulse = self._ease_in_out(1.0 - (phase - 0.35) / 0.35)
            else:
                pulse = 0.0
            opacity = 0.05 + 0.95 * pulse
            if pulse > 0.3:
                color = QColor(ac.red(), ac.green(), ac.blue(), int(255 * opacity))
            else:
                color = QColor(dim.red(), dim.green(), dim.blue(), int(255 * opacity))
            x = start_x + i * (tw + gap)
            path = QPainterPath()
            path.moveTo(x + skew, y)
            path.lineTo(x + tw + skew, y)
            path.lineTo(x + tw, y + h)
            path.lineTo(x, y + h)
            path.closeSubpath()
            painter.fillPath(path, color)

    def _ease_in_out(self, t):
        if t < 0.5:
            return 2 * t * t
        return 1 - pow(-2 * t + 2, 2) / 2


# ----- signal bridge for the background daemon thread -----

class _TranslateSignals(QObject):
    ok = Signal(str)
    failed = Signal(str, str)  # code: "no_text" | "error", detail


# ----- floating result panel -----

class TranslateResultPanel(QWidget):
    """Rounded, opaque card anchored near the selection rect.

    It fades in over 300 ms. States: loading (state-1 scanner) -> result
    (translated text + copy icon at the top-right) or error (message +
    retry). The card re-sizes to its content whenever the state changes; long
    translations scroll inside the card instead of stretching it."""

    ICON_BTN = 26  # copy button size
    ICON_SIZE = 18
    RADIUS = 12
    MAX_RESULT_H = 300  # cap on the result scroll area; longer text scrolls

    def __init__(self, overlay):
        super().__init__(overlay)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._state = "loading"
        self._copied_timer = None
        self._build_ui()
        self._fade_in()

    # ----- appearance helpers -----

    def _text_color(self, role):
        c = QApplication.palette().color(role)
        return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"

    def _accent_rgba(self, alpha):
        c = QApplication.palette().color(QPalette.Highlight)
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"

    def _btn_style(self):
        return f"""
            QPushButton {{
                background-color: {self._accent_rgba(230)};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {self._accent_rgba(200)}; }}
            QPushButton:pressed {{ padding-top: 7px; padding-bottom: 5px; }}
        """

    def _icon_btn_style(self):
        return f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 7px;
            }}
            QPushButton:hover {{ background-color: {self._accent_rgba(30)}; }}
            QPushButton:pressed {{ background-color: {self._accent_rgba(60)}; }}
        """

    def _scroll_style(self):
        handle = self._text_color(QPalette.Mid)
        hover = self._text_color(QPalette.Highlight)
        return f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {handle}; border-radius: 4px; min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {hover}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """

    # ----- card painting -----

    def _fade_in(self):
        """Fade the card in over 300 ms (user prefers 300 over 500)."""
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._fade_anim = anim  # keep a reference alive

    def _card_colors(self):
        bg = QApplication.palette().color(QPalette.Window)
        border = QApplication.palette().color(QPalette.Mid)
        # Fully opaque card body — no see-through translucency. WA_Translucent
        # Background stays on only so the rounded corners remain transparent.
        return (QColor(bg.red(), bg.green(), bg.blue(), 255),
                QColor(border.red(), border.green(), border.blue(), 255))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg, border = self._card_colors()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

    # ----- UI construction -----

    def _build_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 12, 14, 12)
        self.layout.setSpacing(8)

        # Header: copy icon pinned to the top-right corner of the card.
        self.copy_btn = QPushButton(self)
        self.copy_btn.setFixedSize(self.ICON_BTN, self.ICON_BTN)
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setStyleSheet(self._icon_btn_style())
        self.copy_btn.clicked.connect(self._on_copy)
        self.copy_btn.hide()
        self._set_copy_icon(ICON_COPY, I18n.tr("copy"))
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addStretch()
        header.addWidget(self.copy_btn)
        self.layout.addLayout(header)

        # Loading: scanner centered + label below.
        load_box = QWidget(self)
        load_lay = QVBoxLayout(load_box)
        load_lay.setContentsMargins(0, 0, 0, 0)
        load_lay.setSpacing(6)
        self.loading = LoadingWidget(load_box)
        load_lay.addWidget(self.loading, 0, Qt.AlignCenter)
        self.loading_label = QLabel(I18n.tr("translate_loading"), load_box)
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet(
            f"color: {self._text_color(QPalette.PlaceholderText)}; font-size: 12px;")
        load_lay.addWidget(self.loading_label)
        self.layout.addWidget(load_box)

        # Result: translated text (selectable), inside a scroll area so long
        # translations scroll instead of being clipped by the card height.
        self.result_label = QLabel(self)
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.result_label.setStyleSheet(
            f"color: {self._text_color(QPalette.WindowText)}; font-size: 14px;")
        self.result_scroll = QScrollArea(self)
        # Manual sizing: the scroll area must not auto-resize the content down
        # to the viewport, or long text could never scroll.
        self.result_scroll.setWidgetResizable(False)
        self.result_scroll.setFrameShape(QFrame.NoFrame)
        self.result_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.result_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.result_scroll.setStyleSheet(self._scroll_style())
        # The label lives inside a plain container so Qt's layout honours the
        # word-wrapped height (heightForWidth); a bare QLabel as the scroll
        # widget does not grow reliably with wrapped text.
        self._result_wrap = QWidget(self.result_scroll)
        wrap_lay = QVBoxLayout(self._result_wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.addWidget(self.result_label)
        self.result_scroll.setWidget(self._result_wrap)
        self.result_scroll.hide()
        self.layout.addWidget(self.result_scroll)

        # Error: message + retry button row.
        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(
            f"color: {self._text_color(QPalette.WindowText)}; font-size: 13px;")
        self.error_label.hide()
        self.layout.addWidget(self.error_label)

        self.retry_btn = QPushButton(I18n.tr("translate_retry"), self)
        self.retry_btn.setStyleSheet(self._btn_style())
        self.retry_btn.clicked.connect(self._on_retry)
        self.retry_btn.hide()
        retry_row = QHBoxLayout()
        retry_row.addStretch()
        retry_row.addWidget(self.retry_btn)
        self.layout.addLayout(retry_row)

    def _set_copy_icon(self, svg, tooltip):
        self.copy_btn.setToolTip(tooltip)
        color = self._text_color(QPalette.WindowText)
        self.copy_btn.setIcon(_make_icon(svg, color, self.ICON_SIZE))
        self.copy_btn.setIconSize(QSize(self.ICON_SIZE, self.ICON_SIZE))

    # ----- states -----

    def show_state_loading(self):
        self._state = "loading"
        self.loading.show()
        self.loading_label.show()
        self.result_scroll.hide()
        self.copy_btn.hide()
        self.error_label.hide()
        self.retry_btn.hide()

    def show_state_result(self, text):
        self._state = "result"
        self.result_label.setText(text)
        self.loading.hide()
        self.loading_label.hide()
        self.error_label.hide()
        self.retry_btn.hide()
        self.result_scroll.show()
        self.result_scroll.verticalScrollBar().setValue(0)  # start from the top
        self._set_copy_icon(ICON_COPY, I18n.tr("copy"))
        self.copy_btn.show()
        self._relayout()

    def show_state_error(self, code, detail=""):
        self._state = "error"
        if code == "no_text":
            msg = I18n.tr("translate_no_text")
        elif detail:
            # Surface the concrete failure reason (e.g. a network/timeout
            # error from the translator or OCR) instead of a bare "failed".
            # Cap the length so a verbose exception can't balloon the card.
            if len(detail) > 160:
                detail = detail[:160] + "…"
            msg = I18n.tr("translate_failed_detail").format(detail=detail)
        else:
            msg = I18n.tr("translate_failed")
        self.error_label.setText(msg)
        self.loading.hide()
        self.loading_label.hide()
        self.result_scroll.hide()
        self.copy_btn.hide()
        self.error_label.show()
        self.retry_btn.show()
        self._relayout()

    # ----- geometry -----

    def _content_width(self, base_w):
        """Card width for the current state — grows with the content."""
        m = self.layout.contentsMargins()
        if self._state == "result":
            fm = QFontMetrics(self.result_label.font())
            adv = max(fm.horizontalAdvance(line)
                      for line in self.result_label.text().split("\n"))
            return max(240, min(adv + m.left() + m.right() + 12, 520))
        if self._state == "error":
            fm = QFontMetrics(self.error_label.font())
            adv = fm.horizontalAdvance(self.error_label.text())
            return max(240, min(adv + m.left() + m.right() + 12, 520))
        # loading: sized from the selection, clamped to a readable band.
        return max(280, min(base_w, 560))

    def _fit_result_scroll(self, width, max_h):
        """Size the result scroll area to the wrapped text height.

        Short text grows the scroll area to fit. Long text is capped at max_h
        and scrolls. The content is sized from the label's own heightForWidth
        (QFontMetrics.boundingRect under-estimates wrapped CJK height), so the
        measured height exactly matches what the label renders."""
        m = self.layout.contentsMargins()
        inner = width - m.left() - m.right()
        self.result_label.setFixedWidth(inner)
        rh = self.result_label.heightForWidth(inner)
        if rh <= 0:
            rh = 20
        self.result_label.setFixedHeight(rh)
        self._result_wrap.setFixedSize(inner, rh)
        self.result_scroll.setFixedHeight(max(20, min(rh, max_h)))

    def _relayout(self):
        """Re-size to the current content and re-anchor near the selection."""
        sel = getattr(self.parent(), "sel_rect", None)
        if sel:
            self.place_near(sel)

    def place_near(self, sel):
        """Size the card to its content and anchor it near the selection rect.

        Short content grows the card to fit; long content is capped at
        MAX_RESULT_H and scrolls inside the card, keeping the margins even.
        Multi-monitor safe."""
        overlay = self.parent()
        ov_geo = overlay.geometry()
        center_global = sel.center() + overlay.pos()
        screen = QGuiApplication.screenAt(center_global) or QGuiApplication.primaryScreen()
        s = screen.availableGeometry()
        # Screen bounds converted into overlay-local coordinates.
        left = s.left() - ov_geo.left()
        right = s.right() - ov_geo.left()
        top = s.top() - ov_geo.top()
        bottom = s.bottom() - ov_geo.top()
        avail_h = max(40, bottom - top - 16)

        w = min(self._content_width(sel.width()), max(140, right - left - 16))
        m = self.layout.contentsMargins()
        spacing = self.layout.spacing()

        if self._state == "result":
            # Leave room for the copy-icon header above the scrollable text.
            # The scroll area is capped so a long translation scrolls inside a
            # fixed-height card (with equal margins) instead of stretching it
            # across the whole screen.
            scroll_max = avail_h - m.top() - self.ICON_BTN - spacing - m.bottom()
            scroll_max = min(scroll_max, self.MAX_RESULT_H)
            self._fit_result_scroll(w, scroll_max)
            h = m.top() + self.ICON_BTN + spacing + self.result_scroll.height() + m.bottom()
        elif self._state == "error":
            fm = QFontMetrics(self.error_label.font())
            rh = fm.boundingRect(
                QRect(0, 0, w - m.left() - m.right(), 10000), Qt.TextWordWrap,
                self.error_label.text()).height()
            # The (hidden) copy-header row still consumes one layout spacing
            # above the message, so count two spacings total (header->message
            # and message->retry). Otherwise the card comes up short and the
            # retry button is squeezed below its content height, clipping the
            # label text vertically.
            h = (m.top() + spacing + rh + spacing
                 + self.retry_btn.sizeHint().height() + m.bottom())
        else:  # loading
            h = (m.top() + spacing + self.loading.height() + 6 + 18
                 + m.bottom())
        h = min(h, avail_h)

        self.setFixedSize(w, h)
        x = sel.center().x() - w // 2
        x = max(left + 8, min(x, right - w - 8))
        y = sel.bottom() + 10
        if y + h > bottom - 8:
            y = sel.top() - h - 10
        if y < top + 8:
            y = top + 8
        # Last resort: if the card still hangs off the bottom of the screen,
        # shrink it so it fits — the result scroll area then scrolls instead
        # of having its lower content cut off.
        if y + h > bottom - 8:
            h = bottom - 8 - y
            self.setFixedHeight(h)
        self.move(int(x), int(y))

    # ----- interactions -----

    def mousePressEvent(self, event):
        # Swallow clicks on the panel so they don't close the overlay.
        event.accept()

    def _on_copy(self):
        QApplication.clipboard().setText(self.result_label.text())
        self._set_copy_icon(ICON_CHECK, I18n.tr("copied"))
        if self._copied_timer:
            self._copied_timer.stop()
        self._copied_timer = QTimer(self)
        self._copied_timer.setSingleShot(True)
        self._copied_timer.timeout.connect(
            lambda: self._set_copy_icon(ICON_COPY, I18n.tr("copy")))
        self._copied_timer.start(1200)

    def _on_retry(self):
        self.show_state_loading()
        self.parent()._start_worker()


# ----- overlay -----

class TranslateOverlay(BaseOverlay):
    """Full-screen overlay: select a region, then OCR + translate it."""

    def __init__(self, parent=None):
        # Base class first — creating QObject children before super().__init__
        # raises "base class not called" in PySide6/shiboken.
        super().__init__(parent)

        self.desktop_pixmap = QGuiApplication.primaryScreen().grabWindow(0)
        self.start_point = None
        self.end_point = None
        self.is_dragging = False
        self.sel_rect = None
        self.panel = None
        self._captured_png = None
        self._target_lang = Config().get("translate_target_lang", "zh-CN")

        self._signals = _TranslateSignals(self)
        self._signals.ok.connect(self._on_result_ok)
        self._signals.failed.connect(self._on_result_failed)

        self.activateWindow()
        self.setFocus()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))

        rect = None
        if self.is_dragging and self.start_point and self.end_point:
            rect = QRect(self.start_point, self.end_point).normalized()
        elif self.sel_rect:
            rect = self.sel_rect

        if rect:
            # 1:1 physical-pixel paint so HiDPI scaling never makes the text
            # inside the selection wobble while dragging.
            draw_snapshot(painter, self.desktop_pixmap, rect)
            painter.setPen(QPen(_selection_color(), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.sel_rect is not None:
                # A selection is already active — clicking the blank overlay
                # dismisses the whole translation session.
                self.close_overlay()
                return
            self.start_point = event.position().toPoint()
            self.end_point = self.start_point
            self.is_dragging = True
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            self.end_point = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_dragging:
            self.is_dragging = False
            sel = QRect(self.start_point, self.end_point).normalized()
            self.start_point = None
            self.end_point = None
            if sel.width() > 5 and sel.height() > 5:
                self._start_translate(sel)
            else:
                self.close_overlay()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.is_dragging:
                self.is_dragging = False
                self.start_point = None
                self.end_point = None
                self.update()
            else:
                self.close_overlay()
            return
        super().keyPressEvent(event)

    # ----- translation flow -----

    def _start_translate(self, sel):
        self.sel_rect = sel
        captured = self.desktop_pixmap.copy(
            pixel_source(self.desktop_pixmap, sel))
        self._captured_png = _pixmap_to_png(captured)
        self.update()

        self.panel = TranslateResultPanel(self)
        self.panel.show_state_loading()
        self.panel.place_near(sel)
        self.panel.show()
        self.panel.raise_()
        self._start_worker()

    def _start_worker(self):
        threading.Thread(
            target=self._run_translate,
            args=(self._captured_png, self._target_lang),
            daemon=True,
        ).start()

    def _emit_safe(self, signal_name, *args):
        """Emit a signal from the worker thread only if the bridge is alive.

        The overlay can be closed (and its QObject children deleted) while
        OCR/translation is still running — e.g. the user clicks the blank
        overlay or presses ESC mid-translation. Emitting on the deleted
        bridge would raise "RuntimeError: Signal source has been deleted",
        so swallow it: there is no UI left to notify."""
        try:
            sig = getattr(self._signals, signal_name, None)
            if sig is None:
                return
            sig.emit(*args)
        except RuntimeError:
            pass  # bridge deleted underneath us — nothing to notify

    def _run_translate(self, png, target):
        try:
            text = ocr_image(png)
            if not text:
                self._emit_safe("failed", "no_text", "")
                return
            translated = translate_text(text, target)
            if not translated or not translated.strip():
                self._emit_safe("failed", "error", "")
                return
            self._emit_safe("ok", translated.strip())
        except Exception as e:  # noqa: BLE001 - surface the concrete reason
            self._emit_safe("failed", "error", str(e))

    def _on_result_ok(self, text):
        if self.panel and self.panel.isVisible():
            self.panel.show_state_result(text)

    def _on_result_failed(self, code, detail):
        if self.panel and self.panel.isVisible():
            self.panel.show_state_error(code, detail)
