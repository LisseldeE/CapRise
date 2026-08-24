"""Pomodoro / countdown timer: logic manager + capsule strip + setup dialog.

The timer is a compact side feature of the capsule. Clicking the timer
button opens a small dialog to configure a pomodoro cycle (focus/break) or a
plain countdown. While a timer runs, the capsule extends a strip to its left
showing the remaining time as HH:MM:SS (constant-width monospace). The strip
is laid out with the time text on the left and a small vertical column of
controls on the right (reset on top, stop below) so nothing overlaps; the
time text itself is clickable to pause/resume. The strip sits on the same
glass plate as the capsule, separated from the tool cluster by a hairline
divider. When a countdown finishes, an independent glass notice card pops up
on screen (even if the capsule is hidden).
"""
import math
import time

from PySide6.QtCore import (
    QObject, QTimer, Signal, Qt, QRectF, QPropertyAnimation,
    QEasingCurve, Property
)
from PySide6.QtGui import (
    QColor, QPainter, QPen, QFont, QFontMetrics, QPalette
)
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QDialog,
    QPushButton, QButtonGroup, QApplication, QStackedLayout
)

from modules.i18n import I18n
from modules.icons import ICON_ROTATE_CCW, ICON_CLOSE, ICON_TIMER
from modules.widgets import GlassIconButton, paint_pill, make_pixmap
from modules.config import Config
from modules.family import FamilyWindowRegistry

# phase -> i18n key used for the status-label prefix
_PHASE_KEYS = {
    "focus": "timer_focus",
    "break": "timer_break",
    "countdown": "timer_countdown",
}


