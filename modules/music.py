"""
音乐状态
读取 Windows SMTC 会话，供胶囊状态条展示与播放控制
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import asyncio
import threading

from PySide6.QtCore import (
    Qt, QObject, QTimer, QPointF, Signal
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QFontMetricsF, QPalette
)
from PySide6.QtWidgets import QWidget, QApplication

# SMTC playback status values (winrt enum ints) — compared numerically so the
# module imports cleanly even when the media-control package is absent.
_SMTC_PLAYING = 4

# Poll cadence. Fast enough that a track change feels instant, slow enough to
# stay off the CPU radar (each poll is a couple of WinRT calls).
POLL_S = 0.8


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

        The coroutine re-polls when it finishes so the strip reflects the new
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
                # A transient WinRT failure must not blank the strip, and must
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

        # Artwork is read once per track. A track with no artwork simply
        # leaves the cache empty and the segment draws its music-note badge.
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