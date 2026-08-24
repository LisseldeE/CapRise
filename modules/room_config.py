"""Room configuration dialog with a 6-digit code input.

The 6-cell input widget (auto-advance, backspace-to-previous, paste-6-digits)
is adapted from the sibling LANSyncBox project per the PRD. The dialog is a
"family window" so opening it does NOT make the capsule收起.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QWidget, QApplication
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QValidator, QKeyEvent

from modules.i18n import I18n
from modules.family import FamilyWindowRegistry


class DigitValidator(QValidator):
    """Allow only a single digit (or empty)."""

    def validate(self, text, pos):
        if text == "" or (len(text) == 1 and text.isdigit()):
            return QValidator.Acceptable, text, pos
        return QValidator.Invalid, text, pos


class DigitLineEdit(QLineEdit):
    """Single-digit input that signals backspace (when empty) and paste."""

    backspace_pressed = Signal()
    paste_requested = Signal(str)

    def keyPressEvent(self, event: QKeyEvent):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_V:
            self.paste_requested.emit(QApplication.clipboard().text())
            return
        if event.key() == Qt.Key_Backspace:
            if not self.text():
                self.backspace_pressed.emit()
                return
            super().keyPressEvent(event)
            return
        # Reject multi-char / non-digit paste via direct input
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        # Suppress the default context menu (keeps the 6-cell UX clean).
        pass


class RoomCodeInput(QWidget):
    """6-cell room-code input. Matches LANSyncBox's input + delete logic."""

    code_completed = Signal()
    code_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.digit_edits = []
        self._last_complete = False
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        font = QFont()
        font.setPointSize(20)
        font.setBold(True)

        for i in range(6):
            edit = DigitLineEdit()
            edit.setAlignment(Qt.AlignCenter)
            edit.setMaxLength(1)
            edit.setFixedSize(44, 54)
            edit.setFont(font)
            edit.setValidator(DigitValidator())
            edit.setStyleSheet("""
                QLineEdit {
                    font-size: 26px;
                    font-weight: bold;
                    background-color: palette(base);
                    border: 2px solid palette(mid);
                    border-radius: 8px;
                    color: palette(text);
                }
                QLineEdit:focus {
                    border: 2px solid #339af0;
                }
            """)
            edit.textChanged.connect(lambda text, idx=i: self._on_text_changed(text, idx))
            edit.backspace_pressed.connect(lambda idx=i: self._on_backspace(idx))
            if i == 0:
                edit.paste_requested.connect(self._on_paste)
            self.digit_edits.append(edit)
            layout.addWidget(edit)

    def _on_text_changed(self, text, index):
        if text and index < 5:
            self.digit_edits[index + 1].setFocus()
        self.code_changed.emit()
        complete = self.is_complete()
        if complete and not self._last_complete:
            self.code_completed.emit()
        self._last_complete = complete

    def _on_backspace(self, index):
        # Delete logic (matches LANSyncBox): empty cell -> jump back & clear.
        if index > 0:
            prev = self.digit_edits[index - 1]
            prev.clear()
            prev.setFocus()

    def _on_paste(self, text):
        text = (text or "").strip()
        if len(text) == 6 and text.isdigit():
            self.blockSignals(True)
            for i, ch in enumerate(text):
                self.digit_edits[i].setText(ch)
            self.blockSignals(False)
            self._last_complete = True
            self.code_changed.emit()
            self.code_completed.emit()
            self.digit_edits[5].setFocus()

    def set_room_code(self, code, trigger_check=True):
        code = (code or "").zfill(6)[:6]
        self.blockSignals(True)
        for i, ch in enumerate(code):
            self.digit_edits[i].setText(ch if ch.isdigit() else "")
        self.blockSignals(False)
        self._last_complete = self.is_complete()
        self.code_changed.emit()
        if self._last_complete and trigger_check:
            self.code_completed.emit()

    def get_room_code(self):
        return "".join(e.text() for e in self.digit_edits)

    def is_complete(self):
        return all(e.text().isdigit() for e in self.digit_edits)

    def clear(self):
        self.blockSignals(True)
        for e in self.digit_edits:
            e.clear()
        self.blockSignals(False)
        self._last_complete = False
        self.digit_edits[0].setFocus()
        self.code_changed.emit()

    def set_focus(self):
        self.digit_edits[0].setFocus()


class RoomConfigDialog(QDialog):
    """Modal dialog to enter/change the 6-digit room code."""

    def __init__(self, initial_code="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(I18n.tr("clipboard_room_config_title"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setModal(True)
        self.setFixedSize(360, 220)
        # Whether a room was pre-filled (existing room -> focus the last
        # digit on show; new room -> focus the first empty cell).
        self._room_prefilled = bool(initial_code)
        self._init_ui(initial_code)

    def _init_ui(self, initial_code):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel(I18n.tr("clipboard_room_label"))
        title.setStyleSheet("font-size: 14px; font-weight: 600; color: palette(text);")
        layout.addWidget(title)

        self.input = RoomCodeInput()
        if initial_code:
            self.input.set_room_code(initial_code, trigger_check=False)
        layout.addWidget(self.input)

        self.hint = QLabel(I18n.tr("clipboard_room_hint"))
        self.hint.setStyleSheet("color: palette(placeholder-text); font-size: 12px;")
        layout.addWidget(self.hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton(I18n.tr("close"))
        self.btn_cancel.setFixedSize(90, 32)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                border: 1px solid palette(mid); border-radius: 6px;
                padding: 4px 14px; font-size: 13px;
            }
            QPushButton:hover { background-color: palette(light); }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_confirm = QPushButton(I18n.tr("save"))
        self.btn_confirm.setFixedSize(90, 32)
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.setStyleSheet("""
            QPushButton {
                background-color: #339af0; color: white; border: none;
                border-radius: 6px; padding: 4px 14px; font-size: 13px;
            }
            QPushButton:hover { background-color: #228be6; }
            QPushButton:disabled { background-color: palette(mid); color: palette(placeholder-text); }
        """)
        self.btn_confirm.clicked.connect(self._on_confirm)
        btn_row.addWidget(self.btn_confirm)
        layout.addLayout(btn_row)

        self.input.code_changed.connect(
            lambda: self.btn_confirm.setEnabled(self.input.is_complete())
        )
        self.input.code_completed.connect(lambda: self.btn_confirm.setFocus())
        # Pre-fill complete -> enable
        if self.input.is_complete():
            self.btn_confirm.setEnabled(True)

    def _on_confirm(self):
        if not self.input.is_complete():
            self.hint.setText(I18n.tr("clipboard_room_invalid"))
            self.hint.setStyleSheet("color: #e03131; font-size: 12px;")
            return
        self.accept()

    def get_room_code(self):
        return self.input.get_room_code()

    def showEvent(self, event):
        super().showEvent(event)
        FamilyWindowRegistry.add(self)
        FamilyWindowRegistry.refresh_hwnd(self)
        # Grab keyboard focus so the user can type the code immediately
        # without a mouse click. The delayed call lets the modal dialog
        # finish hoisting to the foreground before activating.
        self.raise_()
        QTimer.singleShot(80, self._grab_focus)

    def _grab_focus(self):
        if not self.isVisible() or not self.isEnabled():
            return
        self.activateWindow()
        # Editing an existing room -> place the caret on the last digit so
        # the user can adjust the tail immediately; entering a new room ->
        # focus the first empty cell.
        if self._room_prefilled and self.input.is_complete():
            self.input.digit_edits[-1].setFocus()
        else:
            self.input.set_focus()

    def closeEvent(self, event):
        FamilyWindowRegistry.remove(self)
        super().closeEvent(event)