def format_hms(seconds):
    """Format seconds as HH:MM:SS (always three groups -> constant width)."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class TimerManager(QObject):
    """Owns the countdown clock.

    Drift-free: the end time is a monotonic timestamp and each tick
    recomputes the remaining seconds from it; pausing just freezes the
    remaining value and stops the ticker.

    The cadence is a single GUI-thread QTimer at a sub-second interval
    (REFRESH_MS). It never decrements a counter — every fire recomputes the
    remaining time straight from the monotonic end timestamp, so the value
    shown is always the true remaining time even when a fire arrives late
    (timer coalescing, a momentarily busy event loop). A cross-thread worker
    clock is deliberately avoided: its queued-signal delivery can be stalled
    by thread scheduling / GIL contention, which made the label freeze and
    then jump several seconds. Here all real work happens on the GUI thread,
    so the display simply follows the wall clock.
    """

    phase_changed = Signal(str)   # "focus" | "break" | "countdown"
    tick = Signal(int)            # remaining seconds
    state_changed = Signal(str)   # "running" | "paused" | "idle" | "finished"
    finished = Signal(str)        # the phase that just completed

    # Sub-second cadence: the label only changes once per second, so this
    # interval just bounds how promptly a second boundary is picked up after
    # any event-loop hiccup (<= 200 ms), never the countdown accuracy.
    REFRESH_MS = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = None
        self._phase = None
        self._remaining = 0
        self._paused = False
        self._end_ts = 0.0
        self._focus_sec = 25 * 60
        self._break_sec = 5 * 60
        self._duration_sec = 25 * 60
        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self._on_tick)

    # ----- public API -----

    def start(self, mode, focus_sec=25 * 60, break_sec=5 * 60, duration_sec=25 * 60):
        self._mode = mode
        self._focus_sec = max(1, int(focus_sec))
        self._break_sec = max(1, int(break_sec))
        self._duration_sec = max(1, int(duration_sec))
        if mode == "countdown":
            self._begin("countdown", self._duration_sec)
        else:
            self._begin("focus", self._focus_sec)
        self.state_changed.emit("running")

    def toggle_pause(self):
        if self._paused:
            self.resume()
        else:
            self.pause()

    def pause(self):
        if self._paused or self._phase is None or self._remaining <= 0:
            return
        self._paused = True
        self._timer.stop()
        self.state_changed.emit("paused")

    def resume(self):
        if not self._paused:
            return
        self._paused = False
        self._end_ts = time.monotonic() + self._remaining
        self._timer.start()
        self.state_changed.emit("running")

    def reset(self):
        self._timer.stop()
        self._mode = None
        self._phase = None
        self._remaining = 0
        self._paused = False
        self.state_changed.emit("idle")
        self.tick.emit(0)

    def reset_phase(self):
        """Restart the current phase from its full configured duration.

        Unlike reset() (full cancel), this keeps the timer active — the
        countdown jumps back to e.g. 25:00 and keeps its running/paused
        state. No-op when no timer is running."""
        if self._phase is None:
            return
        seconds = self._phase_seconds(self._phase)
        self._remaining = seconds
        if self._paused:
            # Stay paused at the fresh full value; the label updates below.
            self._timer.stop()
            self.tick.emit(seconds)
            self.state_changed.emit("paused")
        else:
            self._end_ts = time.monotonic() + seconds
            self._timer.start()
            self.tick.emit(seconds)
            self.state_changed.emit("running")

    def _phase_seconds(self, phase):
        if phase == "focus":
            return self._focus_sec
        if phase == "break":
            return self._break_sec
        return self._duration_sec

    def phase(self):
        return self._phase

    def remaining(self):
        return max(0, self._remaining)

    def is_active(self):
        return self._phase is not None

    def is_paused(self):
        return self._paused

    def shutdown(self):
        """Stop the countdown (called on app exit). The QTimer is a child
        of this object, so it is torn down automatically; this keeps the
        API stable for the capsule's exit path."""
        self._timer.stop()

    # ----- internals -----

    def _begin(self, phase, seconds):
        self._phase = phase
        self._remaining = seconds
        self._paused = False
        self._end_ts = time.monotonic() + seconds
        self._timer.start()
        self.phase_changed.emit(phase)
        self.tick.emit(seconds)

    def _on_tick(self):
        if self._paused:
            return
        remaining = int(math.ceil(self._end_ts - time.monotonic()))
        if remaining <= 0:
            self._complete_phase()
        elif remaining != self._remaining:
            # Emit only when the displayed second actually changes — most
            # fires land inside the same second.
            self._remaining = remaining
            self.tick.emit(remaining)

    def _complete_phase(self):
        if self._mode == "countdown":
            phase = self._phase
            self._timer.stop()
            self._mode = None
            self._phase = None
            self._paused = False
            self._remaining = 0
            self.finished.emit(phase)
            self.state_changed.emit("finished")
        else:
            if self._phase == "focus":
                self.finished.emit("focus")
                self._begin("break", self._break_sec)
            else:
                self.finished.emit("break")
                self._begin("focus", self._focus_sec)


