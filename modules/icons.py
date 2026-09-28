"""
图标库
内置 SVG 图标常量集合
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
# SVG icons - hardcoded, no external downloads needed
# All icons use viewBox="0 0 24 24", stroke="currentColor" for theme compatibility

ICON_SCREENSHOT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="5" width="18" height="14" rx="2" ry="2"/>
  <circle cx="12" cy="12" r="4"/>
  <line x1="9" y1="3" x2="15" y2="3"/>
  <line x1="12" y1="3" x2="12" y2="5"/>
</svg>"""

ICON_ANNOTATION = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
  <circle cx="18" cy="5" r="0.5" fill="currentColor"/>
</svg>"""

ICON_SETTINGS = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="3"/>
  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
</svg>"""

ICON_CLOSE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <line x1="18" y1="6" x2="6" y2="18"/>
  <line x1="6" y1="6" x2="18" y2="18"/>
</svg>"""

ICON_MINUS = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <line x1="5" y1="12" x2="19" y2="12"/>
</svg>"""

ICON_RECTANGLE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
</svg>"""

ICON_FREEFORM = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M3 17c3-2 6-10 9-6s6 4 9 0"/>
</svg>"""

ICON_ERASER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/>
  <path d="M22 21H7"/>
  <path d="m5 11 9 9"/>
</svg>"""

ICON_TEXT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="4 7 4 4 20 4 20 7"/>
  <line x1="12" y1="4" x2="12" y2="20"/>
  <line x1="8" y1="20" x2="16" y2="20"/>
</svg>"""

ICON_TRANSLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="m5 8 6 6"/>
  <path d="m4 14 6-6 2-3"/>
  <path d="M2 5h12"/>
  <path d="M7 2h1"/>
  <path d="m22 22-5-10-5 10"/>
  <path d="M14 18h6"/>
</svg>"""

# Swap / convert between the source and target language in the translate
# sub-bar: two arrows pointing inward at the middle.
ICON_SWAP = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M8 3 4 7l4 4"/>
  <path d="M4 7h16"/>
  <path d="m16 21 4-4-4-4"/>
  <path d="M20 17H4"/>
</svg>"""

# Single-direction arrow (right) indicating flow from source to target in
# the translate sub-bar — not the bidirectional swap.
ICON_ARROW_RIGHT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M5 12h14"/>
  <path d="m12 5 7 7-7 7"/>
</svg>"""

# Close / delete an overlay element — white X on the delete bean.
ICON_X = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
  <path d="M18 6 6 18"/>
  <path d="m6 6 12 12"/>
</svg>"""

# --- Clipboard feature icons ---

ICON_CLIPBOARD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="5" y="4" width="14" height="17" rx="2"/>
  <path d="M9 4V3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1"/>
  <path d="M9 11h6M9 15h4"/>
</svg>"""

# --- Search feature icons ---

ICON_SEARCH = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="11" cy="11" r="7"/>
  <line x1="21" y1="21" x2="16.65" y2="16.65"/>
</svg>"""

ICON_APP = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="3" width="18" height="18" rx="3"/>
  <path d="M3 9h18M9 21V9"/>
</svg>"""

ICON_FILE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
  <polyline points="14 2 14 8 20 8"/>
</svg>"""

ICON_CALC = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="4" y="2" width="16" height="20" rx="2"/>
  <line x1="8" y1="6" x2="16" y2="6"/>
  <line x1="8" y1="11" x2="8" y2="11.01"/>
  <line x1="12" y1="11" x2="12" y2="11.01"/>
  <line x1="16" y1="11" x2="16" y2="11.01"/>
  <line x1="8" y1="16" x2="8" y2="16.01"/>
  <line x1="12" y1="16" x2="12" y2="16.01"/>
  <line x1="16" y1="16" x2="16" y2="16.01"/>
</svg>"""

ICON_COPY = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="9" y="9" width="11" height="11" rx="2"/>
  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
</svg>"""

ICON_TRASH = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M3 6h18"/>
  <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/>
  <path d="M5 6l1 14a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1l1-14"/>
  <path d="M10 11v6M14 11v6"/>
</svg>"""

ICON_NETWORK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="6" cy="12" r="2.5"/>
  <circle cx="18" cy="6" r="2.5"/>
  <circle cx="18" cy="18" r="2.5"/>
  <path d="M8.2 10.8l7.6-3.6M8.2 13.2l7.6 3.6"/>
</svg>"""

ICON_ROOM = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="7" cy="15" r="4"/>
  <path d="M10 12l9-9M16 6l2 2M14 8l2 2"/>
</svg>"""

ICON_CHECK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="20 6 9 17 4 12"/>
</svg>"""

# --- Timer feature icons ---

ICON_TIMER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M5 22h14"/>
  <path d="M5 2h14"/>
  <path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/>
  <path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>
</svg>"""

ICON_ROTATE_CCW = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M3 12a9 9 0 1 0 2.64-6.36L3 8"/>
  <path d="M3 3v5h5"/>
</svg>"""

ICON_PAUSE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M8 5v14M16 5v14"/>
</svg>"""

ICON_PLAY = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M7 5l12 7-12 7z"/>
</svg>"""

ICON_PICKER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="m2 22 1-1h3l9-9"/>
  <path d="M3 21v-3l9-9"/>
  <path d="m15 6 3.4-3.4a2.1 2.1 0 1 1 3 3L18 9l.4.4a2.1 2.1 0 1 1-3 3l-3.8-3.8a2.1 2.1 0 1 1 3-3l.4.4Z"/>
