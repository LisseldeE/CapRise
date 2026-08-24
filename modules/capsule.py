from ctypes import wintypes
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QGraphicsDropShadowEffect, QApplication
)
from PySide6.QtCore import (
    Qt, QPoint, QRect, QPropertyAnimation, QEasingCurve, QEvent,
    QAbstractNativeEventFilter, Signal, QTimer, Property
)
from PySide6.QtGui import (
    QPainter, QColor, QGuiApplication, QKeyEvent, QCursor, QRegion
)
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

    # Capsule height. The width is NOT hardcoded: it is measured from the
    # layout's natural sizeHint so the capsule always fits its current tool
    # cluster exactly (the cluster is 8 buttons now that the timer tool was
    # added — a hardcoded 396 from the 7-button era left the layout 54px
    # short, squeezing the gaps and pushing the tool buttons under the timer
    # strip's divider once the strip expanded).
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
        self.timer_display.reset_requested.connect(self.timer.reset_phase)
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
        # Establish the base width from the layout's natural size (timer
        # strip hidden at this point), so the capsule exactly fits its tool
        # cluster with full inter-button gaps.
        self.setFixedWidth(self.layout().sizeHint().width())

    # ----- timer strip -----

    def _expand_timer_strip(self):
        """Animate the capsule growing to fit the timer strip.

        The strip is made visible first so its full content width can be
        measured; the extent animation then glides the strip (and capsule) out
        to that target, revealing content left-to-right via the growing mask.
        The strip is dropped back out of the layout only once fully collapsed
        (handled inside _apply_timer_extent at extent 0)."""
        self.timer_display.setVisible(True)
        self._refresh_timer_display()
        self._full_strip_w = self.timer_display.layout().sizeHint().width()
        self._animate_timer_extent(1.0)

    def _collapse_timer_strip(self):
        """Animate the capsule shrinking back to its base width.

        The strip stays clipped in the layout as the extent falls, so the
        curtain closes smoothly; at extent 0 it is removed entirely."""
        self._animate_timer_extent(0.0)

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
            # Surface the capsule first (no-op when already visible), then
            # expand the strip — the whole bar glides wider around its center.
            self.show_capsule()
            self._expand_timer_strip()
        elif state == "paused":
            self._refresh_timer_display()
            # The pause label can be narrower than the running one (e.g.
            # 倒计时 -> 暂停); re-measure and settle the strip at full extent
            # so the gaps stay balanced (direct refit, no animation).
            self._full_strip_w = self.timer_display.layout().sizeHint().width()
            self._set_timer_extent(1.0)
        elif state == "idle":
            # Reset / countdown finished: retract the strip with an animation.
            self._collapse_timer_strip()

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
            self._collapse_timer_strip()

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

        # Animated expand/collapse of the timer strip: a 0..1 extent property
        # drives the strip's visible width (clipped by a mask for a clean
        # curtain reveal) and the capsule's width (set to exactly what the
        # layout needs), so the strip glides out on start and back in on
        # reset / finish without any clipped or residual content.
        self._timer_extent = 0.0
        self._full_strip_w = 0
        self._timer_width_anim = QPropertyAnimation(self, b"timerExpand")
        self._timer_width_anim.setDuration(300)
        self._timer_width_anim.setEasingCurve(QEasingCurve.OutCubic)

    # ----- timer strip expand / collapse -----

    def _get_timer_extent(self):
        return self._timer_extent

    def _set_timer_extent(self, p):
        self._timer_extent = float(p)
        self._apply_timer_extent(self._timer_extent)

    timerExpand = Property(float, _get_timer_extent, _set_timer_extent)

    def _apply_timer_extent(self, p):
        """Sync the strip width, mask and capsule width to the expand extent.

        The strip is clipped to a growing width (curtain reveal), so its label
        and buttons never spill past the plate while it is only partially
        expanded. The capsule width is always the layout's natural sizeHint —
        the divider (the strip's right edge) is thereby locked to the exact
        boundary between the strip content and the tool cluster, so no tool
        button can ever be pushed under the divider. At extent 0 the strip
        leaves the layout, leaving the plain base capsule with no residue."""
        p = max(0.0, min(1.0, p))
        if p <= 0.001:
            if not self.timer_display.isHidden():
                self.timer_display.setVisible(False)
            self.timer_display.clearMask()
            w = self.layout().sizeHint().width()
            if w != self.width():
                self.setFixedWidth(w)
            if self.isVisible():
                self._recenter()
            return
        if self.timer_display.isHidden():
            self.timer_display.setVisible(True)
        strip_w = int(round(p * self._full_strip_w))
        self.timer_display.setFixedWidth(strip_w)
        if p >= 0.999:
            self.timer_display.clearMask()
        else:
            self.timer_display.setMask(QRegion(
                QRect(0, 0, max(1, strip_w), self.timer_display.height())))
        w = self.layout().sizeHint().width()
        if w != self.width():
            self.setFixedWidth(w)
        if self.isVisible():
            self._recenter()

    def _animate_timer_extent(self, target):
        self._timer_width_anim.stop()
        self._timer_width_anim.setStartValue(self._timer_extent)
        self._timer_width_anim.setEndValue(float(target))
        self._timer_width_anim.start()

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
        self.timer.shutdown()

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
