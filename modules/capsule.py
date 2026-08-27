from ctypes import wintypes
from PySide6.QtWidgets import (
    QWidget, QGraphicsDropShadowEffect, QApplication
)
from PySide6.QtCore import (
    Qt, QPoint, QRect, QRectF, QPropertyAnimation, QEasingCurve, QEvent,
    QAbstractNativeEventFilter, Signal, QTimer, Property
)
from PySide6.QtGui import (
    QPainter, QColor, QGuiApplication, QKeyEvent, QCursor, QRegion,
    QPainterPath
)
from modules.icons import (
    ICON_SCREENSHOT, ICON_ANNOTATION, ICON_TRANSLATE, ICON_SETTINGS,
    ICON_CLOSE, ICON_CLIPBOARD, ICON_SEARCH, ICON_TIMER, ICON_PICKER
)
from modules.i18n import I18n
from modules.family import FamilyWindowRegistry
from modules.global_mouse_hook import GlobalMouseHook
from modules.global_esc_hook import GlobalEscapeHook
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

    # Manual-layout metrics (mirror the approved Plan B preview): the capsule
    # has no QHBoxLayout — every child is positioned by _layout_manual() so the
    # timer strip can span its full final width while the capsule width still
    # grows dynamically. These match the old layout's margins/spacing exactly.
    MARGIN = 14
    TOP = 6
    BTN = 44
    SPACING = 10

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

        # Global low-level ESC hook. The capsule bar never takes activation
        # focus (WA_ShowWithoutActivating + WS_EX_NOACTIVATE), so while only
        # the bar is up the user's focus is still in another app and the Qt
        # nativeEventFilter ESC above goes to that app instead. The LL hook
        # sees ESC system-wide regardless of focus, so the bar collapses too.
        self._esc_hook = GlobalEscapeHook()
        self._esc_hook.on_escape = self._on_global_escape
        self._esc_hook.install()

    def setup_ui(self):
        # No QHBoxLayout: every child is positioned manually by _layout_manual()
        # so the timer strip can span its full final width (divider locked at
        # the final position) while the capsule width still grows dynamically —
        # the approved Plan B preview.

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

        # The five tool buttons are built in the user-defined order (stored
        # in config["tool_order"]); Settings and Close stay pinned at the end.
        tool_specs = {
            "screenshot": (ICON_SCREENSHOT, "screenshot"),
            "annotation": (ICON_ANNOTATION, "annotation"),
            "translate": (ICON_TRANSLATE, "translate"),
            "clipboard": (ICON_CLIPBOARD, "clipboard"),
            "search": (ICON_SEARCH, "search"),
            "timer": (ICON_TIMER, "timer"),
            "picker": (ICON_PICKER, "color_picker"),
        }
        order = Config().get(
            "tool_order",
            ["screenshot", "annotation", "translate", "clipboard", "search",
             "timer", "picker"])

        # All capsule icons must keep their original colour on hover (task 1):
        # only the translucent plate animates, never a colour tint on the SVG.
        self._tool_buttons = {}
        self._tool_order = []
        for key in order:
            if key not in tool_specs:
                continue
            svg, tooltip_key = tool_specs[key]
            btn = GlassIconButton(svg, I18n.tr(tooltip_key), colorize_icon=False)
            btn.setParent(self)
            self._tool_buttons[key] = btn
            self._tool_order.append(key)
        # Fallback: if a stale saved order misses a tool, append it so the
        # capsule never loses a button.
        for key, (svg, tooltip_key) in tool_specs.items():
            if key in self._tool_buttons:
                continue
            btn = GlassIconButton(svg, I18n.tr(tooltip_key), colorize_icon=False)
            btn.setParent(self)
            self._tool_buttons[key] = btn
            self._tool_order.append(key)

        self.btn_settings = GlassIconButton(
            ICON_SETTINGS, I18n.tr("settings"), colorize_icon=False)
        self.btn_settings.setParent(self)

        self.btn_close = GlassIconButton(
            ICON_CLOSE, I18n.tr("close"),
            hover_color="#e03131",
            hover_bg_color=QColor(224, 49, 49),
            colorize_icon=False
        )
        self.btn_close.setParent(self)

        # Stable references used by CapRiseApp.connect_signals().
        self.btn_screenshot = self._tool_buttons["screenshot"]
        self.btn_annotation = self._tool_buttons["annotation"]
        self.btn_translate = self._tool_buttons["translate"]
        self.btn_clipboard = self._tool_buttons["clipboard"]
        self.btn_search = self._tool_buttons["search"]
        self.btn_timer = self._tool_buttons["timer"]
        self.btn_color_picker = self._tool_buttons["picker"]

        # Full ordered toolbar: tool buttons in user order + settings + close.
        self._toolbar = [self._tool_buttons[k] for k in self._tool_order] \
            + [self.btn_settings, self.btn_close]
        self._toolbar_w = len(self._toolbar) * self.BTN \
            + (len(self._toolbar) - 1) * self.SPACING

        # Apply the user's per-tool show/hide choice (config["hidden_tools"]).
        self.set_tools_hidden(Config().get("hidden_tools", []))
        # Establish the base (collapsed) width manually — the capsule exactly
        # fits its tool cluster with full inter-button gaps.
        self._layout_manual(0)

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
        """A phase completed: beep + an independent notice card (visible even
        if the capsule is hidden). Pomodoro auto-continues into the next
        phase; the card auto-closes after a couple of seconds. The longer
        phase messages (e.g. 专注结束，进入休息) don't fit the capsule strip,
        so they pop as a standalone small capsule like the countdown one."""
        QApplication.beep()
        key = {"focus": "timer_finished_focus",
               "break": "timer_finished_break"}.get(
                   phase, "timer_finished_countdown")
        self._timer_notice = TimerNoticeOverlay(I18n.tr(key))
        self._timer_notice.show()
        if phase == "countdown":
            # Collapse the strip right away (the countdown has ended); the
            # notice pops independently, so there's no need to hold the strip
            # open while the card is showing.
            self._retract_timer_strip()

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
        manual toolbar list changes, so the signal connections made in
        CapRiseApp stay valid. Settings and Close always remain pinned at the
        end.

        A stale saved order (e.g. from before a new tool was added) is
        tolerated: any tool missing from `order` is appended so the capsule
        never loses a button."""
        self._tool_order = [k for k in order if k in self._tool_buttons]
        for k in self._tool_buttons:
            if k not in self._tool_order:
                self._tool_order.append(k)
        self._toolbar = [self._tool_buttons[k] for k in self._tool_order] \
            + [self.btn_settings, self.btn_close]
        self._layout_manual(self._current_strip_w())

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

        # Left-right "Dynamic-island" show/hide (alt. to the vertical fly-in).
        # The window stays parked at its final top-centred position while a
        # 0..1 extent drives a rounded mask that grows symmetrically out from
        # a small centre pill to the full width, so the glass plate "expands"
        # out to both sides; opacity fades in along the curve. See
        # _anim_mode() for how it is chosen vs. the vertical animation.
        self._dynamic_expand = 0.0
        self._expand_anim = QPropertyAnimation(self, b"dynamicExpand")
        self._expand_anim.setDuration(300)
        self._expand_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._expand_anim.finished.connect(self._on_anim_finished)

    # ----- timer strip expand / collapse -----

    def _get_timer_extent(self):
        return self._timer_extent

    def _set_timer_extent(self, p):
        self._timer_extent = float(p)
        self._apply_timer_extent(self._timer_extent)

    timerExpand = Property(float, _get_timer_extent, _set_timer_extent)

    def _apply_timer_extent(self, p):
        """Sync the strip mask and capsule geometry to the expand extent.

        Plan B (approved preview): the strip's widget spans its full final
        width, so its hairline divider and the reset/stop column stay locked
        at the final divider position while the capsule grows. A right-aligned
        mask [strip_w-reveal, strip_w] reveals the content anchored to the
        current divider and extends it leftward (the strip's left side stays
        blank briefly while it is still expanding); the part of the strip past
        the capsule edge is clipped by the parent. The capsule width grows
        with strip_w and stays centered. At extent 0 the strip leaves the
        scene, leaving the plain base capsule with no residue."""
        p = max(0.0, min(1.0, p))
        if p <= 0.001:
            if not self.timer_display.isHidden():
                self.timer_display.setVisible(False)
            self.timer_display.clearMask()
            self._layout_manual(0)
            if self.isVisible():
                self._recenter()
            return
        if self.timer_display.isHidden():
            self.timer_display.setVisible(True)
        strip_w = int(round(p * self._full_strip_w))
        if p >= 0.999:
            self.timer_display.clearMask()
        else:
            # Right-aligned reveal anchored to the current divider (strip_w):
            # show the rightmost `reveal` pixels so content slides out from
            # the divider toward the left (matches the approved preview).
            reveal = int(round((p ** 1.5) * self._full_strip_w))
            reveal = min(reveal, strip_w)
            if reveal >= self._full_strip_w - 1:
                self.timer_display.clearMask()
            else:
                x0 = max(0, strip_w - reveal)
                self.timer_display.setMask(QRegion(
                    QRect(x0, 0, max(1, reveal), self.timer_display.height())))
        self._layout_manual(strip_w)
        if self.isVisible():
            self._recenter()

    def _current_strip_w(self):
        """Current strip width in px (0 when the strip is not shown)."""
        if self.timer_display.isVisible():
            return int(round(self._timer_extent * self._full_strip_w))
        return 0

    def _layout_manual(self, strip_w):
        """Position the timer strip and the tool cluster by hand.

        Mirrors the approved Plan B preview: the strip occupies its full final
        width (right edge = final divider, clipped by the capsule edge), while
        the capsule width grows with strip_w and the tool cluster shifts right
        past the strip. Collapsed (strip_w == 0) reproduces the old layout's
        base geometry exactly (tools start at the left margin)."""
        if strip_w > 0:
            cw = self.MARGIN + strip_w + self.SPACING + self._toolbar_w \
                + self.MARGIN
            x = self.MARGIN + strip_w + self.SPACING
        else:
            cw = self.MARGIN + self._toolbar_w + self.MARGIN
            x = self.MARGIN
        self.setFixedWidth(cw)
        if self.timer_display.isVisible():
            self.timer_display.setGeometry(
                self.MARGIN, self.TOP, self._full_strip_w,
                self.timer_display.HEIGHT)
        for b in self._toolbar:
            b.setGeometry(x, self.TOP, self.BTN, self.BTN)
            x += self.BTN + self.SPACING

    def _animate_timer_extent(self, target):
        self._timer_width_anim.stop()
        self._timer_width_anim.setStartValue(self._timer_extent)
        self._timer_width_anim.setEndValue(float(target))
        self._timer_width_anim.start()

    # ----- show/hide animation mode -----

    def _anim_mode(self):
        """'vertical' flies the bar in from the top; 'dynamic' expands it
        left-right from a centre point like a Dynamic Island."""
        return Config().get("capsule_anim", "vertical")

    # ----- left-right (dynamic) expand / collapse -----

    def _get_dynamic_expand(self):
        return self._dynamic_expand

    def _set_dynamic_expand(self, p):
        self._dynamic_expand = float(p)
        self._apply_dynamic_mask(self._dynamic_expand)

    dynamicExpand = Property(float, _get_dynamic_expand, _set_dynamic_expand)

    def _apply_dynamic_mask(self, p):
        """Clip the parked window to a centre-anchored pill that grows with p.

        The glass plate is masked into an expanding rounded pill, while each
        tool button fades in by the fraction of itself inside the pill, so
        buttons glide in smoothly from the centre out to both sides instead
        of popping at the mask edge (Dynamic-island style)."""
        p = max(0.0, min(1.0, p))
        w = self.width()
        h = self.height()
        cx = w / 2.0
        if p >= 0.999:
            self.clearMask()
            self.setWindowOpacity(1.0)
            self._set_buttons_reveal(1.0)
            return
        min_w = min(int(round(w * 0.25)), 96)
        reveal = int(round(min_w + (w - min_w) * p))
        reveal = max(1, min(reveal, w))
        x = (w - reveal) // 2
        # QRegion() does not accept a QPainterPath on all PySide6 builds, so
        # rasterise the rounded pill to a polygon (the region API wants a
        # QPolygon or Sequence[QPoint]).
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, 0, reveal, h), 28, 28)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        # Fade each button in by the fraction of itself inside the pill, so
        # buttons enters smoothly instead of popping at the mask edge.
        pill_l = cx - reveal / 2.0
        pill_r = cx + reveal / 2.0
        for b in self._toolbar:
            bl = b.x()
            br = bl + self.BTN
            overlap = (min(br, pill_r) - max(bl, pill_l)) / float(self.BTN)
            overlap = max(0.0, min(1.0, overlap))
            o = overlap * overlap * (3 - 2 * overlap)  # smoothstep
            b.set_reveal(o)

    def _set_buttons_reveal(self, o):
        for b in self._toolbar:
            b.set_reveal(float(o))

    def _reset_buttons_hover(self):
        """Force every tool button back to its idle state. Used when the bar
        is collapsed so no hover highlight survives a hide/show cycle."""
        for b in self._toolbar:
            b.clear_hover()
            b.set_reveal(1.0)

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

    def _on_global_escape(self):
        """ESC caught system-wide by the low-level keyboard hook, including
        when the capsule bar is up but the user's focus is in another app.
        Mirrors the native ESC filter's guard before collapsing the family.
        """
        if FamilyWindowRegistry.any_visible() and not self._animating:
            self.force_family_hide()

    def shutdown(self):
        """Release OS resources. Call from CapRise.exit_app before quit."""
        self._mouse_hook.uninstall()
        self._esc_hook.uninstall()
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
        self._expand_anim.stop()
        self._dynamic_expand = 0.0
        self.clearMask()
        self.setWindowOpacity(1.0)
        self._set_buttons_reveal(1.0)
        # Hiding never delivers a leaveEvent, so a hovered button keeps its
        # lit `_t`; clear it here so the highlight can't linger on re-show.
        for b in self._toolbar:
            b.clear_hover()
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

        # Dynamic (left-right) mode parks the window at its final geometry and
        # grows a centre-anchored mask out to both sides. Reverses cleanly
        # from wherever a previous hide animation currently is. Opacity is kept
        # at 1.0 for the reveal (pure expand), but a parallel fade is used on
        # hide so no clipped content lingers at the final frame.
        if self._anim_mode() == "dynamic":
            self.pos_anim.stop()
            self.opacity_anim.stop()
            self.setWindowOpacity(1.0)
            if first_show:
                self._apply_dynamic_mask(0.0)
                self.move(int(target_x), int(target_y))
                self.show()
                self.raise_()
            self._expand_anim.stop()
            self._expand_anim.setStartValue(self._dynamic_expand)
            self._expand_anim.setEndValue(1.0)
            self._expand_anim.start()
            return

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
        # Collapse is the natural reset point: force every button back to its
        # idle state so a hovered highlight can't survive into the next show.
        self._reset_buttons_hover()

        # Dynamic mode: close the centre-anchored mask back to a pill while fading
        # out in parallel, so no clipped content is left visible at the final
        # frame before the window hides.
        if self._anim_mode() == "dynamic":
            self.pos_anim.stop()
            self._expand_anim.stop()
            self._expand_anim.setStartValue(self._dynamic_expand)
            self._expand_anim.setEndValue(0.0)
            self._expand_anim.start()
            self.opacity_anim.stop()
            self.opacity_anim.setStartValue(self.windowOpacity())
            self.opacity_anim.setEndValue(0.0)
            self.opacity_anim.start()
            return

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
