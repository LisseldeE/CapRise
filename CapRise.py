"""
CapRise - PySide6 quick tool launcher
Main entry point: Ctrl+` to call, capsule UI with multiple tools
"""
import sys
import os
import ctypes
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtCore import Qt
from modules.config import Config
from modules.i18n import I18n
from modules.hotkey import HotkeyManager, HOTKEY_SPECS, qkeysequence_to_win
from modules.capsule import CapsuleBar
from modules.screenshot import ScreenshotOverlay
from modules.annotation import AnnotationOverlay
from modules.translate import TranslateOverlay
from modules.settings import SettingsDialog, apply_autostart
from modules.clipboard_manager import ClipboardManager
from modules.search import SearchWindow


def set_app_user_model_id():
    """Set the Windows AppUserModelID so the taskbar groups the window with`
    the tray icon under CapRise instead of the generic python icon.

    Must run before the QApplication (i.e. before any window) is created,
    mirroring icon_set.md. Safe no-op on non-Windows / when it fails."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "LisseldeE.CapRise.Version")
    except Exception:
        pass


def load_app_icon():
    """Load icon.ico from the app directory.

    Handles both dev (python CapRise.py) and PyInstaller onefile builds.
    In a onefile build, sys._MEIPASS points to the temp extraction directory
    where --add-data placed icon.ico. In dev mode, __file__'s directory is
    the project root. Fall back to the exe directory as a last resort."""
    icon_path = None
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        icon_path = os.path.join(sys._MEIPASS, "icon.ico")
    if not icon_path or not os.path.exists(icon_path):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    if not os.path.exists(icon_path):
        icon_path = os.path.join(os.path.dirname(sys.executable), "icon.ico")
    if os.path.exists(icon_path):
        return QIcon(icon_path)
    return QIcon()


class CapRiseApp:
    """Main application managing tray, hotkey, capsule, and overlays"""

    def __init__(self):
        # Set the AppUserModelID before any window / QApplication exists so
        # the taskbar shows the CapRise icon. Mirrors icon_set.md.
        set_app_user_model_id()

        # Record app name / version / own exe location into config.json so
        # the installer's update flow can find and replace the running exe.
        # Mirrors LANSyncBox's startup logic.
        if Config.ENABLE_CHECK_UPDATE:
            try:
                if "__compiled__" in globals():
                    # Nuitka build: the exe sits next to the compiled module.
                    exe_path = os.path.join(
                        __compiled__.containing_dir,
                        Config.APP_NAME + ".exe")
                elif getattr(sys, "frozen", False):
                    # PyInstaller build: sys.executable is the exe itself.
                    exe_path = sys.executable
                else:
                    # Dev run: the main script itself.
                    exe_path = os.path.abspath(__file__)
                Config().update_reference_info(exe_path)
            except Exception:
                pass  # Never block startup on a config write failure.

        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("CapRise")
        self.app.setWindowIcon(load_app_icon())

        Config()
        I18n.get_language()

        # Apply auto-start setting from config to registry
        apply_autostart(Config().get("autostart", False))

        self.capsule = CapsuleBar()
        self.active_overlay = None
        # Search card instance; created lazily on first entry to search mode
        # and destroyed when it closes (closed -> _on_search_closed).
        # _pending_search: re-entry requested while a card is mid-close;
        # the new card is opened only after the old one fully closes, so
        # two cards can never stack on screen.
        self._search_window = None
        self._pending_search = False

        # Clipboard manager wires itself to the capsule + panel and restores
        # persisted state (enabled / expanded / room / position) from config.
        # Created before connect_signals so the button wiring can reference it.
        self.clipboard_mgr = ClipboardManager(self.capsule)

        self.setup_tray()
        self.setup_hotkey()
        self.connect_signals()

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon()
        self.tray_icon.setIcon(load_app_icon())
        self.tray_icon.setToolTip("CapRise")

        menu = QMenu()
        show_action = menu.addAction(I18n.tr("show"))
        show_action.triggered.connect(self.toggle_capsule)
        menu.addSeparator()
        exit_action = menu.addAction(I18n.tr("exit"))
        exit_action.triggered.connect(self.exit_app)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def setup_hotkey(self):
        """Build the hotkey manager and register every configured global
        hotkey. Settings may later re-register them live through the same
        manager."""
        self.hotkey_mgr = HotkeyManager(self._on_hotkey_fired)
        # Pair callbacks with specs by config key so the ids in HOTKEY_SPECS
        # stay the single source of truth.
        callbacks = {
            "hotkey_capsule": self.toggle_capsule,
            "hotkey_screenshot": self._on_screenshot,
            "hotkey_annotation": self._on_annotation,
            "hotkey_translate": self._on_translate,
            "hotkey_clipboard": self.clipboard_mgr.on_button_left,
            "hotkey_search": self._on_search,
            "hotkey_settings": self._on_settings,
        }
        self._hotkey_callbacks = {}
        for hotkey_id, cfg_key, _label, default_seq in HOTKEY_SPECS:
            self._hotkey_callbacks[hotkey_id] = callbacks.get(cfg_key)
            seq_text = Config().get(cfg_key, default_seq)
            if not seq_text:
                self.hotkey_mgr.register(hotkey_id, 0, 0)
                continue
            qseq = QKeySequence.fromString(seq_text, QKeySequence.PortableText)
            mod, vk = qkeysequence_to_win(qseq)
            if vk == 0:
                continue
            if not self.hotkey_mgr.register(hotkey_id, mod, vk):
                print(f"Warning: hotkey {seq_text} unavailable (already in use)")

    def _on_hotkey_fired(self, hotkey_id):
        callback = self._hotkey_callbacks.get(hotkey_id)
        if callback is not None:
            callback()

    def connect_signals(self):
        self.capsule.btn_screenshot.clicked.connect(self._on_screenshot)
        self.capsule.btn_annotation.clicked.connect(self._on_annotation)
        self.capsule.btn_translate.clicked.connect(self._on_translate)
        self.capsule.btn_settings.clicked.connect(self._on_settings)
        self.capsule.btn_close.clicked.connect(self._on_close)
        # Clipboard: left-click toggles on/off, right-click opens room config.
        self.capsule.btn_clipboard.clicked.connect(self.clipboard_mgr.on_button_left)
        self.capsule.btn_clipboard.rightClicked.connect(self.clipboard_mgr.on_button_right)
        # Search: enter/exit search mode. ESC and outside-clicks funnel through
        # hide_family_requested (capsule side) and dismiss the search card too.
        self.capsule.btn_search.clicked.connect(self._on_search)
        self.capsule.hide_family_requested.connect(self._close_search)

    def toggle_capsule(self):
        if self.active_overlay is not None:
            return
        # Search mode: the hotkey exits search and restores the capsule.
        if self._search_window is not None and self._search_window.isVisible():
            # Explicit toggle-off — cancel any queued re-entry so the card
            # doesn't unexpectedly reopen after the fade-out.
            self._pending_search = False
            self._search_window.close_search()
            return
        # When the LAN clipboard is enabled, Ctrl+` surfaces the capsule and
        # (if the user last left it expanded) the clipboard card together;
        # toggling again hides both. Family visibility is checked as a whole
        # (capsule OR panel) so a stray panel doesn't strand the family.
        if self.clipboard_mgr.is_enabled():
            if self.capsule.isVisible() or self.clipboard_mgr.is_panel_visible():
                self.clipboard_mgr.hide_family()
            else:
                self.capsule.show_capsule()
                if self.clipboard_mgr.is_expanded():
                    self.clipboard_mgr.show_card()
        else:
            self.capsule.toggle_visibility()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.toggle_capsule()
            
    def _on_screenshot(self):
        # Hide the whole family (capsule + clipboard panel) instantly so
        # neither is captured in the screenshot. hide_family_immediately
        # doesn't touch _expanded or save_state — the panel preference is
        # preserved and the family resurfaces on the next Ctrl+`.
        self.clipboard_mgr.hide_family_immediately()
        overlay = ScreenshotOverlay()
        self.active_overlay = overlay
        overlay.closed.connect(lambda o=overlay: self._on_overlay_closed(o))

    def _on_annotation(self):
        # Same rationale as _on_screenshot: don't let family UI leak into
        # the annotation overlay's screen capture.
        self.clipboard_mgr.hide_family_immediately()
        overlay = AnnotationOverlay()
        self.active_overlay = overlay
        overlay.closed.connect(lambda o=overlay: self._on_overlay_closed(o))
        overlay.finished.connect(lambda o=overlay: self._on_overlay_closed(o))

    def _on_translate(self):
        # Same rationale as _on_screenshot: hide the whole family instantly
        # so neither the capsule nor the clipboard card leaks into the
        # translated selection.
        self.clipboard_mgr.hide_family_immediately()
        overlay = TranslateOverlay()
        self.active_overlay = overlay
        overlay.closed.connect(lambda o=overlay: self._on_overlay_closed(o))

    def _on_search(self):
        """Enter search mode: hide the capsule family, surface the search card.

        The card takes keyboard focus (unlike the capsule/panel which float
        passively), so the user can type immediately. Closing the card
        (ESC / outside-click / Enter on an action) emits `closed`; the
        family stays hidden (like the annotation overlay) — the user
        summons it again via Ctrl+`.

        Re-entry is guarded against stacking: a previous card may still be
        mid-close (fade-out runs for ~300ms plus a 400ms safety net). If we
        created a brand-new card right away, both would be on screen and the
        new one would "expand below" the old. Instead, when a card is still
        closing we remember the re-entry and open the new card only after
        the old one has fully closed (`_on_search_closed`). A card that is
        already up (e.g. a double-click) is simply kept."""
        if self._search_window is not None:
            if self._search_window.is_closing:
                self._pending_search = True
            # else: card already on screen — no-op (no stacking).
            return
        self._open_search()

    def _open_search(self):
        """Create and show a fresh search card (re-entry queued until the
        previous card is fully gone)."""
        self._pending_search = False
        self.clipboard_mgr.hide_family()
        window = SearchWindow()
        self._search_window = window
        # Reference-safe: only clear the ref if it still points at THIS
        # window — a stale window's late `closed` can't null a newer card.
        window.closed.connect(lambda w=window: self._on_search_closed(w))
        window.open_app_settings.connect(self._on_open_app_settings)
        window.show_search()

    def _close_search(self):
        """Dismiss the search card when the family hides (ESC / outside-click).

        The card's `closed` signal then fires _on_search_closed. Exiting
        search behaves like the annotation overlay: the family stays hidden
        (the capsule is NOT restored) — the user summons it again via Ctrl+`.
        A queued re-entry is cancelled: ESC/outside-click is an explicit
        "leave search" intent that overrides a pending re-open."""
        self._pending_search = False
        if self._search_window is not None:
            self._search_window.close_search()

    def _on_search_closed(self, window):
        """Search card fully closed -> drop the reference (no capsule restore)."""
        if self._search_window is window:
            self._search_window = None
            # A re-entry was requested while this card was still closing —
            # open the new card now that no card is on screen.
            if self._pending_search:
                self._open_search()

    def _on_settings(self):
        dialog = SettingsDialog(capsule=self.capsule, hotkey_mgr=self.hotkey_mgr)
        dialog.exec()

    def _on_open_app_settings(self, page):
        """A search result asked to open CapRise's settings on a specific
        page (e.g. "hotkey") — open the dialog on that sidebar page."""
        dialog = SettingsDialog(capsule=self.capsule, hotkey_mgr=self.hotkey_mgr,
                                initial_page=page)
        dialog.exec()

    def _on_overlay_closed(self, overlay):
        if self.active_overlay is overlay:
            self.active_overlay = None

    def _on_close(self):
        # Close dismisses the whole family (capsule + clipboard card).
        # force_family_hide bypasses the show-debounce — user-explicit action.
        self.capsule.force_family_hide()

    def exit_app(self):
        # Uninstall the mouse hook first so no callback fires while we
        # tear down the rest of the family.
        self.capsule.shutdown()
        self.clipboard_mgr.shutdown()
        self.hotkey_mgr.shutdown()
        self.app.quit()

    def run(self):
        return self.app.exec()


if __name__ == "__main__":
    app = CapRiseApp()
    sys.exit(app.run())
