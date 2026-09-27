"""
全局鼠标钩子
低层鼠标钩子，用于检测点击外部以隐藏胶囊
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import ctypes
from ctypes import wintypes, CFUNCTYPE

from PySide6.QtWidgets import QApplication

# Windows constants
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207

_user32 = ctypes.windll.user32

# Low-level hook callback signature:
#   LRESULT CALLBACK HookProc(int nCode, WPARAM wParam, LPARAM lParam)
# lParam is a pointer to MSLLHOOKSTRUCT.
_HOOKPROC = CFUNCTYPE(
    ctypes.c_long,    # LRESULT
    ctypes.c_int,     # int nCode
    ctypes.c_uint,    # WPARAM wParam
    ctypes.c_void_p,  # LPARAM lParam (pointer to MSLLHOOKSTRUCT)
)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


# Configure signatures once.
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
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL


# Mouse-down messages we care about (set for O(1) lookup).
_DOWN_MESSAGES = {WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN}


class GlobalMouseHook:
    """Low-level mouse hook that fires `on_outside_click` when a mouse
    button is pressed anywhere on screen AND the click position is not
    inside any family window.

    The capsule constructs one of these once and assigns a callback to
    `on_outside_click`. The callback is invoked synchronously on the Qt
    main thread, so it can emit Qt signals directly.
    """

    def __init__(self):
        self._hook = None
        # Strong reference to the CFUNCTYPE instance — without this, the
        # GC reclaims the callback and Windows crashes on the next event.
        self._proc = _HOOKPROC(self._hook_proc)
        # Set by the capsule. Called synchronously when a click lands
        # outside the family (and no modal dialog is up).
        self.on_outside_click = None

    def install(self):
        """Install the hook on the calling (Qt main) thread.

        ThreadId 0 means "current thread" — Windows then invokes the hook
        while this thread pumps messages, which QApplication.exec() does.
        """
        if self._hook is not None:
            return
        # hMod = None is valid for WH_MOUSE_LL (it doesn't require a DLL).
        self._hook = _user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)

    def uninstall(self):
        if self._hook is not None:
            _user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _hook_proc(self, nCode, wParam, lParam):
        # Always call next hook first-in-result-order; we never swallow
        # the click (the target window must still receive it).
        result = _user32.CallNextHookEx(self._hook, nCode, wParam, lParam)
        if nCode != HC_ACTION or self.on_outside_click is None:
            return result
        if wParam not in _DOWN_MESSAGES:
            return result
        try:
            # Modal dialog up? Let Windows handle outside clicks itself
            # (deny sound + flash). Hiding the family mid-modal would
            # strand the dialog. This check is main-thread-safe because
            # the hook runs on the Qt main thread.
            if QApplication.activeModalWidget() is not None:
                return result
            # Late import to avoid a circular import at module load time
            # (family.py doesn't import this module, but keep it lazy).
            from modules.family import FamilyWindowRegistry
            mouse = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            pt = (mouse.pt.x, mouse.pt.y)
            if not FamilyWindowRegistry.is_point_in_family(pt):
                # Synchronous: runs on the Qt main thread, so emitting a
                # Qt signal here is safe. The capsule's handler also
                # checks family visibility before emitting, so spurious
                # calls (e.g. before any family window is shown) no-op.
                self.on_outside_click()
        except Exception:
            # NEVER let a Python exception escape the hook — Windows
            # would silently remove the hook and we'd lose the feature
            # with no obvious error.
            pass
        return result