class _ClickableLabel(QLabel):
    """QLabel that emits clicked() on a left press (used to pause/resume)."""

    clicked = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TimerDisplay(QWidget):
    """Left strip of the capsule shown while a timer is active.

    Layout: phase + remaining HH:MM:SS on the left (clickable to
    pause/resume), and a small vertical column of controls on the right
    (reset on top, stop below) that never overlaps the text. The capsule
    paints the shared glass pill underneath; this widget only draws a
    hairline divider at its right edge.
    """

    pause_toggled = Signal()
    reset_requested = Signal()
    close_requested = Signal()

    HEIGHT = 44
    BTN = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paused = False
        self._notice = ""
        self._notice_until = 0.0
        self.setFixedHeight(self.HEIGHT)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)

        font = QFont("Consolas")
        font.setPointSize(11)
        fm = QFontMetrics(font)
        # Right gap (time -> buttons) matches the left gap (title -> time),
        # which is exactly one space in the label font.
        lay.setSpacing(fm.horizontalAdvance(" "))

        self._label = _ClickableLabel("")
        self._label.setFont(font)
        # Left-align with a dynamic width so the time always hugs the strip's
        # left margin — the outer gaps (text->left, buttons->right) stay
        # symmetric instead of leaving a fixed-width slack on the left.
        self._label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._label.setToolTip(I18n.tr("timer_pause"))
        self._label.clicked.connect(self.pause_toggled)
        lay.addWidget(self._label)

        # Compact horizontal control row on the right: reset then stop, side
        # by side, so the controls stay a single row high and read level with
        # the time text (a vertical stack made the buttons tower over the
        # other capsule icons).
        controls = QHBoxLayout()
        controls.setSpacing(2)
        self._btn_reset = GlassIconButton(
            ICON_ROTATE_CCW, I18n.tr("timer_reset_tip"), size=self.BTN,
            icon_size=11, colorize_icon=False)
        self._btn_reset.clicked.connect(self.reset_requested)
        self._btn_close = GlassIconButton(
            ICON_CLOSE, I18n.tr("timer_close_tip"), size=self.BTN,
            icon_size=11, hover_color="#e03131",
            hover_bg_color=QColor(224, 49, 49), colorize_icon=False)
        self._btn_close.clicked.connect(self.close_requested)
        controls.addWidget(self._btn_reset)
        controls.addWidget(self._btn_close)
        lay.addLayout(controls)

    # ----- size -----

    def sizeHint(self):
        # The strip is sized to its current content: left-aligned label (its
        # dynamic text width) + spacing + right button column + margins. The
        # capsule relies on this to reserve exactly the room needed.
        return self.layout().sizeHint()

    # ----- state -----

    @staticmethod
    def _phase_text(phase):
        if phase == "paused":
            return I18n.tr("timer_pause")
        return I18n.tr(_PHASE_KEYS.get(phase, "timer_countdown"))

    def show_phase(self, phase, remaining, paused=False):
        """Refresh the label with the current phase/time (called each tick)."""
        if time.monotonic() < self._notice_until:
            return  # keep the transient "phase finished" notice
        # Undo the width pin applied by show_notice, back to dynamic sizing.
        self._label.setMinimumWidth(0)
        self._label.setText(
            f"{self._phase_text('paused' if paused else phase)} "
            f"{format_hms(remaining)}")
        self.set_paused(paused)

    def set_paused(self, paused):
        if paused == self._paused:
            return
        self._paused = bool(paused)
        if self._paused:
            # Grey the text out so pausing reads visually; clicking resumes.
            self._label.setStyleSheet("color: rgba(128, 128, 128, 190);")
            self._label.setToolTip(I18n.tr("timer_resume"))
        else:
            self._label.setStyleSheet("")
            self._label.setToolTip(I18n.tr("timer_pause"))

    def show_notice(self, message):
        """Transient "phase finished" message (e.g. 专注结束)."""
        self._notice = message
        self._notice_until = time.monotonic() + 2.5
        # Pin the label to its current (steady-state) width and elide longer
        # messages, so the brief notice never reflows or clips the strip
        # (English notices can exceed the width of the phase+time text).
        fm = QFontMetrics(self._label.font())
        w = max(40, fm.horizontalAdvance(self._label.text()))
        self._label.setMinimumWidth(w)
        self._label.setText(fm.elidedText(message, Qt.ElideRight, w))
        self.set_paused(False)

    # ----- painting -----

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(128, 128, 128, 100), 1))
        p.drawLine(self.width() - 1, 12, self.width() - 1, self.height() - 12)
        p.end()


