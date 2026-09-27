"""
剪贴板监控
监控系统剪贴板并做回声防护，避免同步循环
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal


class ClipboardMonitor(QObject):
    """Monitors the system clipboard; emits only on genuine local copies."""

    copied = Signal(str)  # text the user copied locally (echo-guarded)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._clip = QApplication.clipboard()
        self._suppress = False   # True while we are writing the clipboard ourselves
        self._enabled = False
        # Last text we emitted (or set remotely). Burst writes (some apps fire
        # dataChanged several times for text/html/inline variants of one copy)
        # are collapsed by comparing against this — instant, no timer latency.
        self._last_text = None

    def enable(self):
        if self._enabled:
            return
        self._enabled = True
        self._clip.dataChanged.connect(self._on_changed)

    def disable(self):
        if not self._enabled:
            return
        self._enabled = False
        try:
            self._clip.dataChanged.disconnect(self._on_changed)
        except (TypeError, RuntimeError):
            pass

    def set_clipboard(self, text):
        """Write text to the system clipboard WITHOUT re-emitting it as local.
        Also records it as the last text so a subsequent identical local copy
        (echo) doesn't re-emit / re-broadcast."""
        if not isinstance(text, str) or text == "":
            return
        self._suppress = True
        self._last_text = text
        self._clip.setText(text)
        # If setText fired dataChanged synchronously, the handler already
        # cleared _suppress. If the content was identical (no signal fired),
        # clear it manually so a subsequent real copy isn't swallowed.
        if self._suppress:
            self._suppress = False

    def _on_changed(self):
        if self._suppress:
            self._suppress = False
            return
        if not self._enabled:
            return
        text = self._clip.text()
        if not text or text == self._last_text:
            return
        self._last_text = text
        self.copied.emit(text)
