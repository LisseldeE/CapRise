"""
天气
Open-Meteo 天气数据服务与详情卡片窗口
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import (
    QObject, QPointF, QRectF, Qt, QTimer, QPropertyAnimation, QEasingCurve,
    Property, Signal
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QPainter, QPalette, QPen
)
from PySide6.QtWidgets import QApplication, QWidget

from modules.config import Config
from modules.family import FamilyWindowRegistry
from modules.i18n import I18n
from modules.icons import weather_icon
from modules.widgets import make_pixmap, paint_pill

# Open-Meteo：免 key 的开放天气 API。geocoding 把城市名换成经纬度，
# forecast 取当前实况与逐时预报。
_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_UA = "CapRise"

# WMO 天气码 -> 条件名。条件名再决定单色图标与本地化文案（7 类）。
_WMO_CONDITION = {
    0: "clear", 1: "partly", 2: "partly", 3: "cloudy",
    45: "fog", 48: "fog",
    51: "rain", 53: "rain", 55: "rain", 56: "rain", 57: "rain",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow",
    80: "rain", 81: "rain", 82: "rain",
    85: "snow", 86: "snow",
    95: "thunder", 96: "thunder", 99: "thunder",
}

# 单色图标光栅化缓存（卡片重绘频繁，不能每帧重建）。
_glyph_cache = {}


def _glyph(svg, color_name, size):
    key = (svg, color_name, size)
    pm = _glyph_cache.get(key)
    if pm is None:
        pm = make_pixmap(svg, color_name, size)
        _glyph_cache[key] = pm
    return pm


def _hex(color):
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


def condition_of(code):
    """WMO 天气码 -> 条件名（未知码按「阴」处理）。"""
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = -1
    return _WMO_CONDITION.get(code, "cloudy")


def condition_text(condition):
    """条件名 -> 本地化文案。"""
    return I18n.tr(f"weather_{condition}")


def format_temp(celsius, unit="c"):
    """摄氏原始值 -> 显示温度（含 ° 符号）；缺失返回 '--'。

    数据一律按摄氏缓存，显示时再换算 —— 用户切换单位不需要重新联网。"""
    if celsius is None:
        return "--"
    try:
        value = float(celsius)
    except (TypeError, ValueError):
        return "--"
    if unit == "f":
        value = value * 9.0 / 5.0 + 32.0
    return f"{int(round(value))}°"


def format_int(value, suffix=""):
    """整数显示（湿度 / 风速这类）；缺失返回 '--'。"""
    if value is None:
        return "--"
    try:
        return f"{int(round(float(value)))}{suffix}"
    except (TypeError, ValueError):
        return "--"


def _geocode(city, timeout=8):
    """把城市名解析成一个地点；没有匹配时返回 None。

    取候选列表再按人口挑最大的那个，而不是 count=1 直接吃第一条：同一个名字
    往往对应多个地方（"伦敦"会先命中加拿大安大略省的同名小镇，"New York" 会
    先命中内布拉斯加州的 York），只看第一条会把用户送到错的城市。"""
    lang = "zh" if I18n.get_language() == "zh_CN" else "en"
    query = urllib.parse.urlencode({
        "name": city, "count": 8, "language": lang, "format": "json"})
    req = urllib.request.Request(f"{_GEO_URL}?{query}",
                                 headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        geo = json.loads(resp.read().decode("utf-8"))
    results = geo.get("results") or []
    if not results:
        return None
    return max(results, key=lambda r: r.get("population") or 0)


def fetch_weather(city, timeout=8):
    """抓取指定城市的实况 + 逐时预报（后台线程调用）。

    全程 stdlib urllib，无第三方依赖；失败直接抛异常，由服务转成错误文本。"""
    hit = _geocode(city, timeout)
    if hit is None:
        raise RuntimeError(I18n.tr("weather_city_not_found"))

    params = urllib.parse.urlencode({
        "latitude": hit["latitude"],
        "longitude": hit["longitude"],
        "current": ("temperature_2m,relative_humidity_2m,"
                    "apparent_temperature,weather_code,wind_speed_10m"),
        "hourly": "temperature_2m,weather_code",
        "timezone": "auto",
        "forecast_days": 2,
    })
    req = urllib.request.Request(f"{_FORECAST_URL}?{params}",
                                 headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        wx = json.loads(resp.read().decode("utf-8"))

    cur = wx.get("current") or {}
    hourly = wx.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    # 从当前整点起取 6 格。实况时间可能不是整点，按 "YYYY-MM-DDTHH" 前缀对齐。
    hour_key = str(cur.get("time", ""))[:13] + ":00"
    start = 0
    for i, stamp in enumerate(times):
        if stamp[:13] + ":00" >= hour_key:
            start = i
            break
    slots = []
    for i in range(start, min(start + 6, len(times))):
        slots.append({
            "time": times[i][11:16],
            "temp": temps[i] if i < len(temps) else None,
            "code": codes[i] if i < len(codes) else 0,
        })

    place = hit.get("name") or city
    if hit.get("admin1") and hit["admin1"] != place:
        place = f"{place}, {hit['admin1']}"

    return {
        "query": city,
        "city": place,
        "temp": cur.get("temperature_2m"),
        "feels": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "wind": cur.get("wind_speed_10m"),
        "code": cur.get("weather_code", 0),
        "hourly": slots,
        "fetched": int(time.time()),
    }


class WeatherService(QObject):
    """天气数据源：后台抓取 + 定时刷新 + 本地缓存。

    城市为空或功能关闭时不做任何请求；请求失败保留上一次结果（天气片不消
    失），错误文本交给设置页展示。网络走 stdlib urllib + 后台线程，与 about /
    translate 的做法一致，不引入新依赖。"""

    data_changed = Signal()
    _fetched = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = None
        self._error = ""
        self._query = ""
        self._busy = False
        self._stopped = True
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        # worker 在子线程 emit，Qt 自动排队到主线程执行 _on_fetched。
        self._fetched.connect(self._on_fetched)
        self._load_cache()

    # ----- 对外状态 -----

    def data(self):
        return self._data

    def has_data(self):
        return self._data is not None

    def error(self):
        return self._error

    def is_enabled(self):
        return bool(Config().get("weather_enabled", True))

    def unit(self):
        return Config().get("weather_unit", "c")

    def resolved_city(self):
        """已解析到的城市显示名（尚未取到数据时为空串）。"""
        if self._data:
            return self._data.get("city", "")
        return ""

    def pending_city(self):
        """设置里填写的城市名。"""
        return self._city()

    # ----- 生命周期 -----

    def start(self):
        self._stopped = False
        self._apply_interval()
        self.refresh()

    def stop(self):
        self._stopped = True
        self._timer.stop()

    def apply_config(self):
        """设置改动后调用：城市变了重新抓取，否则只通知界面重绘（单位 / 间隔）。"""
        if not self.is_enabled():
            self.stop()
            self._data = None
            self._error = ""
            self.data_changed.emit()
            return
        self._stopped = False
        self._apply_interval()
        # 城市变了要重抓；此外只要手里还没有数据（首次启用 / 上次失败）也抓一次，
        # 否则重新启用后会一直空着，要等下一个刷新周期才有天气。
        if self._city() != self._query or self._data is None:
            self._data = None
            self.refresh()
        else:
            self.data_changed.emit()

    def refresh(self):
        """立即抓取一次（已有请求在跑就跳过，避免并发线程）。"""
        city = self._city()
        if self._stopped or self._busy or not self.is_enabled() or not city:
            return
        self._busy = True
        threading.Thread(target=self._worker, args=(city,),
                         daemon=True).start()

    # ----- 内部 -----

    def _apply_interval(self):
        try:
            minutes = int(Config().get("weather_refresh_min", 15))
        except (TypeError, ValueError):
            minutes = 15
        minutes = max(5, minutes)
        self._timer.setInterval(minutes * 60 * 1000)
        if self.is_enabled() and self._city():
            self._timer.start()
        else:
            self._timer.stop()

    def _worker(self, city):
        """后台抓取。网络抖动（TLS 握手的偶发超时很常见）失败就重试一次；城市
        不存在这类确定性失败不重试。"""
        last = None
        for attempt in range(2):
            try:
                self._fetched.emit(("ok", fetch_weather(city)))
                return
            except Exception as exc:        # 网络 / 解析 / 城市不存在
                last = exc
                if str(exc) == I18n.tr("weather_city_not_found"):
                    break
                if attempt == 0:
                    time.sleep(1.5)
        self._fetched.emit(("err", str(last)))

    def _on_fetched(self, result):
        self._busy = False
        if self._stopped:
            return
        kind, value = result
        if kind == "ok":
            self._data = value
            self._error = ""
            self._query = value.get("query", "")
            self._save_cache()
        else:
            # 失败保留上次结果；首次失败时 _data 仍为空，天气片不出现。
            self._error = value
        self.data_changed.emit()

    def _city(self):
        return str(Config().get("weather_city", "") or "").strip()

    def _cache_path(self):
        folder = Path.home() / "CapRise"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "weather.json"

    def _load_cache(self):
        try:
            path = self._cache_path()
            if not path.exists():
                return
            obj = json.loads(path.read_text(encoding="utf-8"))
            if (obj.get("query") == self._city()
                    and isinstance(obj.get("data"), dict)):
                self._data = obj["data"]
                self._query = obj["query"]
        except Exception:
            pass

    def _save_cache(self):
        try:
            self._cache_path().write_text(
                json.dumps({"query": self._query, "data": self._data},
                           ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass


class WeatherCard(QWidget):
    """胶囊下方的天气详情卡：恒宽无边框置顶窗，展开 / 收起带动画。

    独立顶层窗口而不是胶囊的子控件 —— 胶囊用 setMask 把整窗裁成胶囊形状，
    挂在下方的卡片会被裁掉；改 mask 又要重算窗口高度并连带 _recenter 抖动。
    写法照 TimerNoticeOverlay：Qt.Tool + 半透明背景 + 不抢焦点。"""

    W = 280
    PAD = 16
    H = 168
    ANIM_MS = 220

    # 卡片内容自上而下的几行
    TITLE_Y = 14
    TITLE_H = 18
    ICON = 18
    KPI_Y = 40
    KPI_H = 48
    SEP_Y = 98
    HOUR_Y = 106
    HOUR_H = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(self.W)
        self._data = None
        self._t = 0.0
        self._x = 0
        self._y = 0
        self._closing = False

        self._title_font = QFont()
        self._title_font.setPixelSize(13)
        self._title_font.setBold(True)
        self._desc_font = QFont()
        self._desc_font.setPixelSize(11)
        self._caption_font = QFont()
        self._caption_font.setPixelSize(10)
        self._metric_font = QFont("Consolas")
        self._metric_font.setPixelSize(12)
        self._big_font = QFont("Consolas")
        self._big_font.setPixelSize(28)
        self._big_font.setBold(True)

        self._anim = QPropertyAnimation(self, b"revealT")
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)

    # ----- 展开进度 -----

    def _get_reveal(self):
        return self._t

    def _set_reveal(self, value):
        """0..1 进度同时驱动窗口高度（自上而下揭示）与整体不透明度。"""
        self._t = max(0.0, min(1.0, float(value)))
        height = max(1, int(round(self.H * self._t)))
        self.setGeometry(int(self._x), int(self._y), self.W, height)
        self.setWindowOpacity(self._t)
        self.update()

    revealT = Property(float, _get_reveal, _set_reveal)

    # ----- 对外 -----

    def set_data(self, data):
        self._data = data
        self.update()

    def popup_at(self, x, y):
        """在屏幕坐标 (x, y)（卡片左上角）弹出并展开。"""
        self._closing = False
        self._x, self._y = int(x), int(y)
        self._set_reveal(0.0)
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def dismiss(self):
        """反向动画收起；动画结束才真正隐藏。"""
        if not self.isVisible():
            return
        self._closing = True
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def move_to(self, x, y):
        """跟随天气片重新对位（不触发动画，也不改展开进度）。

        胶囊栏里的天气片会随着其他状态段出现 / 结束而移动（展开↔小图标），
        已展开的卡片要跟着它走，不能停在旧位置上。"""
        self._x, self._y = int(x), int(y)
        self.setGeometry(self._x, self._y, self.W, max(1, self.height()))

    # ----- 窗口生命周期 -----

    def showEvent(self, event):
        super().showEvent(event)
        FamilyWindowRegistry.add(self)
        FamilyWindowRegistry.refresh_hwnd(self)
        FamilyWindowRegistry.set_no_activate(self)

    def hideEvent(self, event):
        # 隐藏后必须摘掉 HWND：否则「点击是否落在家族窗口内」会把卡片原来的
        # 矩形算进去，收起后点那个位置反而不会触发隐藏。
        FamilyWindowRegistry.remove(self)
        self._anim.stop()
        super().hideEvent(event)

    def _on_anim_finished(self):
        if self._closing:
            self._closing = False
            self.hide()

    # ----- 绘制 -----

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_pill(p, QRectF(0, 0, self.W, self.H), 18)
        data = self._data
        if data is None:
            p.end()
            return

        ink = QApplication.palette().color(QPalette.WindowText)
        muted = QColor(ink)
        muted.setAlpha(150)
        unit = Config().get("weather_unit", "c")
        condition = condition_of(data.get("code", 0))
        ink_hex = _hex(ink)

        self._paint_title(p, data, condition, ink, muted, ink_hex)
        self._paint_kpi(p, data, unit, ink, muted)
        p.setPen(QPen(QColor(128, 128, 128, 90), 1))
        p.drawLine(QPointF(self.PAD, self.SEP_Y),
                   QPointF(self.W - self.PAD, self.SEP_Y))
        self._paint_hourly(p, data, unit, ink, muted, ink_hex)
        p.end()

    def _paint_title(self, p, data, condition, ink, muted, ink_hex):
        """图标 + 城市 + 天气文字，右端「18:40 更新」。"""
        pm = _glyph(weather_icon(condition), ink_hex, self.ICON)
        p.drawPixmap(QPointF(self.PAD, self.TITLE_Y
                             + (self.TITLE_H - self.ICON) / 2.0), pm)

        stamp = I18n.tr(
            "weather_updated",
            time=time.strftime("%H:%M",
                               time.localtime(data.get("fetched")
                                              or time.time())))
        p.setFont(self._desc_font)
        stamp_w = QFontMetricsF(self._desc_font).horizontalAdvance(stamp)
        stamp_x = self.W - self.PAD - stamp_w
        p.setPen(muted)
        p.drawText(QRectF(stamp_x, self.TITLE_Y, stamp_w + 1, self.TITLE_H),
                   Qt.AlignVCenter | Qt.AlignLeft, stamp)

        x = self.PAD + self.ICON + 8
        avail = max(0.0, stamp_x - 8 - x)
        city_fm = QFontMetricsF(self._title_font)
        city = data.get("city") or ""
        city_w = min(city_fm.horizontalAdvance(city), avail * 0.62)
        p.setPen(ink)
        p.setFont(self._title_font)
        p.drawText(QRectF(x, self.TITLE_Y, city_w, self.TITLE_H),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   city_fm.elidedText(city, Qt.ElideRight, city_w))

        desc_x = x + city_w + 8
        desc_w = max(0.0, stamp_x - 8 - desc_x)
        desc_fm = QFontMetricsF(self._desc_font)
        p.setPen(muted)
        p.setFont(self._desc_font)
        p.drawText(QRectF(desc_x, self.TITLE_Y, desc_w, self.TITLE_H),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   desc_fm.elidedText(condition_text(condition),
                                      Qt.ElideRight, desc_w))

    def _paint_kpi(self, p, data, unit, ink, muted):
        """大号气温 + 三组「标签 / 值」（体感、湿度、风速）。"""
        p.setPen(ink)
        p.setFont(self._big_font)
        p.drawText(QRectF(self.PAD, self.KPI_Y, 96, self.KPI_H),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   format_temp(data.get("temp"), unit))

        groups = (
            (I18n.tr("weather_feels"),
             format_temp(data.get("feels"), unit)),
            (I18n.tr("weather_humidity"),
             format_int(data.get("humidity"), "%")),
            (I18n.tr("weather_wind"),
             format_int(data.get("wind"), "km/h")),
        )
        x0 = self.PAD + 104
        col = (self.W - self.PAD - x0) / float(len(groups))
        for i, (label, value) in enumerate(groups):
            cx = x0 + i * col
            p.setPen(muted)
            p.setFont(self._caption_font)
            p.drawText(QRectF(cx, self.KPI_Y + 6, col - 4, 14),
                       Qt.AlignVCenter | Qt.AlignLeft, label)
            p.setPen(ink)
            p.setFont(self._metric_font)
            p.drawText(QRectF(cx, self.KPI_Y + 22, col - 4, 18),
                       Qt.AlignVCenter | Qt.AlignLeft, value)

    def _paint_hourly(self, p, data, unit, ink, muted, ink_hex):
        """一行 6 格逐时：时刻、图标、温度。"""
        slots = data.get("hourly") or []
        if not slots:
            return
        cell = (self.W - 2 * self.PAD) / float(len(slots))
        for i, slot in enumerate(slots):
            left = self.PAD + i * cell
            center = left + cell / 2.0
            p.setPen(muted)
            p.setFont(self._caption_font)
            p.drawText(QRectF(left, self.HOUR_Y, cell, 13),
                       Qt.AlignHCenter | Qt.AlignTop, slot.get("time", ""))
            pm = _glyph(weather_icon(condition_of(slot.get("code", 0))),
                        ink_hex, 16)
            p.drawPixmap(QPointF(center - 8, self.HOUR_Y + 16), pm)
            p.setPen(ink)
            p.setFont(self._metric_font)
            p.drawText(QRectF(left, self.HOUR_Y + 33, cell, 14),
                       Qt.AlignHCenter | Qt.AlignTop,
                       format_temp(slot.get("temp"), unit))