class WheelNumberPicker(QWidget):
    """Compact wheel-style number picker (phone-alarm look).

    The current value is centered and highlighted on a translucent chip;
    neighbours are dimmed above/below. Scrolling the wheel or dragging
    vertically changes the value, and every change glides through a short
    scroll animation: a float display value drives the row positions, so the
    numbers slide like a real alarm wheel instead of snapping. The integer
    value commits immediately (value() stays correct mid-animation), while
    the visible rows catch up. Emits valueChanged(int).
    """

    valueChanged = Signal(int)

    W = 56
    ROW = 30        # row height
    ROWS = 3        # visible rows (current + one above / one below)

    def __init__(self, minimum, maximum, value=0, suffix="", width=None,
                 parent=None):
        super().__init__(parent)
        self._min = int(minimum)
        self._max = max(self._min, int(maximum))
        self._value = max(self._min, min(self._max, int(value)))
        self._fv = float(self._value)  # float display value (scroll position)
        self._suffix = suffix
        self._drag_y = None
        self._drag_base = 0.0
        self._w = int(width) if width else self.W
        self.setFixedSize(self._w, self.ROW * self.ROWS)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        self._anim = QPropertyAnimation(self, b"wheelScroll")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)

    # ----- scroll property (driven by the animation) -----

    def _get_wheel_scroll(self):
        return self._fv

    def _set_wheel_scroll(self, fv):
        self._fv = fv
        self.update()

    wheelScroll = Property(float, _get_wheel_scroll, _set_wheel_scroll)

    def value(self):
        return self._value

    def setValue(self, value, animate=True):
        v = max(self._min, min(self._max, int(value)))
        if v == self._value:
            return
        # Commit the integer immediately so value() never reads a stale
        # target; the animation only catches the visible rows up.
        self._value = v
        self.valueChanged.emit(v)
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._fv)
            self._anim.setEndValue(float(v))
            self._anim.start()
        else:
            self._anim.stop()
            self._fv = float(v)
        self.update()

    def _on_anim_finished(self):
        self._fv = float(self._value)
        self.update()

    def _bump(self, delta):
        self.setValue(self._value + delta)

    def wheelEvent(self, event):
        steps = event.angleDelta().y() // 120
        if steps:
            # Reversed: scrolling up decreases, scrolling down increases.
            self._bump(-1 if steps > 0 else 1)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Drop any in-flight animation and start dragging from the
            # current scroll position (not the settled value).
            self._anim.stop()
            self._drag_y = event.position().y()
            self._drag_base = self._fv
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_y is not None:
            # The wheel follows the pointer 1:1 (1 row per ROW px of travel);
            # the integer value is committed live as it rounds.
            fv = self._drag_base + (self._drag_y - event.position().y()) / self.ROW
            fv = max(float(self._min), min(float(self._max), fv))
            self._fv = fv
            v = int(round(fv))
            if v != self._value:
                self._value = v
                self.valueChanged.emit(v)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_y is not None:
            self._drag_y = None
            v = max(self._min, min(self._max, int(round(self._fv))))
            self._fv = float(v)
            if v != self._value:
                self._value = v
                self.valueChanged.emit(v)
            self.update()
        super().mouseReleaseEvent(event)

    def _text(self, value):
        return f"{value}{self._suffix}"

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        accent = QApplication.palette().color(QPalette.Highlight)
        text = QApplication.palette().color(QPalette.WindowText)

        # Center highlight chip (fixed; the numbers scroll beneath it).
        mid = (self.ROWS - 1) // 2
        y_mid = mid * self.ROW + self.ROW / 2
        chip = QRectF(0, mid * self.ROW + 2, self._w, self.ROW - 4)
        c = QColor(accent)
        c.setAlpha(70)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(chip, 8, 8)

        # Float display value -> each value's vertical centre slides
        # continuously, so a change reads as a scroll rather than a jump.
        fv = self._fv
        base = int(round(fv))
        for d in range(-self.ROWS - 1, self.ROWS + 2):
            val = base + d
            if val < self._min or val > self._max:
                continue
            yc = y_mid + (val - fv) * self.ROW
            if yc < -self.ROW or yc > self.height() + self.ROW:
                continue
            dist = abs(yc - y_mid) / self.ROW
            f = QFont()
            f.setPointSize(13 if dist < 0.5 else 10)
            f.setBold(dist < 0.5)
            col = QColor(text)
            col.setAlphaF(max(0.15, 1.0 - dist * 0.5))
            p.setFont(f)
            p.setPen(col)
            p.drawText(QRectF(0, yc - self.ROW / 2, self._w, self.ROW),
                       Qt.AlignCenter, self._text(val))
        p.end()


