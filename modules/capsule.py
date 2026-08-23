from ctypes import wintypes
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QGraphicsDropShadowEffect, QApplication
)
from PySide6.QtCore import (
    Qt, QPoint, QPropertyAnimation, QEasingCurve, QEvent,
    QAbstractNativeEventFilter, Signal, QTimer
)
from PySide6.QtGui import QPainter, QColor, QGuiApplication, QKeyEvent, QCursor
from modules.icons import (
    ICON_SCREENSHOT, ICON_ANNOTATION, ICON_TRANSLATE, ICON_SETTINGS,
    ICON_CLOSE, ICON_CLIPBOARD, ICON_SEARCH, ICON_TIMER
)
from modules.i18n import I18n
from modules.family import FamilyWindowRegistry
from modules.global_mouse_hook import GlobalMouseHook
from modules.widgets import GlassIconButton, paint_pill
from modules.config import Config
from modules.timer import TimerDisplay, TimerManager, TimerNoticeOverlay

# Windows constants
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B


class CapsuleNativeFilter(QAbstractNativeEventFilter):
    """Native event filter to catch global ESC key (WM_KEYDOWN VK_ESCAPE).

    Triggers a family-wide hide as long as ANY family window is visible
    (capsule OR panel) — not just the capsule. ESC is a user-explicit intent
    so it bypasses the show-debounce via force_family_hide()."""

    def __init__(self, capsule):
        super().__init__()
        self.capsule = capsule

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message.__int__()))
            if msg.message == WM_KEYDOWN and msg.wParam == VK_ESCAPE:
                if FamilyWindowRegistry.any_visible() and not self.capsule._animating:
                    self.capsule.force_family_hide()
                    return True, 0
        return False, 0