</svg>"""

# --- Music capsule icons (SMTC playback control) ---

# Beamed quaver: doubles as the fallback badge when a track has no artwork.
ICON_MUSIC = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M9 18V5l11-2v13"/>
  <circle cx="6" cy="18" r="3"/>
  <circle cx="17" cy="16" r="3"/>
</svg>"""

ICON_PREV = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M19 19V5l-11 7z"/>
  <line x1="6" y1="5" x2="6" y2="19"/>
</svg>"""

ICON_NEXT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M5 5v14l11-7z"/>
  <line x1="18" y1="5" x2="18" y2="19"/>
</svg>"""

# --- Record status icons ---

# Stop: a filled rounded square. make_pixmap only recolors stroke= (a literal
# fill="currentColor" would not resolve), so the block is made by thickening
# the stroke until the hole closes: an 8x8 rect with stroke-width 8 leaves no
# inner area and spans 4..20, matching the previous outline's footprint
# (rx 0.5 + stroke/2 = 4.5 outer corner radius, as before).
ICON_STOP = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="8" stroke-linecap="round" stroke-linejoin="round">
  <rect x="8" y="8" width="8" height="8" rx="0.5"/>
</svg>"""

# Record: outer ring + solid centre dot, used as the recording notice badge.
ICON_RECORD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="9"/>
  <circle cx="12" cy="12" r="1" stroke-width="6"/>
</svg>"""

# --- Weather icons (single-colour outline, so make_pixmap can recolour them) ---

ICON_WEATHER_CLEAR = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="4"/>
  <path d="M12 2v2"/>
  <path d="M12 20v2"/>
  <path d="m4.93 4.93 1.41 1.41"/>
  <path d="m17.66 17.66 1.41 1.41"/>
  <path d="M2 12h2"/>
  <path d="M20 12h2"/>
  <path d="m6.34 17.66-1.41 1.41"/>
  <path d="m19.07 4.93-1.41 1.41"/>
</svg>"""

ICON_WEATHER_PARTLY = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2v2"/>
  <path d="m4.93 4.93 1.41 1.41"/>
  <path d="M20 12h2"/>
  <path d="m19.07 4.93-1.41 1.41"/>
  <path d="M15.947 12.65a4 4 0 0 0-5.925-4.128"/>
  <path d="M13 22H7a5 5 0 1 1 4.9-6H13a3 3 0 0 1 0 6Z"/>
</svg>"""

ICON_WEATHER_CLOUDY = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M17.5 21H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>
  <path d="M22 10a3 3 0 0 0-3-3h-2.207a5.502 5.502 0 0 0-10.702.5"/>
</svg>"""

ICON_WEATHER_FOG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
  <path d="M16 17H7"/>
  <path d="M17 21H9"/>
</svg>"""

ICON_WEATHER_RAIN = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
  <path d="M16 14v6"/>
  <path d="M8 14v6"/>
  <path d="M12 16v6"/>
</svg>"""

ICON_WEATHER_SNOW = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
  <path d="M8 15h.01"/>
  <path d="M8 19h.01"/>
  <path d="M12 17h.01"/>
  <path d="M12 21h.01"/>
  <path d="M16 15h.01"/>
  <path d="M16 19h.01"/>
</svg>"""

ICON_WEATHER_THUNDER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M6 16.326A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 .5 8.973"/>
  <path d="m13 12-3 5h4l-3 5"/>
</svg>"""

# 天气条件名 -> 单色图标。条件名由 weather.condition_of() 从 WMO 天气码推出。
_WEATHER_ICONS = {
    "clear": ICON_WEATHER_CLEAR,
    "partly": ICON_WEATHER_PARTLY,
    "cloudy": ICON_WEATHER_CLOUDY,
    "fog": ICON_WEATHER_FOG,
    "rain": ICON_WEATHER_RAIN,
    "snow": ICON_WEATHER_SNOW,
    "thunder": ICON_WEATHER_THUNDER,
}


def weather_icon(condition):
    """天气条件名对应的图标；未知条件回退到「多云」。"""
    return _WEATHER_ICONS.get(condition, ICON_WEATHER_CLOUDY)


def icon_svg(name):
    icons = {
        "screenshot": ICON_SCREENSHOT,
        "annotation": ICON_ANNOTATION,
        "settings": ICON_SETTINGS,
        "close": ICON_CLOSE,
        "minus": ICON_MINUS,
        "rectangle": ICON_RECTANGLE,
        "freeform": ICON_FREEFORM,
        "text": ICON_TEXT,
        "translate": ICON_TRANSLATE,
        "clipboard": ICON_CLIPBOARD,
        "search": ICON_SEARCH,
        "app": ICON_APP,
        "file": ICON_FILE,
        "calc": ICON_CALC,
        "copy": ICON_COPY,
        "trash": ICON_TRASH,
        "network": ICON_NETWORK,
        "room": ICON_ROOM,
        "check": ICON_CHECK,
        "timer": ICON_TIMER,
        "rotate_ccw": ICON_ROTATE_CCW,
        "pause": ICON_PAUSE,
        "play": ICON_PLAY,
        "music": ICON_MUSIC,
        "prev": ICON_PREV,
        "next": ICON_NEXT,
        "stop": ICON_STOP,
        "record": ICON_RECORD,
    }
    return icons.get(name)
