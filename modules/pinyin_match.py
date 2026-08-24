# -*- coding: utf-8 -*-
"""Fuzzy / pinyin-aware matching for CapRise search.

Lets a query like "weix" match the Chinese name "微信" through its full pinyin
("weixin") — and "wx" match it through the initials. Conversion results are
cached so the one-time cost of pypinyin's dictionary load + conversion is paid
once instead of on every keystroke. pypinyin is imported lazily; if it is ever
missing the module degrades to plain substring matching."""
import re
import threading

try:
    from pypinyin import Style, lazy_pinyin
    _HAVE_PYPINYIN = True
except Exception:  # pragma: no cover - dependency missing
    _HAVE_PYPINYIN = False

_ZH = re.compile(r"[\u4e00-\u9fff]")

# text -> (full_pinyin_no_space, initials)
_CACHE = {}
_LOCK = threading.Lock()


def has_chinese(text):
    """True when `text` contains any CJK Unified Ideograph."""
    return bool(_ZH.search(text or ""))


def _compute(text):
    """Convert `text` to (full pinyin without spaces, initials)."""
    if not _HAVE_PYPINYIN:
        return "", ""
    full = "".join(lazy_pinyin(text, style=Style.NORMAL))
    init = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER))
    return full, init


def pinyin_forms(text):
    """Return the cached (full_pinyin, initials) pair for `text`."""
    text = text or ""
    with _LOCK:
        cached = _CACHE.get(text)
    if cached:
        return cached
    forms = _compute(text)
    with _LOCK:
        _CACHE[text] = forms
    return forms


def warm(text):
    """Pre-warm the cache for `text`. Cheap to call from the background index
    thread so the first real keystroke never pays a conversion cost."""
    if text and has_chinese(text):
        pinyin_forms(text)


def fuzzy_match(query, name):
    """True when `query` (any case) fuzzy-matches `name`.

    Matching order: a plain substring of the raw name (covers direct Chinese
    matches and exact English fragments), then a substring of the full pinyin
    ("weix" inside "weixin"), then a substring of the initials ("wx"). Pure-
    ASCII names skip pinyin entirely since it would just echo the name itself.
    """
    q = (query or "").lower().strip()
    if not q:
        return False
    if q in (name or "").lower():
        return True
    if not has_chinese(name):
        return False  # nothing extra to gain for a pure-ASCII name
    full, init = pinyin_forms(name)
    return q in full or q in init