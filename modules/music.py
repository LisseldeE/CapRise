"""
音乐胶囊
读取 Windows SMTC 会话，展示当前曲目并控制播放
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import asyncio
import threading
import time

from PySide6.QtCore import (
    Qt, QObject, QTimer, QPoint, QPointF, QRectF, QPropertyAnimation,
    QEasingCurve, Signal, Property
)
from PySide6.QtGui import (
    QPainter, QPainterPath, QColor, QFont, QFontMetricsF, QImage, QPalette
)
from PySide6.QtWidgets import QWidget, QApplication

from modules.family import FamilyWindowRegistry
from modules.icons import (
    ICON_MUSIC, ICON_PREV, ICON_NEXT, ICON_PAUSE, ICON_PLAY
)
from modules.i18n import I18n
from modules.widgets import (
    GlassIconButton, make_pixmap, paint_pill, screen_dpr
)

# SMTC playback status values (winrt enum ints) — compared numerically so the
# module imports cleanly even when the media-control package is absent.
_SMTC_PLAYING = 4

# Poll cadence. Fast enough that a track change feels instant, slow enough to
# stay off the CPU radar (each poll is a couple of WinRT calls).
POLL_S = 0.8

# A reported position further than this from our extrapolated one is a seek
# (or a track change) and re-anchors the progress clock; anything closer is
# ignored so the bar keeps gliding smoothly instead of snapping to a player
# that only updates its position occasionally.
SEEK_MS = 1500


def _fmt_time(ms):
    """Format milliseconds as m:ss (h:mm:ss past an hour); '--:--' if unknown."""
    if not ms or ms < 0:
        return "--:--"
    total = int(ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class MusicManager(QObject):
    """Polls Windows SMTC on a worker thread and emits the current track.

    `state_changed` carries either a dict describing the active session or
    None when nothing is loaded. It is emitted on the GUI thread (Qt queues
    cross-thread emissions), so receivers can touch widgets directly.
    """

    state_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._loop = None
        self._wake = None
        self._ready = threading.Event()
        self._stop_requested = False
        self._last_state = None
        # Touched only from the worker loop thread.
        self._session_mgr = None
        self._session = None
        self._art_key = None
        self._art_bytes = b""

    # ----- lifecycle -----

    def start(self):
        """Start polling. Idempotent."""
        if self._thread is not None:
            return
        self._stop_requested = False
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._thread_main, name="CapRiseMusic", daemon=True)
        self._thread.start()
        # Wait for the loop to exist so an immediate control call (a click
        # right after enabling) can be scheduled instead of being dropped.
        self._ready.wait(timeout=3.0)

    def stop(self):
        """Stop polling and join the worker. Idempotent."""
        self._stop_requested = True
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._loop = None
        self._wake = None
        self._session_mgr = None
        self._session = None
        self._art_key = None
        self._art_bytes = b""
        if self._last_state is not None:
            self._last_state = None
            self.state_changed.emit(None)

    # ----- transport controls -----

    def play_pause(self):
        self._post(self._cmd_play_pause())

    def next_track(self):
        self._post(self._cmd_skip(next_track=True))

    def previous_track(self):
        self._post(self._cmd_skip(next_track=False))

    def _post(self, coro):
        """Schedule a control coroutine on the worker loop.

        The coroutine re-polls when it finishes so the pill reflects the new
        state immediately instead of after the next scheduled tick."""
        loop = self._loop
        if loop is None:
            coro.close()
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()

    async def _cmd_play_pause(self):
        session = self._session
        if session is None:
            return
        try:
            status = int(session.get_playback_info().playback_status)
        except Exception:
            return
        try:
            if status == _SMTC_PLAYING:
                await session.try_pause_async()
            else:
                await session.try_play_async()
        except Exception:
            pass
        if self._wake is not None:
            self._wake.set()

    async def _cmd_skip(self, next_track):
        session = self._session
        if session is None:
            return
        try:
            if next_track:
                await session.try_skip_next_async()
            else:
                await session.try_skip_previous_async()
        except Exception:
            pass
        if self._wake is not None:
            self._wake.set()

    # ----- worker -----

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._run())
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _run(self):
        self._wake = asyncio.Event()
        self._ready.set()
        while not self._stop_requested:
            try:
                state = await self._poll()
            except Exception:
                # A transient WinRT failure must not blank the pill, and must
                # never kill the worker — keep the last known track.
                state = self._last_state
            if state != self._last_state:
                self._last_state = state
                self.state_changed.emit(state)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=POLL_S)
                self._wake.clear()
            except asyncio.TimeoutError:
                pass

    async def _poll(self):
        """Read the current session and return a state dict (or None)."""
        import winrt.windows.media.control as wmc

        if self._session_mgr is None:
            self._session_mgr = \
                await wmc.GlobalSystemMediaTransportControlsSessionManager \
                .request_async()

        session = self._session_mgr.get_current_session()
        self._session = session
        if session is None:
            return None

        props = await session.try_get_media_properties_async()
        title = (getattr(props, "title", "") or "").strip()
        artist = (getattr(props, "artist", "") or "").strip()
        album = (getattr(props, "album_title", "") or "").strip()
        if not title and not artist:
            return None

        try:
            status = int(session.get_playback_info().playback_status)
        except Exception:
            status = 0
        playing = status == _SMTC_PLAYING

        position_ms, duration_ms = 0, 0
        try:
            tl = session.get_timeline_properties()
            position_ms = int(tl.position.total_seconds() * 1000)
            duration_ms = int(tl.end_time.total_seconds() * 1000)
            if duration_ms <= 0:
                # 部分播放器只填 max_seek_time，作为总时长兜底。
                duration_ms = int(tl.max_seek_time.total_seconds() * 1000)
        except Exception:
            pass

        # Artwork is read once per track. A track with no artwork simply
        # leaves the cache empty and the pill draws its music-note badge.
        art_key = f"{title}\x1f{album}\x1f{artist}"
        if art_key != self._art_key or not self._art_bytes:
            try:
                ref = getattr(props, "thumbnail", None)
            except Exception:
                ref = None
            data = b""
            if ref is not None:
                try:
                    data = await self._read_thumbnail(ref)
                except Exception:
                    data = b""
            self._art_key = art_key
            self._art_bytes = data

        return {
            "title": title or artist,
            "artist": artist,
            "album": album,
            "playing": playing,
            "position_ms": position_ms,
            "duration_ms": duration_ms,
            "art_key": self._art_key,
            "art_bytes": self._art_bytes,
        }

    @staticmethod
    async def _read_thumbnail(ref):
        """Read a thumbnail stream reference into raw image bytes."""
        import winrt.windows.storage.streams as streams

        stream = await ref.open_read_async()
        size = int(stream.size)
        if size <= 0:
            return b""
        reader = streams.DataReader(stream.get_input_stream_at(0))
        await reader.load_async(size)
        buf = reader.read_buffer(size)
        try:
            return bytes(buf)
        except TypeError:
            # Some projections hand back a list of ints instead of a buffer.
            return bytes(bytearray(buf))


class MarqueeLabel(QWidget):
    """Single-line label that scrolls its text when it does not fit.

    Scrolls out to the left, then the wrapped copy enters from the right so
    the loop is seamless; short text is simply drawn centred-left with no
    timer running at all.
    """

    SPEED = 36.0   # px / second
    DWELL = 1.4    # seconds held at the start before scrolling
    GAP = 48       # px of blank space between the tail and the wrapped head

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._font = QFont()
        self._font.setPixelSize(13)
        self._font.setWeight(QFont.Weight.Medium)
        self._color = QApplication.palette().color(QPalette.WindowText)
        self._offset = 0.0
        self._dwell = self.DWELL
        self._text_w = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)

    def setText(self, text):
        text = text or ""
        if text == self._text:
            return
        self._text = text
        self._text_w = QFontMetricsF(self._font).horizontalAdvance(text)
        self._offset = 0.0
        self._dwell = self.DWELL
        self._sync_timer()
        self.update()

    def _overflow(self):
        return self._text_w > self.width() + 0.5

    def _sync_timer(self):
        if self._overflow() and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
        elif self._timer.isActive():
            self._timer.stop()

    def _advance(self):
        if not self._overflow():
            self._timer.stop()
            self._offset = 0.0
            self.update()
            return
        if self._dwell > 0:
            self._dwell -= self._timer.interval() / 1000.0
            return
        self._offset -= self.SPEED * self._timer.interval() / 1000.0
        if self._offset <= -(self._text_w + self.GAP):
            self._offset = 0.0
            self._dwell = self.DWELL
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(self._font)
        p.setPen(self._color)
        fm = QFontMetricsF(self._font)
        baseline = (self.height() + fm.ascent() - fm.descent()) / 2.0
        if not self._overflow():
            p.drawText(QPointF(0.0, baseline), self._text)
        else:
            p.drawText(QPointF(self._offset, baseline), self._text)
            p.drawText(QPointF(self._offset + self._text_w + self.GAP,
                               baseline), self._text)
        p.end()


class MusicCapsule(QWidget):
    """胶囊栏左侧的独立播放胶囊。

    布局：[封面36] 标题（超长跑马灯）/ 歌手 + 时间，右侧三个控制按钮。
    """

    WIDTH = 300
    HEIGHT = 56
    RADIUS = 28
    MARGIN = 12
    ART = 36
    ART_RADIUS = 9
    ART_Y = 10
    TEXT_X = 57
    TITLE_Y = 13
    META_Y = 30
    META_H = 14
    BTN = 26
    BTN_GAP = 4

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

        self.mgr = manager
        self._state = None
        self._art = None
        self._art_key = None
        self._glyph = None
        self._meta_font = None
        self._anchor_ms = 0
        self._anchor_t = 0.0
        self._last_raw = 0
        self._progressing = False
        self._animating = False
        self._flying = False
        self._fly_y = 0.0
        self._pending_hide = False
        self._target = QPoint(0, 0)

        self._marquee = MarqueeLabel(self)
        self._marquee.setGeometry(
            self.TEXT_X, self.TITLE_Y, self._text_w(), 16)

        self.btn_prev = self._make_button(ICON_PREV, "music_prev")
        self.btn_toggle = self._make_button(ICON_PAUSE, "music_pause")
        self.btn_next = self._make_button(ICON_NEXT, "music_next")
        block = 3 * self.BTN + 2 * self.BTN_GAP
        bx = self.WIDTH - self.MARGIN - block
        for b in (self.btn_prev, self.btn_toggle, self.btn_next):
            b.setGeometry(bx, 15, self.BTN, self.BTN)
            bx += self.BTN + self.BTN_GAP
        self.btn_prev.clicked.connect(manager.previous_track)
        self.btn_toggle.clicked.connect(manager.play_pause)
        self.btn_next.clicked.connect(manager.next_track)

        # Progress clock: 200 ms recompute from the monotonic anchor (same
        # pattern as the timer capsule) — no background threads involved.
        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._on_tick)

        self.setup_animations()
        manager.state_changed.connect(self._on_state)
        FamilyWindowRegistry.add(self)
        self.hide()

    # ----- construction helpers -----

    def _text_w(self):
        block = 3 * self.BTN + 2 * self.BTN_GAP
        return self.WIDTH - self.MARGIN - block - 8 - self.TEXT_X

    def _make_button(self, svg, tip_key):
        btn = GlassIconButton(svg, I18n.tr(tip_key), size=self.BTN,
                              icon_size=15, colorize_icon=False,
                              parent=self)
        return btn

    def setup_animations(self):
        # Animate the Y of the fly-in only, and read X from `_target` on every
        # frame — the capsule bar slides sideways while re-centering the whole
        # group, and a plain `pos` animation would pin the pill to the stale
        # X it started from until the flight ended.
        self.pos_anim = QPropertyAnimation(self, b"flyY")
        self.pos_anim.setDuration(300)
        self.pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.pos_anim.finished.connect(self._on_anim_finished)

        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.opacity_anim.finished.connect(self._on_anim_finished)

    def get_fly_y(self):
        return self._fly_y

    def set_fly_y(self, value):
        self._fly_y = float(value)
        self.move(self._target.x(), int(round(self._fly_y)))

    flyY = Property(float, get_fly_y, set_fly_y)

    # ----- state -----

    def has_track(self):
        return self._state is not None

    def clear_state(self):
        self._state = None
        self._art = None
        self._art_key = None
        self._anchor_t = 0.0
        self._anchor_ms = 0
        self._last_raw = 0
        self._progressing = False
        self._tick.stop()
        self._marquee.setText("")
        self.update()

    def _on_state(self, state):
        self._state = state
        if state is None:
            self.clear_state()
            return
        self._marquee.setText(state.get("title", ""))
        if state.get("art_key") != self._art_key:
            self._art_key = state.get("art_key")
            self._set_art(state.get("art_bytes") or b"")
        self.btn_toggle.set_svg(ICON_PAUSE if state.get("playing")
                                else ICON_PLAY)
        self.btn_toggle.setToolTip(
            I18n.tr("music_pause" if state.get("playing") else "music_play"))
        self._anchor_progress()
        if self._progressing:
            if not self._tick.isActive():
                self._tick.start()
        else:
            self._tick.stop()
        self.update()

    def _anchor_progress(self):
        """(Re-)anchor the local progress clock to the reported position.

        SMTC reports the position only when it changes and some players report
        it coarsely, so an unguarded re-anchor on every poll would drag the bar
        backwards. The report is therefore trusted only when it moves us
        forward of our own extrapolation (accurate report, forward seek, or a
        track change) or when it jumps well behind it (a real backwards seek);
        a stale report sitting behind the extrapolation is ignored and the
        local clock keeps gliding.
        """
        if self._state is None:
            return
        raw = int(self._state.get("position_ms", 0))
        now = time.monotonic()
        playing = bool(self._state.get("playing"))
        advancing = raw > self._last_raw
        if self._anchor_t == 0.0:
            self._anchor_ms = raw
            self._anchor_t = now
        elif not (playing or advancing):
            # Frozen (paused / stopped): rest exactly on the reported position
            # instead of freezing at wherever the anchor happened to be.
            self._anchor_ms = raw
            self._anchor_t = now
        else:
            predicted = self._predicted_ms(now)
            if raw > predicted or raw < self._anchor_ms - SEEK_MS:
                self._anchor_ms = raw
                self._anchor_t = now
        # Progress must follow the POSITION, not only the reported status: a
        # player that mislabels itself as paused while its position keeps
        # advancing still needs a moving bar.
        self._progressing = playing or advancing
        self._last_raw = raw

    def _predicted_ms(self, now=None):
        if self._anchor_t == 0.0 or self._state is None:
            return self._anchor_ms
        if not self._progressing:
            return self._anchor_ms
        now = time.monotonic() if now is None else now
        return self._anchor_ms + int((now - self._anchor_t) * 1000)

    def _current_ms(self):
        ms = self._predicted_ms()
        total = int(self._state.get("duration_ms", 0)) if self._state else 0
        if total > 0:
            return max(0, min(ms, total))
        return max(0, ms)

    def _on_tick(self):
        self.update()

    def _set_art(self, data):
        img = QImage()
        if data:
            img.loadFromData(data)
        if img.isNull():
            self._art = None
        else:
            dpr = screen_dpr()
            size = int(round(self.ART * dpr))
            scaled = img.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation)
            x = max(0, (scaled.width() - size) // 2)
            y = max(0, (scaled.height() - size) // 2)
            cropped = scaled.copy(x, y, size, size)
            cropped.setDevicePixelRatio(dpr)
            self._art = cropped
        self.update()

    # ----- positioning / visibility -----

    def attach_to(self, x, y):
        """Park the pill at (x, y) — its final pose beside the capsule bar.

        While airborne only X is applied: the flight animation owns Y, and the
        bar may be sliding sideways underneath us as it re-centers the group
        (so X has to keep tracking or the pill lands out of line)."""
        self._target = QPoint(int(x), int(y))
        if self._flying:
            self.set_fly_y(self._fly_y)
        else:
            self._fly_y = float(y)
            self.move(self._target)

    def show_animated(self, mode):
        """Mirror the capsule bar's show animation (vertical fly-in or fade)."""
        if self.isVisible() and not self._pending_hide:
            # Fully shown: just re-park. Mid flight, leave the animation
            # alone — snapping to the target here would make the pill jump
            # ahead of the bar it is flying in with (_on_anim_finished
            # settles on the latest target once the flight ends).
            if not self._animating:
                self._fly_y = float(self._target.y())
                self.move(self._target)
            return
        self._animating = True
        self._pending_hide = False
        first_show = not self.isVisible()

        if mode == "dynamic":
            self.pos_anim.stop()
            self.opacity_anim.stop()
            self._flying = False
            self.move(self._target)
            if first_show:
                self.setWindowOpacity(0.0)
                self.show()
                self.raise_()
            self.opacity_anim.setStartValue(self.windowOpacity())
            self.opacity_anim.setEndValue(1.0)
            self.opacity_anim.start()
            return

        if first_show:
            start_y = float(-self.height())
            start_opacity = 0.0
            self.setWindowOpacity(0.0)
            self.set_fly_y(start_y)
            self.show()
            self.raise_()
        else:
            start_y = float(self._fly_y)
            start_opacity = self.windowOpacity()

        self.pos_anim.stop()
        self.opacity_anim.stop()
        self.pos_anim.setStartValue(start_y)
        self.pos_anim.setEndValue(float(self._target.y()))
        self.opacity_anim.setStartValue(start_opacity)
        self.opacity_anim.setEndValue(1.0)
        self._flying = True
        self.pos_anim.start()
        self.opacity_anim.start()

    def hide_animated(self, mode):
        if not self.isVisible():
            return
        self._animating = True
        self._pending_hide = True

        if mode == "dynamic":
            self.pos_anim.stop()
            self.opacity_anim.stop()
            self._flying = False
            self.opacity_anim.setStartValue(self.windowOpacity())
            self.opacity_anim.setEndValue(0.0)
            self.opacity_anim.start()
            return

        self.pos_anim.stop()
        self.opacity_anim.stop()
        self.pos_anim.setStartValue(float(self._fly_y))
        self.pos_anim.setEndValue(float(-self.height()))
        self.opacity_anim.setStartValue(self.windowOpacity())
        self.opacity_anim.setEndValue(0.0)
        self._flying = True
        self.pos_anim.start()
        self.opacity_anim.start()

    def hide_immediately(self):
        self._animating = False
        self._flying = False
        self._pending_hide = False
        self.pos_anim.stop()
        self.opacity_anim.stop()
        self._tick.stop()
        self.hide()

    def _on_anim_finished(self):
        self._animating = False
        self._flying = False
        if self._pending_hide:
            self._pending_hide = False
            self.hide()
            return
        # A recenter or group slide landed while we were flying in — settle on
        # the latest target rather than the pose the flight started from.
        if self.isVisible() and self.pos() != self._target:
            self._fly_y = float(self._target.y())
            self.move(self._target)

    def showEvent(self, event):
        FamilyWindowRegistry.refresh_hwnd(self)
        FamilyWindowRegistry.set_no_activate(self)
        self._marquee._sync_timer()
        super().showEvent(event)

    def hideEvent(self, event):
        self.pos_anim.stop()
        self.opacity_anim.stop()
        self._animating = False
        self._flying = False
        self._pending_hide = False
        self._tick.stop()
        self.setWindowOpacity(1.0)
        super().hideEvent(event)

    # ----- painting -----

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_pill(p, self.rect(), self.RADIUS)

        text_color = QApplication.palette().color(QPalette.WindowText)
        dim = QColor(text_color)
        dim.setAlpha(150)

        self._paint_art(p, text_color)
        self._paint_meta(p, text_color, dim)
        p.end()

    def _paint_art(self, p, text_color):
        rect = QRectF(self.MARGIN, self.ART_Y, self.ART, self.ART)
        path = QPainterPath()
        path.addRoundedRect(rect, self.ART_RADIUS, self.ART_RADIUS)
        if self._art is not None:
            p.save()
            p.setClipPath(path)
            p.drawImage(rect.topLeft(), self._art)
            p.restore()
            return
        plate = QColor(text_color)
        plate.setAlpha(28)
        p.fillPath(path, plate)
        if self._glyph is None:
            self._glyph = make_pixmap(ICON_MUSIC, text_color.name(), 18)
        p.drawPixmap(
            QPointF(rect.center().x() - 9, rect.center().y() - 9), self._glyph)

    def _paint_meta(self, p, text_color, dim):
        if self._state is None:
            return
        right = self.TEXT_X + self._text_w()
        font = self._artist_font()
        fm = QFontMetricsF(font)
        p.setPen(text_color)
        p.setFont(font)
        y = self.META_Y
        # Row 2: artist on the left, elapsed / total on the right.
        total = int(self._state.get("duration_ms", 0))
        time_text = ""
        if total > 0:
            time_text = f"{_fmt_time(self._current_ms())} / {_fmt_time(total)}"
        time_w = 0.0
        if time_text:
            time_w = fm.horizontalAdvance(time_text)
            p.setPen(dim)
            p.drawText(QRectF(right - time_w, y, time_w, self.META_H),
                       Qt.AlignRight | Qt.AlignVCenter, time_text)
        artist_w = max(0.0, self._text_w() - time_w - 6)
        artist = fm.elidedText(
            self._state.get("artist", ""), Qt.ElideRight, artist_w)
        if artist:
            p.setPen(dim)
            p.drawText(QRectF(self.TEXT_X, y, artist_w, self.META_H),
                       Qt.AlignLeft | Qt.AlignVCenter, artist)

    def _artist_font(self):
        if self._meta_font is None:
            f = QFont()
            f.setPixelSize(11)
            self._meta_font = f
        return self._meta_font