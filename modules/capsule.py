"""
胶囊栏
主胶囊栏窗口，承载各功能入口并管理家族窗口显示
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
from ctypes import wintypes
from PySide6.QtWidgets import (
    QWidget, QGraphicsDropShadowEffect, QApplication
)
from PySide6.QtCore import (
    Qt, QPoint, QRectF, QPropertyAnimation, QVariantAnimation, QEasingCurve,
    QEvent, QTimer, QAbstractNativeEventFilter, Signal, Property
)
from PySide6.QtGui import (
    QPainter, QColor, QGuiApplication, QKeyEvent, QCursor, QRegion,
    QPainterPath
)
from modules.icons import (
    ICON_SCREENSHOT, ICON_ANNOTATION, ICON_TRANSLATE, ICON_SETTINGS,
    ICON_CLOSE, ICON_CLIPBOARD, ICON_SEARCH, ICON_TIMER, ICON_PICKER,
    ICON_RECORD
)
from modules.i18n import I18n
from modules.family import FamilyWindowRegistry
from modules.global_mouse_hook import GlobalMouseHook
from modules.global_esc_hook import GlobalEscapeHook
from modules.widgets import GlassIconButton, paint_pill
from modules.config import Config
from modules.timer import TimerManager, TimerNoticeOverlay
from modules.music import MusicManager
from modules.recorder import ScreenRecorder
from modules.status_strip import StatusStrip, RecordMiniPill

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
    # current content (status strip + visible tool cluster) so the capsule
    # always fits exactly.
    BASE_HEIGHT = 56

    # mini 态胶囊背景高度：比完整胶囊矮一截（上下对称内缩），整体存在感很小。
    # 与 mini 内容层同高，两者都以窗口竖直中线对齐，所以过渡中也不会错位。
    MINI_PILL_H = RecordMiniPill.H

    # Manual-layout metrics: the capsule has no QHBoxLayout — every child is
    # positioned by _layout_manual() so the status strip and the tool cluster
    # can be re-laid-out (and the capsule re-centred) as segments come and go.
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
        # 状态条宽度（像素）：动画属性 stripWidth 驱动，栏宽 = 边距 + 状态条 +
        # 间距 + 工具组 + 边距。声明在前，setup_ui 里就要用到。
        self._strip_w = 0.0
        self._full_strip_w = 0
        self._music_enabled = False
        # mini 态（录制中收起成的小胶囊）：miniT 0=完整胶囊、1=mini，
        # 由 _mini_width_now() 把窗口宽度在完整宽度与 mini 宽度间插值。
        self._mini_on = False
        self._mini_done = False
        self._mini_t = 0.0
        self._mini_w = 120
        self._mini_extra = 0.0
        self._mini_grow_extra = 16   # 完成态「自动展开一点点」的像素数
        self._outside_click = False  # 本次收起是否由外部点击触发
        self._fade_out = False       # 完成态淡出中（淡出结束即隐藏）
        self._mini_isolated = False  # mini 态已把工具组 / 状态条整体隐藏
        self._full_w = 0             # 完整布局下的窗口宽度
        self._done_timer = QTimer(self)
        self._done_timer.setSingleShot(True)
        self._done_timer.timeout.connect(self._finish_mini_done)
        # 先建动画对象：状态条在 setup_ui 里可能立刻触发宽度动画。
        self.setup_animations()
        self.setup_ui()
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
        # so the status strip can grow / shrink while the capsule width follows.

        # 计时管理器：倒计时与番茄钟的唯一状态源，展示交给状态条。
        self.timer = TimerManager(self)
        self.timer.finished.connect(self._on_timer_finished)

        # 音乐管理器（SMTC）：同样只做状态源，展示交给状态条。
        self.music = MusicManager(self)

        # 进行中状态条（录制 | 音乐 | 倒计时）并入主胶囊栏左侧。
        self.status = StatusStrip(self.timer, self.music, self)
        self.status.layout_changed.connect(self._on_status_layout)
        self.status.stop_record_requested.connect(self.stop_record)

        # 录屏：状态条展示录制中，完成 / 失败通过 _show_notice 就地提示。
        self.recorder = ScreenRecorder(self)
        self.recorder.started.connect(self._on_record_started)
        self.recorder.finished.connect(self._on_record_finished)
        self.recorder.failed.connect(self._on_record_failed)

        # 录制中的 mini 小胶囊内容层（胶囊外形仍由本窗口 paint_pill 绘制）。
        self._mini_pill = RecordMiniPill(self)
        self._mini_pill.stop_requested.connect(self._on_mini_stop)
        self._mini_pill.expand_requested.connect(self._expand_from_mini)
        self._mini_pill.hide()

        # The five tool buttons are built in the user-defined order (stored
        # in config["tool_order"]); Settings and Close stay pinned at the end.
        tool_specs = {
            "screenshot": (ICON_SCREENSHOT, "screenshot"),
            "annotation": (ICON_ANNOTATION, "annotation"),
            "translate": (ICON_TRANSLATE, "translate"),
            "clipboard": (ICON_CLIPBOARD, "clipboard"),
            "search": (ICON_SEARCH, "search"),
            "timer": (ICON_TIMER, "timer"),
            "record": (ICON_RECORD, "record"),
            "picker": (ICON_PICKER, "color_picker"),
        }
        order = Config().get(
            "tool_order",
            ["screenshot", "annotation", "translate", "clipboard", "search",
             "timer", "record", "picker"])

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
        self.btn_record = self._tool_buttons["record"]
        self.btn_color_picker = self._tool_buttons["picker"]

        # Full ordered toolbar: tool buttons in user order + settings + close.
        self._toolbar = [self._tool_buttons[k] for k in self._tool_order] \
            + [self.btn_settings, self.btn_close]

        # Apply the user's per-tool show/hide choice (config["hidden_tools"]).
        self.set_tools_hidden(Config().get("hidden_tools", []))
        # Establish the base (collapsed) width manually — the capsule exactly
        # fits its tool cluster with full inter-button gaps.
        self._layout_manual(0)

        # 音乐状态段：读取开关并同步给状态条（关闭时不起轮询线程）。
        self._music_enabled = bool(Config().get("music_capsule_enabled", True))
        if self._music_enabled:
            self.music.start()
        self.status.set_music_enabled(self._music_enabled)

    # ----- 状态条宽度 -----

    def _on_status_layout(self):
        """状态条内容变化：把栏宽动画到新目标。

        互斥互换展开段时总宽不变（目标不变），所以栏宽恒定；新增 / 结束
        段才会改变目标宽度，此时平滑过渡。"""
        self._full_strip_w = self.status.content_width()
        self._animate_strip_width(self._full_strip_w)

    def _get_strip_w(self):
        return self._strip_w

    def _set_strip_w(self, w):
        self._strip_w = float(w)
        self._layout_manual(self._strip_w)
        if self.isVisible():
            self._recenter()

    stripWidth = Property(float, _get_strip_w, _set_strip_w)

    def _animate_strip_width(self, target):
        """栏宽动画：覆盖出现(0→full)、内容增删(cur→new)、结束(full→0)。"""
        target = float(target)
        if not self.isVisible():
            # 收起状态下直接落位，避免在不可见窗口上空跑动画。
            self._strip_w_anim.stop()
            self._set_strip_w(target)
            return
        if abs(self._strip_w - target) < 0.5:
            return
        self._strip_w_anim.stop()
        self._strip_w_anim.setStartValue(self._strip_w)
        self._strip_w_anim.setEndValue(target)
        self._strip_w_anim.start()

    def _recenter(self):
        """在当前屏幕水平居中，保持 Y。"""
        x = self._resting_x()
        # 飞入动画进行中时 pos 由动画驱动，直接 move 会被动画拽回；改写终点。
        if (self.pos_anim.state() == QPropertyAnimation.Running
                and not self._pending_hide):
            end = self.pos_anim.endValue()
            if end is not None:
                self.pos_anim.setEndValue(QPoint(x, end.y()))
            return
        self.move(x, self.y())

    def _resting_x(self, screen=None):
        """居中左边缘（栏宽变化后重新计算）。"""
        if screen is None:
            screen = self._get_screen_geo()
        return (screen.width() - self.width()) // 2 + screen.x()

    # ----- 录屏 -----

    def toggle_record(self):
        """热键 / 设置入口：正在录制则停止，否则开始。"""
        if self.recorder.is_recording():
            self.stop_record()
        else:
            self.start_record()

    def start_record(self):
        # 录制状态显示在状态条上，先保证胶囊栏可见。
        self.show_capsule()
        self.recorder.start()

    def stop_record(self):
        self.recorder.stop()

    def _on_record_started(self):
        self.btn_record.set_active(True)
        self.status.record_started()

    def _on_record_finished(self, path):
        self.btn_record.set_active(False)
        self.status.record_stopped()
        if self._mini_done:
            # mini 上点停止：完成态流程已接管，不再重复弹提示卡
            return
        if self._mini_on:
            # 录制在 mini 态被结束（如热键）：同样走完成态再淡出
            self._enter_mini_done()
            return
        self._show_notice(I18n.tr("record_saved"), ICON_RECORD, slot="record")

    def _on_record_failed(self, detail):
        self.btn_record.set_active(False)
        self.status.record_stopped()
        self._mini_done = False
        self._done_timer.stop()
        if self._mini_on:
            # mini 层不能留着：直接收掉，失败提示卡是独立窗口仍可见
            self.hide_immediately()
        self._show_notice(
            I18n.tr("record_failed_detail", detail=detail), ICON_RECORD,
            slot="record")

    def _on_mini_stop(self):
        """mini 上的停止按钮：同步收尾后停在「录制完成」态。"""
        # 先打标记：recorder.stop() 同步收尾，finished 会在返回前触发
        self._mini_done = True
        self.recorder.stop()
        if not self._mini_done:
            return            # 失败分支已清标记并弹提示
        self._enter_mini_done()

    def _enter_mini_done(self):
        """完成态：文案切「录制完成」+ 加宽一点点，停留后淡出隐藏。"""
        self._mini_done = True
        self._mini_pill.set_done(True)
        self._mini_w = self._mini_pill.sizeHint().width()
        self._grow.stop()
        self._grow.setStartValue(self._mini_extra)
        self._grow.setEndValue(1.0)
        self._grow.start()
        self._done_timer.start(1200)

    def _finish_mini_done(self):
        """完成态结束：整窗淡出后彻底隐藏（录制已结束，mini 态不再成立）。"""
        if not self._mini_done:
            return
        self._mini_done = False
        self._animating = True
        self._fade_out = True
        self.opacity_anim.stop()
        self.opacity_anim.setStartValue(self.windowOpacity())
        self.opacity_anim.setEndValue(0.0)
        self.opacity_anim.start()

    def _on_fade_finished(self):
        """淡出结束：只有完成态淡出才顺带隐藏整窗（其余淡出是显示动画）。"""
        if self._fade_out:
            self._fade_out = False
            self.hide_immediately()

    def _show_notice(self, message, icon=ICON_TIMER, slot="timer"):
        """完成提示：胶囊栏在屏上时就地伸缩状态条显示，不再另开窗口。

        提示收在状态条里（占用展开位、到点自动撤下），胶囊栏宽度随之伸出去
        再缩回来。slot 是这条提示报告的状态段，决定它排在状态条的哪一格 ——
        录制完成的提示必须落在录制段那一格，不能跑到倒计时那格去。

        只有胶囊栏本身不可见时（例如倒计时期间用户把它收起了、或正处于录制
        mini 态）才回退到独立提示小胶囊 —— 否则用户什么也看不到。"""
        if self.isVisible() and not self._mini_on:
            self.status.show_notice(message, icon, slot)
            return
        self._notice = TimerNoticeOverlay(message, icon)
        self._notice.show()

    def _on_timer_finished(self, phase):
        """一个阶段结束：蜂鸣 + 完成提示。

        番茄钟自动进入下一阶段（状态条随之刷新）；倒计时结束后计时器变为
        非活动，状态条自行收起，无需额外处理。"""
        QApplication.beep()
        key = {"focus": "timer_finished_focus",
               "break": "timer_finished_break"}.get(
                   phase, "timer_finished_countdown")
        self._show_notice(I18n.tr(key))

    # ----- 音乐开关 -----

    def set_music_enabled(self, enabled):
        """开关音乐状态段（设置页开关）并持久化。

        关闭会直接停掉 SMTC 轮询线程 —— 功能关闭时不做任何后台工作。"""
        enabled = bool(enabled)
        self._music_enabled = enabled
        Config().set("music_capsule_enabled", enabled)
        if enabled:
            self.music.start()
        else:
            self.music.stop()
        self.status.set_music_enabled(enabled)

    # ----- tools -----

    def set_tools_hidden(self, hidden_keys):
        """Show/hide tool buttons per the `hidden_tools` config list.

        Hidden buttons stay in the layout with their signal connections and
        global hotkey bindings intact — they just render invisible, so the
        capsule stays compact while the user can still trigger them by
        hotkey."""
        # Track the hidden keys explicitly instead of consulting isVisible():
        # during startup the parent capsule is not yet shown, so every child's
        # isVisible() is False regardless of intent, which would collapse the
        # bar to nothing. This set is the single source of truth for layout.
        self._hidden_tools = set(hidden_keys or [])
        for key, btn in self._tool_buttons.items():
            btn.setVisible(key not in self._hidden_tools
                           and not self._mini_isolated)
        # Re-measure and re-lay-out: a hidden tool must collapse the bar to
        # fit the remaining buttons (and re-center) instead of leaving a blank
        # gap where the button used to be. This also covers the initial call
        # from setup_ui before the base layout is applied.
        self._layout_manual(self._strip_w)
        if self.isVisible():
            self._recenter()

    def _visible_toolbar(self):
        """Toolbar buttons that should be laid out, in order.

        Uses the explicitly tracked hidden set (not widget visibility), so it
        returns the correct cluster even while the capsule itself is hidden
        during startup. Settings and Close are never hidden."""
        visible = [self.btn_settings, self.btn_close]
        for key in reversed(self._tool_order):
            if key not in self._hidden_tools:
                visible.insert(0, self._tool_buttons[key])
        return visible

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
        self._layout_manual(self._strip_w)

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
        self.opacity_anim.finished.connect(self._on_fade_finished)

        # 状态条宽度动画：像素值驱动，栏宽随内容平滑增减。
        self._strip_w_anim = QPropertyAnimation(self, b"stripWidth")
        self._strip_w_anim.setDuration(300)
        self._strip_w_anim.setEasingCurve(QEasingCurve.OutCubic)

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

        # mini 态：miniT 0↔1 驱动窗口宽度在完整 / mini 之间插值，内容交叉
        # 淡入淡出（始终左右方向，不跟随 capsule_anim 的上下飞入）。
        self._mini_anim = QPropertyAnimation(self, b"miniT")
        self._mini_anim.setDuration(300)
        self._mini_anim.setEasingCurve(QEasingCurve.OutCubic)

        # 完成态「自动展开一点点」：只加宽，不改变内容配比。
        self._grow = QVariantAnimation(self)
        self._grow.setDuration(200)
        self._grow.setEasingCurve(QEasingCurve.OutCubic)
        self._grow.valueChanged.connect(self._on_grow)

    # ----- layout -----

    def _layout_manual(self, strip_w):
        """手工排布状态条与工具组。

        状态条占 MARGIN 起的 strip_w 宽（内容按最终宽度摆放，超出部分被
        自身宽度裁掉，形成由左向右的揭示），工具组紧随其后；strip_w == 0
        时退化为纯工具条。只有未隐藏的工具参与宽度与定位。"""
        visible = self._visible_toolbar()
        tw = len(visible) * self.BTN + (len(visible) - 1) * self.SPACING
        strip_w = max(0, int(round(strip_w)))
        self.status.setGeometry(
            self.MARGIN, self.TOP, strip_w, StatusStrip.HEIGHT)
        # mini 态下状态条由 _set_mini_isolated 整体隐藏，这里不能再把它拉回来
        self.status.setVisible(strip_w > 0 and not self._mini_isolated)
        if strip_w > 0:
            cw = self.MARGIN + strip_w + self.SPACING + tw + self.MARGIN
            x = self.MARGIN + strip_w + self.SPACING
        else:
            cw = self.MARGIN + tw + self.MARGIN
            x = self.MARGIN
        # 记录完整宽度；mini 态期间宽度由 _mini_width_now() 插值收窄。
        self._full_w = cw
        self.setFixedWidth(self._mini_width_now())
        for b in visible:
            b.setGeometry(x, self.TOP, self.BTN, self.BTN)
            x += self.BTN + self.SPACING

    # ----- mini 小胶囊（录制中收起态） -----

    def _mini_width_now(self):
        """当前帧窗口宽度：完整宽度 ↔ mini 宽度（含完成态加宽）插值。"""
        if self._mini_t <= 0.0001:
            return self._full_w
        target = self._mini_w + self._mini_grow_extra * self._mini_extra
        return max(1, int(round(self._full_w
                                + (target - self._full_w) * self._mini_t)))

    def _get_mini_t(self):
        return self._mini_t

    def _set_mini_t(self, p):
        self._mini_t = max(0.0, min(1.0, float(p)))
        self._apply_mini_frame()

    miniT = Property(float, _get_mini_t, _set_mini_t)

    def _apply_mini_frame(self):
        """把 miniT 落成一帧：窗口宽度、内容交叉淡出 / 淡入、mini 层定位。"""
        t = self._mini_t
        self.setFixedWidth(self._mini_width_now())
        # mini 层按收窄后的窗口宽度居中（宽度先落定，位置才不会慢一帧）；
        # 竖直方向始终与背景胶囊的中线对齐 —— 背景是从下边往上收，所以这里
        # 也随 miniT 由居中位置滑到顶边（t=1 时 y=0）。
        w = self._mini_w
        self._mini_pill.setGeometry(
            int((self.width() - w) / 2),
            int(round((self.height() - RecordMiniPill.H) / 2.0 * (1.0 - t))),
            w, RecordMiniPill.H)
        if t <= 0.0001:
            self._mini_pill.hide()
            self._set_mini_isolated(False)
            self._set_buttons_reveal(1.0)
            if self.isVisible():
                self._recenter()
            return
        # mini 内容延后出现：窗口收到接近 mini 宽度时再渐入，避免中途两套
        # 内容同时可见；工具组 / 状态条随 miniT 线性淡出。
        mini_r = max(0.0, (t - 0.35) / 0.65)
        mini_r = mini_r * mini_r * (3 - 2 * mini_r)
        for b in self._toolbar:
            b.set_reveal(1.0 - t)
        self.status.set_reveal(1.0 - t)
        # 淡出完成后整体隐藏：状态条里有不参与绘制级 reveal 的子控件（音乐段
        # 的走马灯文案），只靠 reveal 淡到 0 仍会漏出来压在 mini 胶囊上。
        self._set_mini_isolated(t >= 0.999)
        self._mini_pill.set_reveal(mini_r)
        self._mini_pill.setVisible(mini_r > 0.0)
        self._mini_pill.raise_()
        if self.isVisible():
            self._recenter()

    def _set_mini_isolated(self, isolated):
        """mini 态隔离：把工具组与状态条整体隐藏 / 恢复。

        状态条内并非所有子控件都参与绘制级 reveal（音乐段的走马灯文案是
        普通 QWidget），淡出到 0 之后它仍会绘制，并正好落在收窄后的 mini
        胶囊上（看起来像个跑到错位置的图标）；完全收起后直接隐藏整条状态
        条，是唯一可靠的隔离方式。"""
        isolated = bool(isolated)
        if isolated == self._mini_isolated:
            return
        self._mini_isolated = isolated
        self._apply_mini_visibility()

    def _apply_mini_visibility(self):
        """按 _mini_isolated 落地工具组 / 状态条的显隐（恢复时沿用既有规则）。"""
        if self._mini_isolated:
            self.status.hide()
            for b in self._toolbar:
                b.hide()
            return
        self.status.setVisible(self._strip_w > 0)
        for key, b in self._tool_buttons.items():
            b.setVisible(key not in self._hidden_tools)
        self.btn_settings.show()
        self.btn_close.show()

    def _on_grow(self, value):
        self._mini_extra = float(value)
        if self._mini_t > 0.0001:
            self._apply_mini_frame()

    def _animate_mini(self, target):
        self._mini_anim.stop()
        self._mini_anim.setStartValue(self._mini_t)
        self._mini_anim.setEndValue(float(target))
        self._mini_anim.start()

    def _can_mini(self):
        """录制中收起 → 进入 mini 态（后续可加设置项在此处做开关）。"""
        return self.recorder.is_recording() and not self._mini_on

    def is_mini(self):
        """是否处于录制中的 mini 小胶囊态（它本身就是「已收起」）。"""
        return self._mini_on

    def _collapse_to_mini(self):
        """收起成 mini 小胶囊：真实收窄窗口（命中范围与视觉一致）。"""
        self._mini_on = True
        self._mini_done = False
        self._mini_extra = 0.0
        self._grow.stop()
        self._mini_pill.set_done(False)
        self._mini_w = self._mini_pill.sizeHint().width()
        # 收起同样是复位点：清掉悬浮高亮，避免留在下一次展开。
        self._reset_buttons_hover()
        self._animate_mini(1.0)

    def _expand_from_mini(self):
        """mini → 完整胶囊：左右展开，内容交叉淡入。"""
        self._mini_on = False
        self._mini_done = False
        self._fade_out = False
        self._done_timer.stop()
        self._grow.stop()
        self._mini_extra = 0.0
        # 完成态淡出中途被呼出：把透明度一并拉回，而不是先跳回不透明
        if self.windowOpacity() < 1.0:
            self.opacity_anim.stop()
            self.opacity_anim.setStartValue(self.windowOpacity())
            self.opacity_anim.setEndValue(1.0)
            self.opacity_anim.start()
        self._animate_mini(0.0)

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

    @staticmethod
    def _overlap_reveal(left, width, pill_l, pill_r):
        """元素落在展开胶囊内的比例（smoothstep 淡入）。"""
        overlap = min(left + width, pill_r) - max(left, pill_l)
        overlap = max(0.0, min(1.0, overlap / float(max(1, width))))
        return overlap * overlap * (3 - 2 * overlap)

    def _apply_dynamic_mask(self, p):
        """Clip the parked window to a centre-anchored pill that grows with p.

        The glass plate is masked into an expanding rounded pill, while each
        tool button and the status strip fade in by the fraction of itself
        inside the pill, so content glides in smoothly from the centre out to
        both sides instead of popping at the mask edge (Dynamic-island style)."""
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
        pill_l = cx - reveal / 2.0
        pill_r = cx + reveal / 2.0
        for b in self._toolbar:
            b.set_reveal(self._overlap_reveal(b.x(), self.BTN, pill_l, pill_r))
        if not self.status.isHidden():
            self.status.set_reveal(self._overlap_reveal(
                self.status.x(), self.status.width(), pill_l, pill_r))

    def _set_buttons_reveal(self, o):
        for b in self._toolbar:
            b.set_reveal(float(o))
        self.status.set_reveal(float(o))

    def _reset_buttons_hover(self):
        """Force every tool button back to its idle state. Used when the bar
        is collapsed so no hover highlight survives a hide/show cycle."""
        for b in self._toolbar:
            b.clear_hover()
            b.set_reveal(1.0)
        self.status.clear_hover()
        self.status.set_reveal(1.0)

    def paintEvent(self, event):
        # Shared pill look (gradient body + family hairline) so the capsule
        # and the annotation sub-bar read as one design family.
        painter = QPainter(self)
        rect = QRectF(self.rect())
        radius = 28.0
        # mini 态：背景主要由下边往上收（收起基线锚在顶部，min 胶囊的顶边
        # 与大胶囊顶边重合），圆角同步收到半高，整条明显变矮变小。内容层
        # 按同一中线跟随，见 _apply_mini_frame。
        t = self._mini_t
        if t > 0.0001:
            rect = rect.adjusted(
                0.0, 0.0, 0.0, -(self.BASE_HEIGHT - self.MINI_PILL_H) * t)
            radius += (self.MINI_PILL_H / 2.0 - radius) * t
        paint_pill(painter, rect, radius)

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
            # 标记本次收起来源：mini 态（录制指示器）只对显式收起生效，
            # 外部点击不收它。emit 是直连同步调用，try/finally 保证标记
            # 在 hide_capsule() 判定期间有效。
            self._outside_click = True
            try:
                self.hide_family_requested.emit()
            finally:
                self._outside_click = False

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
        # 正在录制则先收尾成片，否则文件不完整。
        if self.recorder.is_recording():
            self.recorder.stop()
        self.music.stop()
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
        self._strip_w_anim.stop()
        # mini 态复位：先归零再重排，_layout_manual 才会落回完整宽度。
        self._mini_anim.stop()
        self._grow.stop()
        self._done_timer.stop()
        self._mini_on = False
        self._mini_done = False
        self._fade_out = False
        self._mini_t = 0.0
        self._mini_extra = 0.0
        self._mini_pill.hide()
        # mini 隔离复位：把被整体隐藏的工具组 / 状态条放回来，否则下次呼出
        # 会缺一整条状态条（工具按钮由 _layout_manual 之外的这里负责恢复）。
        if self._mini_isolated:
            self._mini_isolated = False
            self._apply_mini_visibility()
        # 落回目标宽度：下一次呼出直接就是正确布局。
        self._strip_w = float(self._full_strip_w)
        self._layout_manual(self._strip_w)
        self._dynamic_expand = 0.0
        self.clearMask()
        self.setWindowOpacity(1.0)
        self._set_buttons_reveal(1.0)
        # Hiding never delivers a leaveEvent, so a hovered button keeps its
        # lit `_t`; clear it here so the highlight can't linger on re-show.
        for b in self._toolbar:
            b.clear_hover()
        self.status.clear_hover()
        # 完成提示是一次性的：胶囊栏收起后不能把它留到下次呼出。
        self.status.dismiss_notice()
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
        # Already fully shown and not hiding → nothing to do, except while
        # recording the bar may be parked in the mini pill: expand it back.
        if self.isVisible() and not self._pending_hide:
            if self._mini_on:
                self._expand_from_mini()
            return

        first_show = not self.isVisible()
        self._animating = True
        self._pending_hide = False
        self._fade_out = False
        screen = self._get_screen_geo()
        target_x = self._resting_x(screen)
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
        already hidden (no-op) or while showing (reverses).

        录制中收起不隐藏整窗，而是收成 mini 小胶囊（否则「录制中」无处
        显示）；mini 态本身是常驻录制指示器，外部点击不收它，只有 ESC /
        快捷键 / 关闭按钮这类显式收起才真正隐藏（录制继续在后台跑）。"""
        if not self.isVisible():
            return

        if self._mini_on:
            if self._outside_click:
                return
        elif self._can_mini():
            self._collapse_to_mini()
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
        # mini 态本身就是「已收起」态：再切换一次应当是展开回完整胶囊，
        # 而不是把它收掉（那会让「录制中」的指示彻底消失）。
        if self._mini_on:
            self.show_capsule()
            return
        # User-explicit toggle: bypass the focus-loss debounce via
        # force_family_hide so a quick second press isn't swallowed by the
        # 500ms show-debounce. The animation itself is reversible, so we
        # no longer bail out when _animating is True.
        if self.isVisible() and not self._pending_hide:
            self.force_family_hide()
        else:
            self.show_capsule()