class TimerDialog(QDialog):
    """Configure and start a pomodoro cycle or a plain countdown.

    A family window, so opening it never dismisses the capsule. The chosen
    values are persisted to config; starting over an active timer just
    replaces it. Durations are chosen with wheel-style number pickers instead
    of plain spin boxes.
    """

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self.setWindowTitle(I18n.tr("timer_settings_title"))
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint
                            | Qt.WindowStaysOnTopHint)
        self.setFixedWidth(400)
        self.setup_ui()
        self.load_values()
        self.center_on_screen()

    def setup_ui(self):
        self.setStyleSheet(self._QSS())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(16)

        # Mode: segmented toggle between countdown and pomodoro (countdown is
        # listed first, with a small gap between the two halves).
        seg = QHBoxLayout()
        seg.setSpacing(8)
        self._btn_count = QPushButton(I18n.tr("timer_countdown"))
        self._btn_pomo = QPushButton(I18n.tr("timer_pomodoro"))
        self._btn_count.setObjectName("seg")
        self._btn_pomo.setObjectName("seg")
        self._grp = QButtonGroup(self)
        self._grp.setExclusive(True)
        self._grp.addButton(self._btn_count)
        self._grp.addButton(self._btn_pomo)
        self._btn_count.setCheckable(True)
        self._btn_pomo.setCheckable(True)
        self._btn_pomo.setChecked(True)
        for b in (self._btn_count, self._btn_pomo):
            b.setFixedHeight(30)
            b.setCursor(Qt.PointingHandCursor)
        seg.addWidget(self._btn_count)
        seg.addWidget(self._btn_pomo)
        seg.addStretch()
        lay.addLayout(seg)

        # Pomodoro durations: each phase is entered as HH:MM:SS using six
        # wheel pickers (a ten- and a one-wheel per unit). Minutes/seconds
        # rollers cap at 59 so any combination stays a valid clock value.
        self._pico_focus, self._picks_focus = self._hms_row(
            I18n.tr("timer_focus_min"), 25, 0, 0)
        self._pico_break, self._picks_break = self._hms_row(
            I18n.tr("timer_break_min"), 5, 0, 0)
        self._pomo_box = QWidget()
        pb = QVBoxLayout(self._pomo_box)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(14)
        pb.addLayout(self._pico_focus)
        pb.addLayout(self._pico_break)
        lay.addWidget(self._pomo_box)

        # Countdown duration. Its content is vertically centered (stretches
        # above/below) so it reuses the pomodoro view's taller height without
        # hugging the top once the dialog height is locked.
        self._pico_dur, self._picks_dur = self._hms_row(
            I18n.tr("timer_duration_min"), 25, 0, 0)
        self._count_box = QWidget()
        cb = QVBoxLayout(self._count_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(14)
        cb.addStretch()
        cb.addLayout(self._pico_dur)
        cb.addStretch()
        lay.addWidget(self._count_box)

        # Actions.
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QPushButton(I18n.tr("cancel"))
        self._btn_cancel.setObjectName("cancel")
        self._btn_start = QPushButton(I18n.tr("timer_start"))
        self._btn_start.setObjectName("start")
        for b in (self._btn_cancel, self._btn_start):
            b.setFixedSize(88, 32)
            b.setCursor(Qt.PointingHandCursor)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_start)
        lay.addLayout(btn_row)

        self._grp.buttonClicked.connect(self._update_mode_fields)
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_start.clicked.connect(self._on_start)
        self._update_mode_fields()
        # Lock a single dialog height. The pomodoro view (two rows) is the
        # tallest, so once the countdown box is hidden its sizeHint gives the
        # required height; fixing it here keeps the window size stable when
        # switching modes (the countdown row is vertically centered to fit).
        self.setFixedHeight(self.layout().sizeHint().height())

    def _hms_row(self, text, ph, pm, ps):
        """A labelled block: a caption above six wheel pickers grouped as
        HH:MM:SS (a ten- and a one-wheel per unit), e.g. [0][0]:[2][5]:[0][0].

        Returns (block_layout, pickers) where pickers is
        (ten_h, one_h, ten_m, one_m, ten_s, one_s). The hour rollers span
        00-99; the minute and second rollers span 00-59, so no wheel combo
        can produce an invalid clock value."""
        block = QVBoxLayout()
        block.setSpacing(6)
        label = QLabel(text)
        block.addWidget(label)

        box = QHBoxLayout()
        box.setSpacing(2)
        picks = []
        units = ((ph, 9, 9), (pm, 5, 9), (ps, 5, 9))  # value, ten-max, one-max
        for i, (val, ten_max, one_max) in enumerate(units):
            if i:
                colon = QLabel(":")
                cf = QFont()
                cf.setPointSize(14)
                cf.setBold(True)
                colon.setFont(cf)
                colon.setAlignment(Qt.AlignCenter)
                box.addWidget(colon)
            ten = WheelNumberPicker(0, ten_max, val // 10, width=48)
            one = WheelNumberPicker(0, one_max, val % 10, width=48)
            picks.extend((ten, one))
            box.addWidget(ten)
            box.addWidget(one)
        box.addStretch()
        block.addLayout(box)
        return block, picks

    @staticmethod
    def _hms_seconds(picks):
        """Combine the six pickers (ten_h, one_h, ...) into total seconds."""
        ten_h, one_h, ten_m, one_m, ten_s, one_s = picks
        hh = ten_h.value() * 10 + one_h.value()
        mm = ten_m.value() * 10 + one_m.value()
        ss = ten_s.value() * 10 + one_s.value()
        return hh * 3600 + mm * 60 + ss

    @staticmethod
    def _set_hms_values(picks, seconds, animate=False):
        """Load a total-seconds value into the six pickers as HH:MM:SS."""
        seconds = max(0, int(seconds))
        hh, rem = divmod(seconds, 3600)
        mm, ss = divmod(rem, 60)
        ten_h, one_h, ten_m, one_m, ten_s, one_s = picks
        for pick, v in ((ten_h, hh // 10), (one_h, hh % 10),
                        (ten_m, mm // 10), (one_m, mm % 10),
                        (ten_s, ss // 10), (one_s, ss % 10)):
            pick.setValue(v, animate)

    def _update_mode_fields(self, *_):
        pomo = self._btn_pomo.isChecked()
        self._pomo_box.setVisible(pomo)
        self._count_box.setVisible(not pomo)
        # No resize here: the dialog height is fixed at construction to the
        # pomodoro (tallest) view, so toggling modes never moves the window.

    def load_values(self):
        c = Config()
        mode = c.get("timer_mode", "pomodoro")
        self._btn_pomo.setChecked(mode != "countdown")
        self._btn_count.setChecked(mode == "countdown")
        self._set_hms_values(self._picks_focus,
                             int(c.get("timer_focus_sec", 25 * 60)))
        self._set_hms_values(self._picks_break,
                             int(c.get("timer_break_sec", 5 * 60)))
        self._set_hms_values(self._picks_dur,
                             int(c.get("timer_duration_sec", 25 * 60)))
        # Programmatic setChecked above doesn't emit buttonClicked, so sync the
        # visible fields with the loaded mode explicitly.
        self._update_mode_fields()

    def _on_start(self):
        c = Config()
        if self._btn_pomo.isChecked():
            focus = self._hms_seconds(self._picks_focus)
            break_ = self._hms_seconds(self._picks_break)
            c.set("timer_mode", "pomodoro")
            c.set("timer_focus_sec", focus)
            c.set("timer_break_sec", break_)
            self._manager.start("pomodoro", focus_sec=focus, break_sec=break_)
        else:
            duration = self._hms_seconds(self._picks_dur)
            c.set("timer_mode", "countdown")
            c.set("timer_duration_sec", duration)
            self._manager.start("countdown", duration_sec=duration)
        self.accept()

    def _QSS(self):
        return """
        QDialog { background: palette(window); }
        QLabel { background: transparent; }
        QPushButton#seg {
            border: none; border-radius: 15px; padding: 4px 16px;
            background: palette(button); color: palette(window-text);
        }
        QPushButton#seg:checked {
            background: palette(highlight); color: white; font-weight: 600;
        }
        QPushButton#start {
            border: none; border-radius: 16px; padding: 5px 16px;
            background: palette(highlight); color: white; font-weight: 600;
        }
        QPushButton#start:hover {
            background: palette(highlight);
            border: 1px solid rgba(255, 255, 255, 150);
            border-radius: 15px;
        }
        QPushButton#cancel {
            border: none; border-radius: 16px; padding: 5px 16px;
            background: transparent; color: palette(window-text);
        }
        QPushButton#cancel:hover { background: palette(button); }
        """

    def center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2
        )

    def showEvent(self, event):
        super().showEvent(event)
        FamilyWindowRegistry.add(self)
        FamilyWindowRegistry.refresh_hwnd(self)

    def closeEvent(self, event):
        FamilyWindowRegistry.remove(self)
        super().closeEvent(event)


class TimerNoticeOverlay(QWidget):
    """Compact capsule-style notice popped when a countdown finishes.

    Deliberately independent of the capsule: if the capsule was hidden while
    the timer ran, the user still sees the "finished" card. Rendered as a
    small horizontal glass capsule — a line timer icon, the message and the
    OK button all on a single row — that fades in and auto-closes after a
    few seconds or on the button.
    """

    H = 52  # pill height (rounded ends: radius = H / 2)

    def __init__(self, message, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._message = message
        self.setFixedHeight(self.H)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 10, 12, 10)
        lay.setSpacing(10)

        # Line-style timer icon echoing the capsule's icon language.
        icon_color = QApplication.palette().color(QPalette.WindowText)
        icon_hex = (f"#{icon_color.red():02x}{icon_color.green():02x}"
                    f"{icon_color.blue():02x}")
        icon = QLabel()
        icon.setPixmap(make_pixmap(ICON_TIMER, icon_hex, 18))
        lay.addWidget(icon)

        msg = QLabel(message)
        mf = QFont()
        mf.setPointSize(13)
        mf.setBold(True)
        msg.setFont(mf)
        lay.addWidget(msg)

        btn = QPushButton(I18n.tr("timer_ok"))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(64, 28)
        btn.setStyleSheet("""
            QPushButton { border: none; border-radius: 14px;
                          background: palette(highlight); color: white;
                          font-weight: 600; }
            QPushButton:hover { background: palette(highlight);
                                border: 1px solid rgba(255, 255, 255, 150);
                                border-radius: 13px; }
        """)
        btn.clicked.connect(self._close_soon)
        lay.addWidget(btn)

        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_anim.setDuration(300)
        self._opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._opacity_anim.finished.connect(self._on_anim_done)

        self._auto_close = QTimer(self)
        self._auto_close.setSingleShot(True)
        self._auto_close.setInterval(5000)
        self._auto_close.timeout.connect(self._close_soon)

        # Fit the width to the content, then center it near the top of the
        # screen so it reads as a notice.
        self.resize(self.layout().sizeHint().width(), self.H)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.y() + 40)

    def showEvent(self, event):
        super().showEvent(event)
        FamilyWindowRegistry.add(self)
        FamilyWindowRegistry.refresh_hwnd(self)
        FamilyWindowRegistry.set_no_activate(self)
        self._start_fade(0.0, 1.0)

    def _start_fade(self, start, end):
        self._opacity_anim.stop()
        self._opacity_anim.setStartValue(start)
        self._opacity_anim.setEndValue(end)
        self._opacity_anim.start()

    def _close_soon(self):
        self._auto_close.stop()
        self._start_fade(self.windowOpacity(), 0.0)

    def _on_anim_done(self):
        if self.windowOpacity() < 0.01:
            self.close()

    def paintEvent(self, event):
        p = QPainter(self)
        paint_pill(p, self.rect(), self.H // 2)
        p.end()

    def closeEvent(self, event):
        FamilyWindowRegistry.remove(self)
        super().closeEvent(event)
