"""Global low-level ESC hook (WH_KEYBOARD_LL) for the main capsule bar.

The capsule bar must stay non-activating (WS_EX_NOACTIVATE +
WA_ShowWithoutActivating) so it never steals the user's caret. But that
means a global Qt nativeEventFilter ESC (CapsuleNativeFilter) only fires
while a CapRise window holds the foreground — when just the capsule bar is
up, the user's focus is still in some other app and ESC goes there instead,
so the bar never hides.

A WH_KEYBOARD_LL hook receives every key on the system *before* the target
window, regardless of focus — exactly how GlobalMouseHook already receives
every mouse-down. We mirror that pattern: on ESC keydown, if any family
window is visible (and no modal is up), collapse the whole family.
"""
import ctypes
from ctypes import wintypes, CFUNCTYPE

from PySide6.QtWidgets import QApplication

# Windows constants
WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B

_user32 = ctypes.windll.user32

# Low-level hook callback signature:
#   LRESULT CALLBACK HookProc(int nCode, WPARAM wParam, LPARAM lParam)
# lParam for WH_KEYBOARD_LL points to a KBDLLHOOKSTRUCT (vkCode first).
_HOOKPROC = CFUNCTYPE(
    ctypes.c_long,    # LRESULT
    ctypes.c_int,     # int nCode
    ctypes.c_uint,    # WPARAM wParam
    ctypes.c_void_p,  # LPARAM lParam (pointer to KBDLLHOOKSTRUCT)
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD
]
_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p
]
_user32.CallNextHookEx.restype = ctypes.c_long


class GlobalEscapeHook:
    """Low-level keyboard hook that fires `on_escape` on ESC key-down.

    The capsule installs one and assigns a callback. The callback runs
    synchronously on the install (Qt main) thread, so it can emit Qt
    signals directly.
    """

    def __init__(self):
        self._hook = None
        # Strong reference to the CFUNCTYPE instance — otherwise the GC
        # reclaims the callback and Windows crashes on the next event.
        self._proc = _HOOKPROC(self._hook_proc)
        # Set by the capsule. Called on ESC key-down while a family window
        # is visible and no modal is up.
        self.on_escape = None

    def install(self):
        if self._hook is not None:
            return
        self._hook = _user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, None, 0)

    def uninstall(self):
        if self._hook is not None:
            _user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _hook_proc(self, nCode, wParam, lParam):
        result = _user32.CallNextHookEx(self._hook, nCode, wParam, lParam)
        if nCode != HC_ACTION or wParam != WM_KEYDOWN:
            return result
        if self.on_escape is None:
            return result
        try:
            kbd = ctypes.cast(
                lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if kbd.vkCode != VK_ESCAPE:
                return result
            # A modal family dialog (e.g. room config) owns ESC already;
            # don't collapse the family out from under it.
            if QApplication.activeModalWidget() is not None:
                return result
            # Synchronous: runs on the Qt main thread, so emitting here is
            # safe. The capsule handler also re-checks family visibility.
            self.on_escape()
        except Exception:
            # NEVER let a Python exception escape the hook — Windows would
            # silently remove it and we'd lose the feature silently.
            pass
        return result