class CapsuleBar(QWidget):
    """Main floating capsule bar with tool buttons.

    The capsule is the anchor of a "family" of windows (itself + the
    clipboard panel + the room dialog). Focus moving to a family window
    does NOT trigger a hide; focus leaving the family hides everything.
    Background follows the system palette - no fixed colors.
    """

    hide_family_requested = Signal()

    # Base capsule size without the timer strip (matches the pre-timer fixed
    # 396x56 layout); the strip extends the width by its own width + one
    # inter-item gap when a timer is active.
    BASE_WIDTH = 396
    BASE_HEIGHT = 56

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Never steal focus on show — the user's caret stays in their input.
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedHeight(self.BASE_HEIGHT)

        self._animating = False
        self._pending_hide = False
        self.setup_ui()
        self.setup_animations()
        self.setup_shadow()
        self.hide()

        # The capsule is always a family window (the anchor).
        FamilyWindowRegistry.add(self)

        # ESC: catches WM_KEYDOWN VK_ESCAPE at Windows message level
        self._esc_filter = CapsuleNativeFilter(self)
        QApplication.instance().installNativeEventFilter(self._esc_filter)

        # Global low-level mouse hook: the OS delivers every mouse-down on
        # the screen to us before the target window sees it. When the click
        # is not inside any family window's HWND rect, we hide the family.
        # This is far more reliable than the foreground-window poll it
        # replaces — it works for clicks on other apps, the desktop, the
        # taskbar, the tray, etc., not just inside the Qt app.
        self._mouse_hook = GlobalMouseHook()
        self._mouse_hook.on_outside_click = self._on_outside_click
        self._mouse_hook.install()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 6, 14, 6)

        # Timer countdown strip: hidden until a timer starts, then the capsule
        # extends to its left (same glass plate, hairline divider) and the
        # whole bar re-centers on screen.
        self.timer = TimerManager(self)
        self.timer_display = TimerDisplay(self)
        self.timer_display.setVisible(False)
        self.timer_display.pause_toggled.connect(self.timer.toggle_pause)
        self.timer_display.reset_requested.connect(self.timer.reset)
        self.timer_display.close_requested.connect(self.timer.reset)
        self.timer.tick.connect(self._refresh_timer_display)
        self.timer.phase_changed.connect(self._refresh_timer_display)
        self.timer.state_changed.connect(self._on_timer_state)
        self.timer.finished.connect(self._on_timer_finished)
        layout.addWidget(self.timer_display)

        # The five tool buttons are built in the user-defined order (stored
        # in config["tool_order"]); Settings and Close stay pinned at the end.
        tool_specs = {
            "screenshot": (ICON_SCREENSHOT, "screenshot"),
            "annotation": (ICON_ANNOTATION, "annotation"),
            "translate": (ICON_TRANSLATE, "translate"),
            "clipboard": (ICON_CLIPBOARD, "clipboard"),
            "search": (ICON_SEARCH, "search"),
            "timer": (ICON_TIMER, "timer"),
        }
        order = Config().get(
            "tool_order",
            ["screenshot", "annotation", "translate", "clipboard", "search"])

        # All capsule icons must keep their original colour on hover (task 1):
        # only the translucent plate animates, never a colour tint on the SVG.
        self._tool_buttons = {}
        for key in order:
            if key not in tool_specs:
                continue
            svg, tooltip_key = tool_specs[key]
            btn = GlassIconButton(svg, I18n.tr(tooltip_key), colorize_icon=False)
            self._tool_buttons[key] = btn
            layout.addWidget(btn)
        # Fallback: if a stale saved order misses a tool, append it so the
        # capsule never loses a button.
        for key, (svg, tooltip_key) in tool_specs.items():
            if key in self._tool_buttons:
                continue
            btn = GlassIconButton(svg, I18n.tr(tooltip_key), colorize_icon=False)
            self._tool_buttons[key] = btn
            layout.addWidget(btn)

        self.btn_settings = GlassIconButton(
            ICON_SETTINGS, I18n.tr("settings"), colorize_icon=False)
        layout.addWidget(self.btn_settings)

        self.btn_close = GlassIconButton(
            ICON_CLOSE, I18n.tr("close"),
            hover_color="#e03131",
            hover_bg_color=QColor(224, 49, 49),
            colorize_icon=False
        )
        layout.addWidget(self.btn_close)

        # Stable references used by CapRiseApp.connect_signals().
        self.btn_screenshot = self._tool_buttons["screenshot"]
        self.btn_annotation = self._tool_buttons["annotation"]
        self.btn_translate = self._tool_buttons["translate"]
        self.btn_clipboard = self._tool_buttons["clipboard"]
        self.btn_search = self._tool_buttons["search"]
        self.btn_timer = self._tool_buttons["timer"]

        # Apply the user's per-tool show/hide choice (config["hidden_tools"]).
        self.set_tools_hidden(Config().get("hidden_tools", []))
        # Establish the base width (timer strip hidden at this point).
        self.setFixedWidth(self.BASE_WIDTH)

    # ----- timer strip -----

    def _sync_timer_width(self):
        """Resize the capsule to fit the timer strip (or back to base width)
        and keep it horizontally centered. Called only when the strip shows or
        hides — the monospace HH:MM:SS keeps the width constant while ticking,
        so there is no per-second churn or re-centering."""
        # isHidden() (not isVisible()) so the decision is independent of
        # whether the parent capsule itself is currently shown.
        if not self.timer_display.isHidden():
            # Reserve the layout's full ideal width. The tool buttons are all
            # fixed-size, so this is the only width that guarantees the timer
            # strip receives its complete sizeHint — a fixed BASE_WIDTH plus
            # the strip would let the 8 buttons squeeze the strip below its
            # minimum and push the label under the reset/stop controls.
            self.setFixedWidth(self.layout().sizeHint().width())
        else:
            self.setFixedWidth(self.BASE_WIDTH)
        if self.isVisible():
            self._recenter()

    def _recenter(self):
        """Re-center horizontally on the current screen, keeping the Y."""
        screen = self._get_screen_geo()
        self.move((screen.width() - self.width()) // 2 + screen.x(), self.y())

    def _refresh_timer_display(self, *_):
        phase = self.timer.phase()
        if phase is None:
            return
        self.timer_display.show_phase(
            phase, self.timer.remaining(), self.timer.is_paused())

    def _on_timer_state(self, state):
        if state == "running":
            self.timer_display.setVisible(True)
            # Set the time text first so the width sync below sizes the
            # capsule to the actual content (the label is now dynamic width).
            self._refresh_timer_display()
            self._sync_timer_width()
            # A timer started from the capsule is already visible; this also
            # covers edge cases where the strip must surface the countdown.
            self.show_capsule()
        elif state == "paused":
            self._refresh_timer_display()
            # The pause label can be narrower than the running one (e.g.
            # 倒计时 -> 暂停); re-fit the capsule so the gaps stay balanced.
            self._sync_timer_width()
        elif state == "idle":
            # Reset / countdown finished: retract the strip.
            self.timer_display.setVisible(False)
            self._sync_timer_width()

    def _on_timer_finished(self, phase):
        """A phase completed: beep + transient notice in the strip. Pomodoro
        auto-continues into the next phase; a plain countdown additionally
        pops an independent notice card (visible even if the capsule is
        hidden) and then retracts the strip."""
        QApplication.beep()
        key = {"focus": "timer_finished_focus",
               "break": "timer_finished_break"}.get(
                   phase, "timer_finished_countdown")
        self.timer_display.show_notice(I18n.tr(key))
        if phase == "countdown":
            self._timer_notice = TimerNoticeOverlay(I18n.tr(key))
            self._timer_notice.show()
            QTimer.singleShot(2700, self._retract_timer_strip)

    def _retract_timer_strip(self):
        # If a new timer was started meanwhile, keep the strip up.
        if not self.timer.is_active():
            self.timer_display.setVisible(False)
            self._sync_timer_width()

    def set_tools_hidden(self, hidden_keys):
        """Show/hide tool buttons per the `hidden_tools` config list.

        Hidden buttons stay in the layout with their signal connections and
        global hotkey bindings intact — they just render invisible, so the
        capsule stays compact while the user can still trigger them by
        hotkey."""
        hidden = set(hidden_keys or [])
        for key, btn in self._tool_buttons.items():
            btn.setVisible(key not in hidden)

    def reorder_tools(self, order):
        """Reorder the tool buttons to match `order` (a list of tool keys).

        The existing button objects are reused and only their position in the
        layout changes, so the signal connections made in CapRiseApp stay
        valid. Settings and Close always remain pinned at the end.

        A stale saved order (e.g. from before a new tool was added) is
        tolerated: any tool missing from `order` is appended so the capsule
        never loses a button."""
        layout = self.layout()
        for btn in self._tool_buttons.values():
            layout.removeWidget(btn)
        anchor = self.btn_settings  # insert before Settings
        inserted = set()
        for key in order:
            btn = self._tool_buttons.get(key)
            if btn is not None:
                layout.insertWidget(layout.indexOf(anchor), btn)
                inserted.add(key)
        # Append tools missing from the saved order (new tools, stale config).
        for key, btn in self._tool_buttons.items():
            if key not in inserted:
                layout.insertWidget(layout.indexOf(anchor), btn)

    def setup_shadow(self):
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

    def setup_animations(self):
        self.pos_anim = QPropertyAnimation(self, b"pos")
        self.pos_anim.setDuration(300)
        self.pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.pos_anim.finished.connect(self._on_anim_finished)

        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setEasingCurve(QEasingCurve.OutCubic)

    def paintEvent(self, event):
        # Shared pill look (gradient body + family hairline) so the capsule
        # and the annotation sub-bar read as one design family.
        painter = QPainter(self)
        paint_pill(painter, self.rect(), 28)

    def showEvent(self, event):
        # Native HWND may (re)create on show — refresh the registry and apply
        # WS_EX_NOACTIVATE so mouse clicks on the capsule don't steal focus
        # from the user's input field either.
        FamilyWindowRegistry.refresh_hwnd(self)
        FamilyWindowRegistry.set_no_activate(self)
        super().showEvent(event)

    def set_clipboard_active(self, active):
        self.btn_clipboard.set_active(active)

    # ----- family-aware hide -----

    def _on_outside_click(self):
        """Called synchronously by GlobalMouseHook when a mouse-down lands
        outside any family window's HWND rect.

        Synchronous is intentional: it lets the hook fire BEFORE Qt finishes
        processing the click that triggered show_capsule (e.g. a tray-icon
        click that toggles the capsule). At that moment the family is still
        invisible, so the any_visible() check no-ops and we don't dismiss
        the capsule we're about to show. An async QTimer.singleShot(0) here
        would race the show_capsule() call and dismiss it on the next loop
        iteration.
        """
        if FamilyWindowRegistry.any_visible():
            self.hide_family_requested.emit()

    def request_family_hide(self):
        """Outside-click / focus-loss path. No debounce is needed: a real
        click is unambiguous user intent (unlike transient foreground
        flicker that the old poll had to ride out). Emits and lets the
        ClipboardManager drive hide_family() so the whole family collapses
        together — never hide_capsule() alone, which would strand the panel.
        """
        self.hide_family_requested.emit()

    def force_family_hide(self):
        """User-explicit path (ESC, close button, Ctrl+` toggle-off).
        Same emit as request_family_hide — both names kept for clarity
        (callers signal intent: force = bypass any gate, request = reactive).
        """
        self.hide_family_requested.emit()

    def shutdown(self):
        """Release OS resources. Call from CapRise.exit_app before quit."""
        self._mouse_hook.uninstall()

    def event(self, event):
        """ESC key when the capsule itself has keyboard focus."""
        if event.type() == QEvent.KeyPress:
            if isinstance(event, QKeyEvent) and event.key() == Qt.Key_Escape:
                if FamilyWindowRegistry.any_visible() and not self._animating:
                    self.force_family_hide()
                    return True
        return super().event(event)

    def hideEvent(self, event):
        self.pos_anim.stop()
        self.opacity_anim.stop()
        self._animating = False
        self._pending_hide = False
        super().hideEvent(event)

    def _get_screen_geo(self):
        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos)
        if not screen:
            screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _on_anim_finished(self):
        self._animating = False
        if self._pending_hide:
            self._pending_hide = False
            self.hide()

    def show_capsule(self):
        """Show the capsule, interrupting any in-progress hide animation by
        reversing from the current opacity / position. Safe to call when
        already fully shown (no-op) or while hiding (reverses)."""
        # Already fully shown and not hiding → nothing to do.
        if self.isVisible() and not self._pending_hide:
            return

        first_show = not self.isVisible()
        self._animating = True
        self._pending_hide = False
        screen = self._get_screen_geo()
        target_x = (screen.width() - self.width()) // 2 + screen.x()
        target_y = screen.y() + 30

        if first_show:
            # Boot from off-screen at zero opacity.
            self.setWindowOpacity(0.0)
            self.move(int(target_x), int(-self.height()))
            self.show()
            self.raise_()
            # NOTE: no activateWindow() — floats without taking focus.
            start_pos = QPoint(int(target_x), int(-self.height()))
            start_opacity = 0.0
        else:
            # Reverse from wherever the hide animation currently is.
            start_pos = self.pos()
            start_opacity = self.windowOpacity()

        self.pos_anim.stop()
        self.opacity_anim.stop()
        self.pos_anim.setStartValue(start_pos)
        self.pos_anim.setEndValue(QPoint(int(target_x), int(target_y)))
        self.opacity_anim.setStartValue(start_opacity)
        self.opacity_anim.setEndValue(1.0)
        self.pos_anim.start()
        self.opacity_anim.start()

    def hide_capsule(self):
        """Hide the capsule, interrupting any in-progress show animation by
        reversing from the current opacity / position. Safe to call when
        already hidden (no-op) or while showing (reverses)."""
        if not self.isVisible():
            return

        self._animating = True
        self._pending_hide = True
        current_pos = self.pos()

        self.pos_anim.stop()
        self.opacity_anim.stop()
        self.pos_anim.setStartValue(current_pos)
        self.pos_anim.setEndValue(
            QPoint(int(current_pos.x()), int(-self.height())))
        self.opacity_anim.setStartValue(self.windowOpacity())
        self.opacity_anim.setEndValue(0.0)
        self.pos_anim.start()
        self.opacity_anim.start()

    def hide_immediately(self):
        self._animating = False
        self._pending_hide = False
        self.pos_anim.stop()
        self.opacity_anim.stop()
        self.hide()

    def toggle_visibility(self):
        # User-explicit toggle: bypass the focus-loss debounce via
        # force_family_hide so a quick second press isn't swallowed by the
        # 500ms show-debounce. The animation itself is reversible, so we
        # no longer bail out when _animating is True.
        if self.isVisible() and not self._pending_hide:
            self.force_family_hide()
        else:
            self.show_capsule()
