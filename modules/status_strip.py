"""
胶囊状态条
录制 / 音乐 / 倒计时三段进行中状态合并显示，互斥展开
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import math
import time

from PySide6.QtCore import (
    Qt, QRectF, QPointF, QSize, QTimer, QVariantAnimation, QEasingCurve, Signal
)
from PySide6.QtGui import (
    QPainter, QPainterPath, QColor, QFont, QFontMetricsF, QImage, QPalette,
    QPen
)
from PySide6.QtWidgets import QWidget, QApplication

from modules.i18n import I18n
from modules.icons import (
    ICON_MUSIC, ICON_PREV, ICON_NEXT, ICON_PAUSE, ICON_PLAY, ICON_ROTATE_CCW,
    ICON_CLOSE, ICON_TIMER, ICON_STOP, ICON_CHECK
)
from modules.music import MarqueeLabel
from modules.timer import format_hms, phase_label
from modules.widgets import GlassIconButton, make_pixmap, screen_dpr

RED = QColor(224, 49, 49)

_glyph_cache = {}


def _glyph(svg, color_name, size):
    """光栅化并缓存 SVG 字形（状态条每帧重绘，不能每次重建）。"""
    key = (svg, color_name, size)
    pm = _glyph_cache.get(key)
    if pm is None:
        pm = make_pixmap(svg, color_name, size)
        _glyph_cache[key] = pm
    return pm


class _Segment(QWidget):
    """状态段基类：收起 26px / 展开统一宽度，点击切换展开态。

    收起态字形统一锚在左侧 13px 处，而不是随控件宽度居中：展开↔收起过渡
    时控件左边缘不动、只有右边缘在移动，左锚可以保证内容切换的位置几乎不
    可见（居中会让字形在收缩过程中一路横移）。"""

    clicked = Signal()
    H = 44
    COLLAPSED = 26
    # 展开段内容的左右内边距。左右必须一致：段被两条分隔线夹着时，两侧内边距
    # 不等就会整段偏向一边。
    EDGE = 12
    # 尾部按钮盒（GlassIconButton 22px、13px 图标居中）里，字形距按钮盒边缘
    # 还有约 6px，所以按钮盒外侧只留 EDGE - 6，字形的视觉内边距才等于 EDGE。
    BTN_PAD = EDGE - 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.H)
        self.setCursor(Qt.PointingHandCursor)
        self._collapsed = False
        self._laid = False
        self._reveal = 1.0

    # ----- 形态 -----

    def set_collapsed(self, collapsed):
        """切换展开 / 收起；首次调用必定执行一次子控件布局。"""
        collapsed = bool(collapsed)
        if collapsed == self._collapsed and self._laid:
            return
        self._collapsed = collapsed
        self._laid = True
        self._form_changed()
        self.update()

    def _form_changed(self):
        """展开 / 收起切换时调整子控件。"""

    def relayout(self):
        """按当前宽度重排子控件（展开↔收起过渡的每一帧调用）。"""
        self._form_changed()

    def is_collapsed(self):
        return self._collapsed

    def set_reveal(self, o):
        o = max(0.0, min(1.0, float(o)))
        if o == self._reveal:
            return
        self._reveal = o
        for b in self.findChildren(GlassIconButton):
            b.set_reveal(o)
        self.update()

    def clear_hover(self):
        for b in self.findChildren(GlassIconButton):
            b.clear_hover()

    def content_insets(self, w=None):
        """可见内容相对控件左右边缘的内缩 (left, right)，供段间距排版使用。

        收起态字形锚在 26px 盒内、可点区域就是整盒，故内缩 0；展开段带 EDGE
        内边距。内缩随宽度插值（收起 0 / 展开 EDGE），互换过渡中相邻段的内容
        间距才恒为 GAP_C、分隔线不跳变。w 省略时按当前几何宽度算，排版时按
        目标宽度预取。子类覆盖。"""
        return (0.0, 0.0)

    def _expand_ratio(self, expanded_w, w=None):
        """宽度 w（省略时取当前宽度）落在「收起 → 展开」区间里的进度。"""
        w = self.width() if w is None else w
        span = float(max(1, expanded_w - self.COLLAPSED))
        return max(0.0, min(1.0, (w - self.COLLAPSED) / span))

    def _color(self):
        return QApplication.palette().color(QPalette.WindowText)

    # ----- 事件 / 绘制 -----

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._reveal)
        if self._collapsed:
            self._paint_collapsed(p)
        else:
            self._paint_expanded(p)
        p.end()

    def _paint_collapsed(self, p):
        raise NotImplementedError

    def _paint_expanded(self, p):
        raise NotImplementedError


class RecordSegment(_Segment):
    """录制段：红点 + 已录时长，右侧停止按钮。"""

    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t0 = None
        self._elapsed = 0
        self._font = QFont("Consolas")
        self._font.setPointSize(13)
        self._label_font = QFont()
        self._label_font.setPixelSize(12)
        self.setToolTip(I18n.tr("record"))
        self.btn_stop = GlassIconButton(
            ICON_STOP, I18n.tr("record_stop_tip"), size=22, icon_size=13,
            hover_color="#e03131", hover_bg_color=RED, colorize_icon=False,
            parent=self)
        self.btn_stop.clicked.connect(self.stop_requested)
        self.btn_stop.hide()
        # 时长由单调时钟推出，避免累加误差
        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._on_tick)

    def is_active(self):
        return self._t0 is not None

    def start(self):
        self._t0 = time.monotonic()
        self._elapsed = 0
        self._tick.start()
        self.update()

    def stop(self):
        self._t0 = None
        self._elapsed = 0
        self._tick.stop()
        self.update()

    def _on_tick(self):
        self._elapsed = int(time.monotonic() - self._t0)
        self.update()

    def _form_changed(self):
        self.btn_stop.setVisible(not self._collapsed)
        self.btn_stop.setGeometry(
            self.width() - self.BTN_PAD - 22, (self.H - 22) // 2, 22, 22)

    def content_insets(self, w=None):
        t = self._expand_ratio(StatusStrip.FULL_W, w)
        return (self.EDGE * t, self.EDGE * t)

    def _paint_collapsed(self, p):
        cx, cy = self.COLLAPSED / 2.0, self.H / 2.0
        ring = QColor(self._color())
        ring.setAlpha(130)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ring, 2))
        p.drawEllipse(QPointF(cx, cy), 11, 11)
        p.setPen(Qt.NoPen)
        p.setBrush(RED)
        p.drawEllipse(QPointF(cx, cy), 4, 4)

    def _paint_expanded(self, p):
        """红点 + 「录制中」在左，大号时长右对齐到停止按钮之前。

        时长右对齐是为了把整段 200px 填满 —— 左对齐时文字右侧会空出一大
        块，整段看着很稀疏。"""
        p.setPen(Qt.NoPen)
        p.setBrush(RED)
        p.drawEllipse(QPointF(17, self.H / 2.0), 4.5, 4.5)
        p.setPen(self._color())
        p.setFont(self._label_font)
        p.drawText(QRectF(28, 0, 46, self.H),
                   Qt.AlignVCenter | Qt.AlignLeft, I18n.tr("recording"))
        # 停止按钮占右侧 22px + BTN_PAD 外边距，时长右边界停在它左侧 10px 处
        right = max(28.0, self.width() - (self.BTN_PAD + 32.0))
        p.setFont(self._font)
        p.drawText(QRectF(28, 0, right - 28, self.H),
                   Qt.AlignVCenter | Qt.AlignRight, format_hms(self._elapsed))


class RecordMiniPill(QWidget):
    """录制中的 mini 小胶囊内容层：红点 + 「录制中」，右侧停止 / 完成按钮。

    底（胶囊外形）由 CapsuleBar 的 paint_pill 绘制，本控件只负责红点、文案
    与按钮，并按 _reveal 做绘制级淡入淡出（不继承子控件，需手动透传）。"""

    stop_requested = Signal()
    expand_requested = Signal()

    H = 38
    BTN = 20
    # 左右留白要比上下留白（固定为 (H - BTN) / 2）更大：横向太紧会显得局促
    # 猥琐，多给一点呼吸空间整条胶囊才舒展。
    PAD = 14
    DOT = 6
    GAP = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.H)
        self.setCursor(Qt.PointingHandCursor)
        self._done = False
        self._reveal = 0.0
        self._text = I18n.tr("recording")
        self._font = QFont()
        self._font.setPixelSize(11)
        self.btn_stop = GlassIconButton(
            ICON_STOP, I18n.tr("record_stop_tip"), size=self.BTN, icon_size=12,
            hover_color="#e03131", hover_bg_color=RED, colorize_icon=False,
            parent=self)
        self.btn_stop.clicked.connect(self.stop_requested)
        self._form_changed()

    # ----- 内容 -----

    def sizeHint(self):
        """宽度由文案决定，中英文自适应。"""
        fm = QFontMetricsF(self._font)
        tw = fm.horizontalAdvance(self._text)
        return QSize(int(self.PAD + self.DOT + self.GAP + tw + self.GAP
                         + self.BTN + self.PAD), self.H)

    def set_done(self, done):
        """切到「录制完成」：文案替换，停止按钮换成勾选并禁用。"""
        self._done = bool(done)
        self._text = I18n.tr("record_done" if done else "recording")
        self.btn_stop.set_svg(ICON_CHECK if done else ICON_STOP)
        self.btn_stop.setEnabled(not done)
        self.btn_stop.setToolTip(
            I18n.tr("record_done" if done else "record_stop_tip"))
        self._form_changed()
        self.updateGeometry()
        self.update()

    def is_done(self):
        return self._done

    def set_reveal(self, o):
        o = max(0.0, min(1.0, float(o)))
        if o == self._reveal:
            return
        self._reveal = o
        self.btn_stop.set_reveal(o)
        self.update()

    # ----- 事件 / 绘制 -----

    def _form_changed(self):
        self.btn_stop.setGeometry(
            self.width() - self.PAD - self.BTN, (self.H - self.BTN) // 2,
            self.BTN, self.BTN)

    def resizeEvent(self, event):
        self._form_changed()
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        # 按钮是子控件会自己吃掉点击，这里只处理本体点击 → 展开胶囊栏
        if event.button() == Qt.LeftButton:
            self.expand_requested.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._reveal)
        cy = self.H / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(RED)
        p.drawEllipse(QPointF(self.PAD + self.DOT / 2.0, cy),
                      self.DOT / 2.0, self.DOT / 2.0)
        p.setFont(self._font)
        p.setPen(QApplication.palette().color(QPalette.WindowText))
        x = self.PAD + self.DOT + self.GAP
        w = max(0.0, self.width() - x - self.GAP - self.BTN - self.PAD)
        p.drawText(QRectF(x, 0, w, self.H),
                   Qt.AlignVCenter | Qt.AlignLeft, self._text)
        p.end()


class MusicSegment(_Segment):
    """音乐段：圆角封面 + 曲目 / 歌手，右侧播放控制。"""

    ART = 28
    BTN = 22
    BTN_GAP = 4
    MARGIN = _Segment.EDGE          # 封面左侧内边距，与段右端按钮的字形内边距对齐
    TITLE_X = MARGIN + ART + 6      # 文案起点：封面右侧再留 6px
    TITLE_H = 16
    TITLE_Y = 7        # 有歌手时标题占上半行，歌手占下半行
    TITLE_Y_ALONE = (_Segment.H - TITLE_H) // 2   # 没有歌手时标题垂直居中

    # 「音柱」播放徽标：深色圆底 + 三根高低跳动的白柱，贴着封面右下角
    EQ_MS = 40         # 刷新间隔（约 25fps，这么小的徽标够用）
    EQ_R = 5           # 圆底半径，徽标就按它贴在封面下缘
    EQ_BARS = 3
    EQ_W = 1.4         # 柱宽
    EQ_GAP = 1.0       # 柱间距

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self._state = None
        self._art = None
        self._art_key = None
        self._has_artist = False
        self._meta_font = QFont()
        self._meta_font.setPixelSize(11)
        self.setToolTip(I18n.tr("music_capsule"))

        self._marquee = MarqueeLabel(self)
        self._marquee.hide()

        # 音柱徽标的刷新计时器：只在真的在播时跑，柱高由墙钟相位算出，不做
        # 几何动画 —— 段的排布 / 展开收起因此完全不受影响。
        self._eq_tick = QTimer(self)
        self._eq_tick.setInterval(self.EQ_MS)
        self._eq_tick.timeout.connect(self.update)

        self.btn_prev = self._button(ICON_PREV, "music_prev")
        self.btn_toggle = self._button(ICON_PAUSE, "music_pause")
        self.btn_next = self._button(ICON_NEXT, "music_next")
        for b in (self.btn_prev, self.btn_toggle, self.btn_next):
            b.hide()
        self.btn_prev.clicked.connect(manager.previous_track)
        self.btn_toggle.clicked.connect(manager.play_pause)
        self.btn_next.clicked.connect(manager.next_track)

        manager.state_changed.connect(self._on_state)

    def _button(self, svg, tip_key):
        return GlassIconButton(svg, I18n.tr(tip_key), size=self.BTN, icon_size=13,
                               colorize_icon=False, parent=self)

    # ----- 状态 -----

    def has_track(self):
        return self._state is not None

    def _is_playing(self):
        return self._state is not None and bool(self._state.get("playing"))

    def _sync_eq(self):
        """在播才跑音柱刷新计时器；暂停 / 没曲目就停掉，不空转。"""
        if self._is_playing():
            if not self._eq_tick.isActive():
                self._eq_tick.start()
        else:
            self._eq_tick.stop()

    def clear(self):
        self._state = None
        self._art = None
        self._art_key = None
        self._has_artist = False
        self._eq_tick.stop()
        self._marquee.setText("")
        self.update()

    def _artist(self):
        """歌手名（去空白）；很多音源（本地文件、播客）没有这一项。"""
        if self._state is None:
            return ""
        return (self._state.get("artist") or "").strip()

    def _on_state(self, state):
        self._state = state
        if state is None:
            self.clear()
            return
        self._marquee.setText(state.get("title", ""))
        if state.get("art_key") != self._art_key:
            self._art_key = state.get("art_key")
            self._set_art(state.get("art_bytes") or b"")
        # 有无歌手决定标题占一行还是居中，切换曲目时要重排
        has_artist = bool(self._artist())
        if has_artist != self._has_artist:
            self._has_artist = has_artist
            self._form_changed()
        playing = bool(state.get("playing"))
        self.btn_toggle.set_svg(ICON_PAUSE if playing else ICON_PLAY)
        self.btn_toggle.setToolTip(
            I18n.tr("music_pause" if playing else "music_play"))
        self._sync_eq()
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
            self._art = scaled.copy(x, y, size, size)
        self.update()

    # ----- 形态 -----

    def _form_changed(self):
        expanded = not self._collapsed
        block = 3 * self.BTN + 2 * self.BTN_GAP
        bx = self.width() - self.BTN_PAD - block
        self._marquee.setVisible(expanded)
        # 没有歌手信息时标题垂直居中，把下半行也占掉；不然标题贴在上半行、
        # 下面空出一条，整段看着像没对齐。
        ty = self.TITLE_Y if self._has_artist else self.TITLE_Y_ALONE
        self._marquee.setGeometry(self.TITLE_X, ty,
                                  max(0, bx - 6 - self.TITLE_X), self.TITLE_H)
        x = bx
        for b in (self.btn_prev, self.btn_toggle, self.btn_next):
            b.setVisible(expanded)
            b.setGeometry(x, (self.H - self.BTN) // 2, self.BTN, self.BTN)
            x += self.BTN + self.BTN_GAP

    def content_insets(self, w=None):
        t = self._expand_ratio(StatusStrip.FULL_W, w)
        return (self.EDGE * t, self.EDGE * t)

    def _paint_cover(self, p, rect, radius):
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        if self._art is not None:
            p.save()
            p.setClipPath(path)
            p.drawImage(rect, self._art)
            p.restore()
            return
        c = self._color()
        plate = QColor(c)
        plate.setAlpha(28)
        p.fillPath(path, plate)
        pm = _glyph(ICON_MUSIC, c.name(), 14)
        p.drawPixmap(QPointF(rect.center().x() - 7, rect.center().y() - 7), pm)

    def _paint_collapsed(self, p):
        size = self.COLLAPSED
        rect = QRectF(0, (self.H - size) / 2.0, size, size)
        self._paint_cover(p, rect, 8)
        if self._is_playing():
            self._paint_eq_badge(p, rect.right() - 8, rect.bottom() - self.EQ_R)

    def _paint_eq_badge(self, p, cx, cy):
        """播放中的「音柱」小徽标：深色圆底 + 三根高低跳动的白柱。

        cy 给圆底中心，调用方按 EQ_R 把它贴到封面下缘（不是原来小三角那样浮在
        中间偏下）。底色沿用原来播放三角形的半透明黑：徽标压在封面上，封面什么
        颜色都有，深底配白柱才在任何封面上都读得出来。柱高只按墙钟相位算，不碰
        几何，所以整段的排布与展开收起完全不受影响。"""
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawEllipse(QPointF(cx, cy), self.EQ_R, self.EQ_R)
        p.setBrush(QColor(255, 255, 255))
        base = cy + 3.0                     # 三根柱子共用的底线
        left = cx - (self.EQ_BARS * self.EQ_W
                     + (self.EQ_BARS - 1) * self.EQ_GAP) / 2.0
        t = time.monotonic()
        for i in range(self.EQ_BARS):
            # 周期 / 相位各不相同，跳起来才不像三根同步闪烁
            h = 2.0 + 4.0 * (0.5 + 0.5 * math.sin(t * (5.2 + 1.7 * i) + 2.1 * i))
            x = left + i * (self.EQ_W + self.EQ_GAP)
            p.drawRoundedRect(QRectF(x, base - h, self.EQ_W, h),
                              self.EQ_W / 2.0, self.EQ_W / 2.0)

    def _paint_expanded(self, p):
        cover = QRectF(self.MARGIN, (self.H - self.ART) / 2.0, self.ART, self.ART)
        self._paint_cover(p, cover, 9)
        # 与收起态同一口径：徽标贴着封面下缘、右缘内缩 8px，两种形态位置一致
        if self._is_playing():
            self._paint_eq_badge(p, cover.right() - 8,
                                 cover.bottom() - self.EQ_R)
        artist = self._artist()
        if not artist:
            return          # 无歌手：标题已垂直居中，下半行不再画东西
        block = 3 * self.BTN + 2 * self.BTN_GAP
        text_w = max(0.0, self.width() - self.BTN_PAD - block - 6 - self.TITLE_X)
        dim = QColor(self._color())
        dim.setAlpha(150)
        p.setPen(dim)
        p.setFont(self._meta_font)
        fm = QFontMetricsF(self._meta_font)
        p.drawText(QRectF(self.TITLE_X, 25, text_w, 14),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(artist, Qt.ElideRight, text_w))


class TimerSegment(_Segment):
    """倒计时段：剩余时间，右侧重置 / 停止；收起时画剩余百分比圆环。"""

    reset_requested = Signal()
    close_requested = Signal()

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self._phase = None
        self._remaining = 0
        self._total = 0
        self._paused = False
        self._frac = 1.0        # 圆环当前绘制进度（按本地时钟插值）
        self._ref_t = 0.0       # 插值锚点：上次同步权威剩余值的单调时刻
        self._time_font = QFont("Consolas")
        self._time_font.setPointSize(11)
        self._phase_font = QFont()
        self._phase_font.setPixelSize(12)
        self.setToolTip(I18n.tr("timer"))

        self.btn_reset = GlassIconButton(
            ICON_ROTATE_CCW, I18n.tr("timer_reset_tip"), size=22, icon_size=13,
            colorize_icon=False, parent=self)
        self.btn_close = GlassIconButton(
            ICON_CLOSE, I18n.tr("timer_close_tip"), size=22, icon_size=13,
            hover_color="#e03131", hover_bg_color=RED, colorize_icon=False,
            parent=self)
        self.btn_reset.clicked.connect(self.reset_requested)
        self.btn_close.clicked.connect(self.close_requested)
        self.btn_reset.hide()
        self.btn_close.hide()

        # 圆环进度按本地时钟插值，而不是让动画去追每秒一次的整数 tick：
        # tick 只在"显示秒数变化"时发出（约 1s 一次），若以它为动画起点，
        # 弧会整整落后真实剩余时间 1 秒（开头停滞 1s、结尾 1% 走不完）。
        # 这里每次同步都记录权威剩余值与单调时刻，两次同步之间按真实时间
        # 匀速推进；下次同步重新取锚点，因此不会累积漂移。
        self._clock = QTimer(self)
        self._clock.setInterval(100)
        self._clock.timeout.connect(self._on_clock)

    def is_active(self):
        # 直接问管理器，不读本地缓存 _phase：倒计时结束时管理器先清 phase 再发
        # finished，提示就是在 finished 里排进布局的 —— 若这里读缓存会晚一拍
        # （提示已按"计时段还在"排好伸缩过渡，紧接着刷新又把计时段撤下，等于
        # 把刚起步的过渡硬切掉）。
        return self.mgr.phase() is not None

    def refresh(self):
        """从计时管理器同步一次权威状态（每个 tick / 状态变化调用）。

        管理器给的是整数秒，这里只把它当作插值锚点：记下值和当时的单调
        时刻，之后的亚秒进度由 _on_clock 按真实时间推出来。"""
        phase = self.mgr.phase()
        self._phase = phase
        self._remaining = self.mgr.remaining()
        self._paused = self.mgr.is_paused()
        self._total = self.mgr.total_seconds() if phase else 0
        self._ref_t = time.monotonic()
        if phase is None:
            self._clock.stop()
        elif not self._clock.isActive():
            self._clock.start()
        self._on_clock()

    def _on_clock(self):
        """按本地时钟算出当前圆环进度（同步后立即调用一次，此后每 100ms）。"""
        total = self._total
        if not total:
            self._frac = 1.0
        elif self._paused:
            # 暂停时进度冻结在锚点值上
            self._frac = max(0.0, min(1.0, self._remaining / float(total)))
        else:
            elapsed = time.monotonic() - self._ref_t
            self._frac = max(0.0, min(1.0,
                                       (self._remaining - elapsed) / float(total)))
        self.update()

    def _form_changed(self):
        expanded = not self._collapsed
        y = (self.H - 22) // 2
        self.btn_close.setVisible(expanded)
        self.btn_reset.setVisible(expanded)
        self.btn_close.setGeometry(self.width() - self.BTN_PAD - 22, y, 22, 22)
        self.btn_reset.setGeometry(
            self.width() - self.BTN_PAD - 22 - 26, y, 22, 22)

    def content_insets(self, w=None):
        t = self._expand_ratio(StatusStrip.FULL_W, w)
        return (self.EDGE * t, self.EDGE * t)

    def _paint_collapsed(self, p):
        cx, cy = self.COLLAPSED / 2.0, self.H / 2.0
        r = 11.0
        c = self._color()
        track = QColor(c)
        track.setAlpha(55)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(track, 2))
        p.drawEllipse(QPointF(cx, cy), r, r)
        # 进度弧从 12 点顺时针缩短，表示剩余百分比（按插值进度平滑走）
        frac = max(0.0, min(1.0, self._frac))
        arc = QColor(c)
        if self._paused:
            arc.setAlpha(110)
        p.setPen(QPen(arc, 2, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2),
                  90 * 16, -int(round(360 * 16 * frac)))
        glyph = QColor(c)
        if self._paused:
            glyph.setAlpha(120)
        pm = _glyph(ICON_TIMER, glyph.name(), 12)
        p.drawPixmap(QPointF(cx - 6, cy - 6), pm)

    def _paint_expanded(self, p):
        c = QColor(self._color())
        if self._paused:
            c.setAlpha(150)
        text = phase_label(self._phase, self._paused)
        p.setFont(self._phase_font)
        p.setPen(c)
        pw = QFontMetricsF(self._phase_font).horizontalAdvance(text)
        p.drawText(QRectF(12, 0, pw + 4, self.H),
                   Qt.AlignVCenter | Qt.AlignLeft, text)
        p.setFont(self._time_font)
        p.drawText(QRectF(12 + pw + 8, 0,
                          self.width() - 12 - pw - 8 - 62, self.H),
                   Qt.AlignVCenter | Qt.AlignLeft, format_hms(self._remaining))


class NoticeSegment(_Segment):
    """完成提示段：把「录制已保存 / 倒计时结束」这类一次性反馈就地显示。

    与其它段不同，它没有「进行中」语义 —— 消息由 StatusStrip.show_notice()
    塞进来、到点自动撤下，段本身不持有计时逻辑。宽度按文案自适应，且永远按
    文案宽度占位（不占展开位、也不参与互斥互换）：它出现时是额外多出来的一段，
    把胶囊栏伸出去，撤下时再缩回来。"""

    ICON = 16
    PAD = 14
    GAP = 9
    MIN_W = _Segment.COLLAPSED + 20
    MAX_W = 320       # 上限：英文长句也不至于把胶囊栏撑得过长

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._icon_svg = ICON_TIMER
        self._font = QFont()
        self._font.setPixelSize(13)

    def set_notice(self, text, icon_svg=ICON_TIMER):
        self._text = text
        self._icon_svg = icon_svg
        self.update()

    def has_notice(self):
        return bool(self._text)

    def expanded_width(self):
        """展开宽度：文案长度 + 两侧留白，并夹在上下限之间。"""
        tw = QFontMetricsF(self._font).horizontalAdvance(self._text)
        want = self.PAD * 2 + self.ICON + self.GAP + tw
        return int(max(self.MIN_W, min(self.MAX_W, want)))

    def _paint_icon(self, p, x, y):
        pm = _glyph(self._icon_svg, self._color().name(), self.ICON)
        p.drawPixmap(QPointF(x, y), pm)

    def content_insets(self, w=None):
        t = self._expand_ratio(self.expanded_width(), w)
        return (self.PAD * t, self.PAD * t)

    def _paint_collapsed(self, p):
        # 只在伸缩过渡的首尾帧出现（宽度尚未过半）：留一个图标即可
        self._paint_icon(p, (self.COLLAPSED - self.ICON) / 2.0,
                         (self.H - self.ICON) / 2.0)

    def _paint_expanded(self, p):
        self._paint_icon(p, self.PAD, (self.H - self.ICON) / 2.0)
        p.setPen(self._color())
        p.setFont(self._font)
        x = self.PAD + self.ICON + self.GAP
        w = max(0.0, self.width() - x - self.PAD)
        text = QFontMetricsF(self._font).elidedText(
            self._text, Qt.ElideRight, w)
        p.drawText(QRectF(x, 0, w, self.H),
                   Qt.AlignVCenter | Qt.AlignLeft, text)


class StatusStrip(QWidget):
    """胶囊栏左侧的进行中状态条（录制 | 音乐 | 倒计时）。

    默认展开优先级最高的进行中功能，其余收起为 26px 图标，未进行中的功能
    不占位；点击收起项互斥互换，点击当前展开项回到自动默认态。展开宽度
    统一，因此互换时整条宽度恒定。手动展开标记随该功能结束清空。
    """

    layout_changed = Signal()
    stop_record_requested = Signal()

    HEIGHT = 44
    FULL_W = 200      # 展开态统一宽度，保证互换时栏宽不变
    COLLAPSED = 26
    # 内容间距：相邻两段「可见内容」之间的空隙统一为 GAP_C，分隔线落在空隙
    # 中点 —— 线到两侧内容各 GAP_C / 2，收起图标也就被两条线对称夹住。段盒
    # 位置由内容位置反推（盒 = 内容 ∓ 内缩），所以展开段有内缩、收起段没有
    # 时，两者的内容间距依然相等。
    # 取值取「工具图标盒到分割线」的距离：1（线在状态条内缘）+ SPACING(10)
    # + 工具按钮内边距 (44 - 22) / 2 = 22，段间空隙因此与「线到工具图标」等长。
    # 代价是「状态条 | 工具组」那条边线左边只有 11、比右边短 —— 取 44 能让它
    # 左右等长，但收起图标之间会空得发虚，宁可接受这点偏短。
    # 下限是两段内缩之和：最大为「提示段 PAD + 收起段」= 14，低于它提示段的
    # 盒子就会压到邻居的可点区域。
    GAP_C = 22
    # 首段「内容」左边缘距本控件左缘的偏移。取 15 = 工具图标在胶囊里的视觉
    # 内缩（按钮盒内边距 (44−22)/2 = 11 + 字形墨迹内缩 4），于是状态条在时和
    # 不在时、以及左右两侧，胶囊外缘到墨迹的距离都是 29：封面（实心块、没有
    # 墨迹内缩）与右侧关闭图标（细线字形、含 4px 内缩）看起来才一样远。
    # 注意这是内容的位置，不是段盒的位置（段盒 = 内容 − 内缩）。
    MARGIN = 15
    SWAP_MS = 260     # 互换过渡时长
    NOTICE_MS = 2600  # 完成提示就地停留多久，到点自动撤下
    # 段的固定排列，同时也是展开优先级：录制 > 音乐 > 倒计时
    ORDER = ("record", "music", "timer")

    def __init__(self, timer, music, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self._manual = None
        self._music_enabled = False

        # 目标布局 key -> (x, w)；_from / _to 是本次过渡的首末帧。_target 永远
        # 是"真实目标"，_to 通常与它相同 —— 只有提示段撤下时多带一个 0 宽占位，
        # 好让它缩回 0 而不是凭空消失。段集合变化（首次出现 / 结束）直接落位。
        self._target = {}
        self._from = {}
        self._to = {}
        # 展开段结束时"展开位暂时空着"：不把收起态的邻居立刻提拔上来。录制
        # 优先于音乐 / 倒计时，所以录制收完、它的完成提示也说完，音乐才展开。
        # _hold_box 是那段结束前的盒子，用来把这一格先留空（提示一接手就清掉）；
        # _hold_key 是刚结束的那一段，_prev_keys 是上一次排布时的活动段。
        self._hold = False
        self._hold_box = None
        self._hold_key = None
        self._prev_keys = []
        self._swap = QVariantAnimation(self)
        self._swap.setDuration(self.SWAP_MS)
        self._swap.setEasingCurve(QEasingCurve.OutCubic)
        self._swap.valueChanged.connect(self._on_swap_frame)

        self.seg_record = RecordSegment(self)
        self.seg_music = MusicSegment(music, self)
        self.seg_timer = TimerSegment(timer, self)
        self.seg_notice = NoticeSegment(self)
        self._segs = (
            ("record", self.seg_record),
            ("music", self.seg_music),
            ("timer", self.seg_timer),
            ("notice", self.seg_notice),
        )
        self._seg_map = dict(self._segs)
        for key, seg in self._segs:
            # 提示段不可点击：它自带生命周期，没有"收起 / 展开"的用户语义。
            if key != "notice":
                seg.clicked.connect(lambda k=key: self._on_clicked(k))
            seg.hide()

        self._notice_on = False
        self._notice_slot = "timer"
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(self.dismiss_notice)

        self.seg_record.stop_requested.connect(self.stop_record_requested)
        self.seg_timer.reset_requested.connect(timer.reset_phase)
        self.seg_timer.close_requested.connect(timer.reset)

        # 任一段的进行中状态变化都要重排
        timer.phase_changed.connect(self._on_timer)
        timer.tick.connect(self._on_timer)
        timer.state_changed.connect(self._on_timer)
        music.state_changed.connect(self._on_music)
        self.apply_layout()

    # ----- 活动段与展开态 -----

    def _active_keys(self):
        keys = []
        for key, seg in self._segs:
            if key == "record":
                ok = self.seg_record.is_active()
            elif key == "music":
                ok = self._music_enabled and self.seg_music.has_track()
            elif key == "timer":
                ok = self.seg_timer.is_active()
            else:
                ok = self._notice_on
            if ok:
                keys.append(key)
        return keys

    def active_count(self):
        return len(self._active_keys())

    def _expanded_key(self):
        keys = self._active_keys()
        if not keys:
            return None
        # 点击指定的段优先（录制启停也走这条）
        if self._manual in keys:
            return self._manual
        # 展开位正被按住（刚结束的那段还占着格子）：先一个都不提拔。录制优先于
        # 音乐 / 倒计时，所以录制收完、它的完成提示也说完，音乐才展开。
        if self._hold:
            return None
        # 提示段不占展开位：它作为"额外一段"把胶囊栏伸出去，而不是把已经展开
        # 的邻居（比如换阶段时仍在跑的倒计时）挤回收起态。
        return keys[0]

    def _expanded_w(self, key):
        """展开段宽度：提示段按文案自适应，其余段统一 FULL_W。"""
        if key == "notice":
            return self.seg_notice.expanded_width()
        return self.FULL_W

    def _layout_order(self):
        """本次排布的段顺序：完成提示插在它所报告的那个状态段的格子上。

        消息必须出在"事情原来所在的那一格"（录制完成就落在录制段原来占的
        位置），否则用户会看到「录制完成」跑到倒计时那一格去。"""
        order = list(self.ORDER)
        if self._notice_on and self._notice_slot in order:
            order.insert(order.index(self._notice_slot), "notice")
        return order

    def _on_clicked(self, key):
        if key not in self._active_keys():
            return
        self._manual = None if self._expanded_key() == key else key
        self.apply_layout()

    def _boxes(self):
        """按当前活动段 / 展开态算出的最终几何 [(key, x, w), ...]。

        位置以「可见内容」为准推进：相邻段的内容间距恒为 GAP_C，分隔线落在
        中点，于是线到两侧内容的距离处处相等、收起图标被对称夹住。段盒左边缘
        = 内容左边缘 − 左内缩（收起 0、展开 EDGE / PAD），展开段的盒子因此向
        两侧各探出内缩那么多 —— 最右段是展开段时盒子末端会超出本控件宽度，
        那一段在内容之外没有要画的东西，被裁掉无碍。

        首段也从同一把尺子起算（内容左边缘 = MARGIN）：收起 / 展开切换时内容
        位置因此固定，只有右边缘在动，首段的内容不会随展开态左右漂。"""
        keys = self._active_keys()
        expanded = self._expanded_key()
        hold = self._hold_box
        boxes = []
        content_x = float(self.MARGIN)   # 下一段的内容左边缘
        for key in self._layout_order():
            if hold is not None and key == hold[0]:
                # 刚结束的那段：位置、宽度照旧占着，但它已经藏起来了 —— 展开位
                # 先留空给完成提示接手，收起态的邻居不许顶上来。
                w = hold[2]
            elif key in keys:
                # 提示段恒按文案宽度占位（它不参与互斥互换，出现时是额外的一段）
                w = (self._expanded_w(key) if key in ("notice", expanded)
                     else self.COLLAPSED)
            else:
                continue
            ins_l, ins_r = self._seg_map[key].content_insets(w)
            x = content_x - ins_l
            boxes.append((key, x, w))
            content_x = x + w - ins_r + self.GAP_C
        return boxes

    def apply_layout(self):
        """按活动段与展开态排布各段；整条宽度由 content_width() 给出。

        提示段的出现 / 撤下走"伸缩"过渡（它自己从 0 宽长到文案宽度、再缩回
        0，其余段被平滑推开 / 拉回，整条胶囊随之伸出再收回）；其余段集合变化
        （首次出现 / 结束）直接落位，伴随整条宽度动画即可；段集合不变的互换
        （点击收起项）走 SWAP_MS 的几何过渡。"""
        keys = self._active_keys()
        if self._manual not in keys:
            self._manual = None
        # 被按住的段又回来了（录制重启之类）：撤掉留空，恢复正常排布
        if self._hold and self._hold_key in keys:
            self._hold = False
            self._hold_box = None
            self._hold_key = None
        armed = self._arm_hold(keys)
        self._prev_keys = keys
        target = {key: (x, w) for key, x, w in self._boxes()}

        if set(self._target) != set(target):
            self._swap.stop()
            # 提示段在变：它是额外的一段，直接落位会在左端硬闪一下，补一个
            # 0 宽占位让它就地伸缩。
            if "notice" in set(self._target) ^ set(target):
                self._stretch_frames(self._target, target)
                return
            self._target = target
            self._apply_frame(target, target, 1.0)
            return
        if target == self._target and not armed:
            return
        if armed:
            # 盒子一个没变（结束的那段被留空占位顶着）：只需把结束段藏掉
            self._swap.stop()
            self._target = target
            self._apply_frame(target, target, 1.0)
            return
        self._from = dict(self._target)
        self._to = dict(target)
        self._target = target
        self._swap.stop()
        self._apply_frame(self._from, self._to, 0.0)
        self._swap.setStartValue(0.0)
        self._swap.setEndValue(1.0)
        self._swap.start()

    def _arm_hold(self, keys):
        """展开段刚结束：把它占的展开位先按住，别把收起态的邻居提拔上来。

        录制优先于音乐 / 倒计时 —— 录制一收，音乐不能马上顶上它的位置，先
        留空，等完成提示来接手那一格；提示说完才放开，音乐 / 倒计时这才展开。
        判定用"上一次排布的活动段"而不是几何：留空期间那一格一直挂在 _target
        里，只看几何会把它反复当成"刚结束"。没有提示跟上的情况（音乐自己停
        了之类）由一个 0 延时的兜底调用放开，日常无感。"""
        if self._hold:
            return False
        for key in self._prev_keys:
            if key == "notice" or key in keys:
                continue
            box = self._target.get(key)
            if not box or box[1] <= self.COLLAPSED:
                continue
            self._hold = True
            self._hold_key = key
            # 提示已经登场（倒计时到点就是这个顺序）：格子直接交给提示，不再留空
            self._hold_box = None if self._notice_on else (key, box[0], box[1])
            QTimer.singleShot(0, self._release_hold)
            return True
        return False

    def _apply_frame(self, frm, to, p):
        """把插值 p 落成各段的几何与形态（互换 / 伸缩过渡的每一帧调用）。

        展开 / 收起形态按"当前插值宽度"过半判定，而不是跟随目标态：这样
        过渡首帧不会出现内容瞬间抽空（宽盒子里只剩一个小图标）的跳变，
        内容是在盒子展开过半时才长出来，收起的盒子先把内容裁掉再合上。
        过半线按各段自己的展开宽度算（提示段宽度随文案变），而不是一个共用
        常量，否则短文案的提示段会以收起形态占着展开位。"""
        for key, seg in self._segs:
            # 留空的那格虽然还在 to 里（位置、宽度都占着），但它已经结束了，
            # 得藏起来 —— 否则旧内容会和刚长出来的提示重叠。
            if key not in to or (self._hold_box is not None
                                 and key == self._hold_box[0]):
                seg.hide()
                continue
            x0, w0 = frm.get(key, to[key])
            x1, w1 = to[key]
            x = x0 + (x1 - x0) * p
            w = w0 + (w1 - w0) * p
            seg.setGeometry(int(round(x)), 0, max(1, int(round(w))),
                            self.HEIGHT)
            seg.set_collapsed(w < (self._expanded_w(key) + self.COLLAPSED) / 2.0)
            seg.relayout()
            seg.show()
        # 收尾：_to 里那些只作占位存在的段（提示段撤下）到这里才真正撤掉，
        # 文案也在这一刻清空 —— 提前清会在收缩中途闪一下空白。
        if p >= 1.0:
            for key, seg in self._segs:
                if key in to and key not in self._target:
                    if key == "notice":
                        self.seg_notice.set_notice("")
                    seg.hide()
        # 兜底：提示被别的排布变化直接顶掉时（没走 dismiss_notice），留空位
        # 到这儿才放开。正常路径由 dismiss_notice 在提示开始收起时同步放开，
        # 音乐 / 倒计时的展开与提示的收缩是并行的。
        if (p >= 1.0 and self._hold and self._hold_box is None
                and not self._notice_on and "notice" not in self._target):
            QTimer.singleShot(0, self._release_hold)
        self.update()

    def _stretch_frames(self, prev, target):
        """提示段出现 / 撤下时的伸缩过渡。

        给提示段补一个 0 宽的首帧（出现）或末帧（撤下），其余段照常从旧位置
        插值到新位置 —— 于是提示段就地长出来 / 缩回去、邻居被平滑推开 / 拉回，
        整条胶囊随之伸出再收回，全程没有硬切。

        撤下时的末帧位置取"提示原本插的那一格在新排布里的落点"，而不是它
        当前所在的 x：提示一边缩一边滑向那一格，把展开位让给同时要展开的那
        一段 —— 两段动画并行，盒子又始终不重叠（提示在要展开段左边时它原地
        缩，在右边时它往右让开）。"""
        self._from = dict(prev)
        self._to = dict(target)
        if "notice" in target:
            self._from["notice"] = (target["notice"][0], 0)
        else:
            self._to["notice"] = (self._notice_retire_x(target), 0)
        self._target = target
        self._swap.stop()
        self._apply_frame(self._from, self._to, 0.0)
        self._swap.setStartValue(0.0)
        self._swap.setEndValue(1.0)
        self._swap.start()

    def _notice_retire_x(self, target):
        """提示撤下后收在哪儿：按 _boxes() 同一套推进方式走一遍它前面那几段。

        提示自身 0 宽、内缩为 0，所以它的盒子左边缘就等于那一段的位置。"""
        x = self.MARGIN
        for key in self.ORDER:
            if key == self._notice_slot:
                break
            box = target.get(key)
            if box is None:
                continue
            bx, bw = box
            _ins_l, ins_r = self._seg_map[key].content_insets(bw)
            x = bx + bw - ins_r + self.GAP_C
        return x

    def _on_swap_frame(self, value):
        self._apply_frame(self._from, self._to, float(value))

    def content_width(self):
        """整条需要的宽度：恰好一个展开段 + 其余收起段 +（有提示时）提示段。

        右端收在「最右段内容的右边界 + GAP_C / 2 + 1」：GAP_C / 2 与段间分隔
        线保持一致（最右内容到「状态条 | 工具组」那条线的距离等于段间距离），
        1px 是那条线本身。"""
        boxes = self._boxes()
        if not boxes:
            return 0
        key, x, w = boxes[-1]
        _ins_l, ins_r = self._seg_map[key].content_insets(w)
        return int(round(x + w - ins_r + self.GAP_C / 2.0)) + 1

    # ----- 状态源 -----

    def record_started(self):
        self.seg_record.start()
        # 录制优先级最高：开始即占用展开位（其余进行中段折叠为小图标）
        self._manual = "record"
        self._changed()

    def record_stopped(self):
        self.seg_record.stop()
        self._changed()

    def set_music_enabled(self, enabled):
        self._music_enabled = bool(enabled)
        if not enabled:
            self.seg_music.clear()
        self._changed()

    # ----- 完成提示 -----

    def show_notice(self, text, icon_svg=ICON_TIMER, slot="timer"):
        """就地伸缩出一条完成提示，NOTICE_MS 后自动撤下。

        录制结束 / 倒计时结束都是一次性的「做完了」反馈：它作为额外一段把
        胶囊栏伸出去、到点再缩回来，全程走伸缩过渡，不挤占已经展开的邻居。
        slot 指定这条提示报告的是哪个状态段（"record" / "timer"），用来决定
        它出现在哪一格。"""
        self.seg_notice.set_notice(text, icon_svg)
        self._notice_slot = slot if slot in self.ORDER else "timer"
        self._notice_on = True
        # 提示接手被按住的那一格（留空到此为止）；_hold 保持为真，音乐 / 倒计时
        # 继续在 26px 上等着，等提示说完才放开。
        self._hold_box = None
        self._notice_timer.start(self.NOTICE_MS)
        self._changed()

    def dismiss_notice(self):
        """撤下完成提示（到点自动调用；胶囊栏隐藏时也必须调用）。

        不在这里清文案：让它先把盒子缩回 0（伸缩过渡），文案在过渡收尾帧才
        由 _apply_frame 清空，否则收缩中途会闪一下空白。

        同一步放开留空位：音乐 / 倒计时的展开与提示的收缩跑在同一次过渡里
        （并行），而不是等提示彻底消失后再单独动一次（两段、拖沓）。"""
        self._notice_timer.stop()
        if not self._notice_on:
            return
        self._notice_on = False
        if self._hold:
            self._release_hold()      # 内部会 _changed()
            return
        self._changed()

    def _release_hold(self):
        """放开被按住的展开位，让还活着的段按优先级正常展开。

        由 dismiss_notice 在提示一开始收起时调用 —— 提示的收缩和音乐 / 倒计时
        的展开因此是同一段过渡里的并行动画；提示还在显示时不放（_notice_on），
        免得把撑在提示旁边的音乐提前展开。"""
        if not self._hold or self._notice_on:
            return
        key = self._hold_key
        self._hold = False
        self._hold_box = None
        self._hold_key = None
        # 把留空占位从"上一帧"里摘掉：那段已经结束了，它的盒子不该再算数 ——
        # 否则段集合被误判成变了，还活着的段会被直接落位（硬切）而不是过渡。
        if key is not None and key not in self._active_keys():
            self._target.pop(key, None)
            self._from.pop(key, None)
            self._to.pop(key, None)
        self._changed()

    def _on_music(self, _state):
        self._changed()

    def _on_timer(self, *_):
        self.seg_timer.refresh()
        self._changed()

    def _changed(self):
        self.apply_layout()
        self.layout_changed.emit()

    # ----- 动态展开时的内容淡入 -----

    def set_reveal(self, o):
        for _key, seg in self._segs:
            seg.set_reveal(o)

    def clear_hover(self):
        for _key, seg in self._segs:
            seg.clear_hover()

    # ----- 绘制：与工具图标组的分隔线 -----

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(QColor(128, 128, 128, 100), 1))
        # 相邻两段之间都要有分隔线：几个 26px 圆形图标并排时会糊成一片，展开
        # 段与旁边的收起图标之间同样分不清边界（展开的音乐紧挨着收起的录制，
        # 视觉上会连成一块）。按实际 x 排序，提示段插在中间时顺序也正确。
        shown = [seg for _key, seg in self._segs if seg.isVisible()]
        shown.sort(key=lambda s: s.geometry().x())
        for left, right in zip(shown, shown[1:]):
            # 取两段「可见内容」边界的中点。布局保证了相邻内容间距恒为 GAP_C
            #（内缩由 _boxes() 反推进盒子位置摊掉），所以这条线到两侧内容的
            # 距离都是 GAP_C / 2，被夹在中间的收起图标也就自然居中。
            lg, rg = left.geometry(), right.geometry()
            lx = lg.x() + lg.width() - left.content_insets()[1]
            rx = rg.x() + right.content_insets()[0]
            x = int((lx + rx) / 2.0)
            p.drawLine(x, 12, x, self.HEIGHT - 12)
        # 状态条与右侧工具图标组之间的分隔线：content_width() 让最右段内容到
        # 这条线的距离同样是 GAP_C / 2。
        p.drawLine(self.width() - 1, 12, self.width() - 1, self.HEIGHT - 12)
        p.end()