"""Global hotkey management for CapRise.

Multiple Win32 global hotkeys (RegisterHotKey) are managed by id. Qt key
sequences entered in the settings page are converted to Win32 MOD_*/VK_*
values, and every WM_HOTKEY message is dispatched to the callback bound to
its hotkey id.

Hotkey values are persisted in config.json as portable QKeySequence text
(e.g. "Ctrl+`"); an empty string means "no hotkey".
"""
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QAbstractNativeEventFilter, Qt
from PySide6.QtGui import QKeySequence

user32 = ctypes.windll.user32

# Win32 modifier / message constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

# Qt::Key enum bounds for the printable / function-key ranges.
KEY_PRINTABLE_MAX = 0x01000000
QT_F1 = Qt.Key_F1
QT_F24 = Qt.Key_F24
VK_F1 = 0x70

# Qt key codes (modifier bits stripped) that do not map to their ASCII value.
_QT_TO_VK = {
    Qt.Key_Escape: 0x1B,
    Qt.Key_Tab: 0x09,
    Qt.Key_Backtab: 0x09,
    Qt.Key_Backspace: 0x08,
    Qt.Key_Return: 0x0D,
    Qt.Key_Enter: 0x0D,
    Qt.Key_Insert: 0x2D,
    Qt.Key_Delete: 0x2E,
    Qt.Key_Pause: 0x13,
    Qt.Key_Print: 0x2C,
    Qt.Key_Home: 0x24,
    Qt.Key_End: 0x23,
    Qt.Key_Left: 0x25,
    Qt.Key_Up: 0x26,
    Qt.Key_Right: 0x27,
    Qt.Key_Down: 0x28,
    Qt.Key_PageUp: 0x21,
    Qt.Key_PageDown: 0x22,
    # OEM punctuation keys (printable but not equal to their VK code).
    0x60: 0xC0,                 # ` (VK_OEM_3)
    ord('-'): 0xBD, ord('='): 0xBB,
    ord('['): 0xDB, ord(']'): 0xDD, ord('\\'): 0xDC,
    ord(';'): 0xBA, ord("'"): 0xDE,
    ord(','): 0xBC, ord('.'): 0xBE, ord('/'): 0xBF,
    # Shifted symbols: Qt reports the shifted character code (e.g. '!'=0x21)
    # even though the physical key is the unshifted one, so map them back to
    # the base VK (the Shift modifier is carried separately by the sequence).
    ord('~'): 0xC0,             # Shift+`
    ord('!'): 0x31, ord('@'): 0x32, ord('#'): 0x33, ord('$'): 0x34,
    ord('%'): 0x35, ord('^'): 0x36, ord('&'): 0x37, ord('*'): 0x38,
    ord('('): 0x39, ord(')'): 0x30,
    ord('_'): 0xBD, ord('+'): 0xBB,
    ord('{'): 0xDB, ord('}'): 0xDD, ord('|'): 0xDC,
    ord(':'): 0xBA, ord('"'): 0xDE,
    ord('<'): 0xBC, ord('>'): 0xBE, ord('?'): 0xBF,
}


def qkey_to_vk(qt_key):
    """Map a Qt key code (modifier bits stripped) to a Win32 VK code."""
    if qt_key in _QT_TO_VK:
        return _QT_TO_VK[qt_key]
    if QT_F1 <= qt_key <= QT_F24:
        return VK_F1 + (qt_key - QT_F1)
    if qt_key < KEY_PRINTABLE_MAX:  # printable ASCII maps to its own VK
        return qt_key
    return 0


def qkeysequence_to_win(qseq):
    """Convert a QKeySequence to a (mod, vk) pair for RegisterHotKey.

    Returns (0, 0) when the sequence is empty (meaning "no hotkey")."""
    if qseq is None or qseq.isEmpty():
        return 0, 0
    combo = qseq[0]  # PySide6 returns a QKeyCombination
    mods = combo.keyboardModifiers()
    mod = 0
    if mods & Qt.ControlModifier:
        mod |= MOD_CONTROL
    if mods & Qt.AltModifier:
        mod |= MOD_ALT
    if mods & Qt.ShiftModifier:
        mod |= MOD_SHIFT
    if mods & Qt.MetaModifier:
        mod |= MOD_WIN
    vk = qkey_to_vk(int(combo.key()))
    return mod, vk


def is_valid_hotkey(mod, vk):
    """A hotkey needs at least one modifier, unless it is a bare F-key.

    A combination is valid when it has a real key; (0, 0) means "cleared".
    A non-zero modifier with vk == 0 (a bare modifier, e.g. QKeySequenceEdit
    committing "Ctrl" alone after a long press) is invalid — it must never be
    mistaken for "cleared", otherwise a hotkey being edited would be wiped."""
    if vk == 0:
        return mod == 0  # only a truly empty sequence counts as cleared
    if mod != 0:
        return True
    return VK_F1 <= vk <= VK_F1 + (QT_F24 - QT_F1)


# --- hotkey registry: (hotkey_id, config_key, i18n_label_key, default_seq) ---
HOTKEY_SPECS = [
    (1, "hotkey_capsule", "hotkey_capsule", "Ctrl+`"),
    (2, "hotkey_screenshot", "screenshot", ""),
    (3, "hotkey_annotation", "annotation", ""),
    (4, "hotkey_translate", "translate", ""),
    (5, "hotkey_clipboard", "clipboard", ""),
    (6, "hotkey_search", "search", ""),
    (7, "hotkey_settings", "settings", ""),
    (8, "hotkey_picker", "color_picker", ""),
]


class WinHotkeyFilter(QAbstractNativeEventFilter):
    """Native event filter that forwards WM_HOTKEY with its hotkey id."""

    def __init__(self, on_hotkey):
        super().__init__()
        self.on_hotkey = on_hotkey

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message.__int__()))
            if msg.message == WM_HOTKEY:
                self.on_hotkey(int(msg.wParam) & 0xFFFF)
                return True, 0
        return False, 0


class HotkeyManager:
    """Registers / unregisters multiple Win32 global hotkeys by id.

    register() is transactional: when the combination is unavailable (already
    used by another app, or by another of our own hotkeys) the previous
    binding is restored and False is returned so the UI can revert."""

    def __init__(self, on_hotkey):
        self._on_hotkey = on_hotkey
        self._items = {}  # hotkey_id -> (mod, vk)
        self._filter = WinHotkeyFilter(self._dispatch)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().installNativeEventFilter(self._filter)

    def _dispatch(self, hotkey_id):
        if hotkey_id in self._items:
            self._on_hotkey(hotkey_id)

    def register(self, hotkey_id, mod, vk):
        """Bind (mod, vk) to hotkey_id, replacing any previous binding.

        Passing vk == 0 clears the hotkey. Returns True on success/clear,
        False when the combination is taken (rolled back to the old state)."""
        prev = self._items.get(hotkey_id)
        self.unregister(hotkey_id)
        if vk == 0:
            return True
        if user32.RegisterHotKey(None, hotkey_id, mod | MOD_NOREPEAT, vk):
            self._items[hotkey_id] = (mod, vk)
            return True
        # Combination unavailable: restore the previous binding if any.
        if prev is not None:
            user32.RegisterHotKey(None, hotkey_id, prev[0] | MOD_NOREPEAT, prev[1])
            self._items[hotkey_id] = prev
        return False

    def unregister(self, hotkey_id):
        if hotkey_id in self._items:
            user32.UnregisterHotKey(None, hotkey_id)
            del self._items[hotkey_id]

    def shutdown(self):
        for hotkey_id in list(self._items):
            self.unregister(hotkey_id)
