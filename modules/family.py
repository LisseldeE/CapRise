"""
家族窗口
家族窗口注册表，避免扩展窗口触发胶囊收起
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import weakref


class FamilyWindowRegistry:
    """Process-wide registry of family windows (capsule + its extensions)."""

    _widgets = weakref.WeakSet()
    _hwnds = set()

    @classmethod
    def add(cls, widget):
        """Register a widget as a family window. Safe to call repeatedly."""
        cls._widgets.add(widget)
        cls._record_hwnd(widget)

    @classmethod
    def remove(cls, widget):
        """Unregister a widget. Safe to call when not registered."""
        cls._widgets.discard(widget)
        try:
            cls._hwnds.discard(int(widget.winId()))
        except Exception:
            pass

    @classmethod
    def refresh_hwnd(cls, widget):
        """Re-read widget's HWND.

        Call after the widget's native handle has been created (e.g. in the
        first showEvent) — winId() can change across hide/show cycles.
        """
        if widget in cls._widgets:
            cls._record_hwnd(widget)

    @classmethod
    def is_family_hwnd(cls, hwnd):
        """True if the given Windows HWND belongs to a family window."""
        try:
            return int(hwnd) in cls._hwnds
        except (TypeError, ValueError):
            return False

    @classmethod
    def is_family_widget(cls, widget):
        """True if widget is a family window or a descendant of one.

        Used by the capsule's global event filter to ignore mouse presses
        that land on a family window (so clicking the panel doesn't收起).
        """
        w = widget
        while w is not None:
            if w in cls._widgets:
                return True
            w = w.parent()
        return False

    @classmethod
    def any_visible(cls):
        """True if any family window is currently visible.

        Drives the family-aware focus poll: as long as any family member
        (capsule / clipboard panel / room dialog) is on screen, the poll
        keeps running; once all are hidden the poll early-returns.
        Iteration is guarded against destroyed widgets (WeakSet may still
        hold dead refs until GC).
        """
        for w in list(cls._widgets):
            try:
                if w.isVisible():
                    return True
            except RuntimeError:
                # widget already deleted — drop the stale ref
                cls._widgets.discard(w)
        return False

    @classmethod
    def is_point_in_family(cls, pt):
        """True if a screen-space point (x, y) lies inside any family
        window's HWND rect.

        Uses Win32 GetWindowRect on every recorded HWND — this is the
        source of truth for "did the click land on a CapRise window?",
        because it accounts for the actual on-screen geometry of our
        frameless Qt.Tool windows (Qt's geometry() can disagree with
        the OS for WA_TranslucentBackground windows).

        Stale HWNDs are tolerated: GetWindowRect returns False for
        invalid HWNDs and we just skip them. _hwnds is a snapshot copy
        so a widget being unregistered mid-iteration can't corrupt the
        loop.
        """
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetWindowRect.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.RECT)
        ]
        user32.GetWindowRect.restype = wintypes.BOOL
        for hwnd in list(cls._hwnds):
            try:
                rect = wintypes.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    if rect.left <= pt[0] < rect.right and \
                       rect.top <= pt[1] < rect.bottom:
                        return True
            except Exception:
                pass
        return False

    @classmethod
    def _record_hwnd(cls, widget):
        try:
            hwnd = int(widget.winId())
            if hwnd:
                cls._hwnds.add(hwnd)
        except Exception:
            pass

    @staticmethod
    def set_no_activate(widget):
        """Apply WS_EX_NOACTIVATE so the window never steals keyboard focus
        (neither on show nor on mouse click). Combined with Qt's
        WA_ShowWithoutActivating this lets the capsule/panel float above the
        user's input field WITHOUT disrupting the caret — clicking a clipboard
        item copies and the user can Ctrl+V straight into the original input.
        Must be called after the native HWND exists (i.e. in/after showEvent).
        """
        try:
            import ctypes
            hwnd = int(widget.winId())
            if not hwnd:
                return
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            user32 = ctypes.windll.user32
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if not (ex & WS_EX_NOACTIVATE):
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE)
        except Exception:
            pass
