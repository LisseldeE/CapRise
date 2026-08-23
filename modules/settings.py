"""Settings dialog for CapRise.

Split-pane layout: a left navigation column lets the user switch between the
General / Translate / System / About sub-cards, and the right pane shows the
settings for the selected section (task 4). The About page also carries the
check-for-update logic (task 5)."""
import sys
import os
import winreg
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox,
    QListWidget, QListWidgetItem, QStackedWidget, QWidget, QFrame,
    QApplication, QGraphicsOpacityEffect, QAbstractItemView, QKeySequenceEdit,
    QPushButton
)
from PySide6.QtCore import (
    Qt, QSize, QByteArray, QRectF, QPropertyAnimation, QEasingCurve, Signal,
    QMimeData, QPoint, QTimer
)
from PySide6.QtGui import (
    QGuiApplication, QPalette, QPixmap, QPainter, QColor, QDrag, QKeySequence,
    QIcon
)
from PySide6.QtSvg import QSvgRenderer
from modules.config import Config
from modules.i18n import I18n
from modules.about import AboutPage
from modules.hotkey import HOTKEY_SPECS, qkeysequence_to_win, is_valid_hotkey

# Dotted grip glyph used as the drag handle on each reorder row.
GRIP_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <circle cx="9"  cy="6"  r="1.7" fill="currentColor"/>
  <circle cx="15" cy="6"  r="1.7" fill="currentColor"/>
  <circle cx="9"  cy="12" r="1.7" fill="currentColor"/>
  <circle cx="15" cy="12" r="1.7" fill="currentColor"/>
  <circle cx="9"  cy="18" r="1.7" fill="currentColor"/>
  <circle cx="15" cy="18" r="1.7" fill="currentColor"/>
</svg>"""

# Eye glyphs for the per-row show/hide toggle: open = tool visible in the
# capsule, closed (with a slash) = tool hidden.
EYE_OPEN_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <path d="M2 12c2-4.5 6-7 10-7s8 2.5 10 7c-2 4.5-6 7-10 7s-8-2.5-10-7z"
        fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
  <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.6"/>
</svg>"""
EYE_CLOSED_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <path d="M2 12c2-4.5 6-7 10-7s8 2.5 10 7c-2 4.5-6 7-10 7s-8-2.5-10-7z"
        fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
  <line x1="4" y1="4" x2="20" y2="20" stroke="currentColor"
        stroke-width="1.6" stroke-linecap="round"/>
</svg>"""


def _get_app_cmd():
    """Command registered to HKCU Run.

    For a source launch, prefer pythonw.exe (windowless) when available so no
    black console flashes at logon alongside the app; a frozen build registers
    only the exe itself (sys.executable is already the entry point)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    if os.path.basename(exe).lower() == "python.exe":
        alt = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(alt):
            exe = alt
    return f'"{exe}" "{os.path.abspath(sys.argv[0])}"'


def apply_autostart(enabled):
    """Set or clear the auto-start registry entry for the current user.

    Returns True on success, False on failure (logged to stderr) so callers
    can surface the problem instead of it being silently swallowed."""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
            )
        except OSError:
            # Run key missing (rare) — create it so the entry can be written.
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        try:
            if enabled:
                winreg.SetValueEx(key, "CapRise", 0, winreg.REG_SZ, _get_app_cmd())
            else:
                try:
                    winreg.DeleteValue(key, "CapRise")
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Failed to set autostart: {e}")
        return False


def _accent_hex():
    c = QApplication.palette().color(QPalette.Highlight)
    return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"


def _text_hex():
    c = QApplication.palette().color(QPalette.WindowText)
    return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"


def _make_line_svg_pixmap(svg, size=14):
    """Rasterise a currentColor line SVG as a DPR-aware QPixmap.

    The colour is the window-text colour blended against the window
    background (SVG only takes RGB, so transparency is baked in that way) —
    it reads well on both light and dark themes. Both fill and stroke
    currentColor tokens are substituted."""
    base = QColor(_text_hex())
    bg = QApplication.palette().color(QPalette.Window)
    alpha = 170
    r = int((base.red() * alpha + bg.red() * (255 - alpha)) / 255)
    g = int((base.green() * alpha + bg.green() * (255 - alpha)) / 255)
    b = int((base.blue() * alpha + bg.blue() * (255 - alpha)) / 255)
    hex_color = f"#{r:02x}{g:02x}{b:02x}"
    colored = (svg
               .replace('fill="currentColor"', f'fill="{hex_color}"')
               .replace('stroke="currentColor"', f'stroke="{hex_color}"'))
    renderer = QSvgRenderer(QByteArray(colored.encode()))
    dpr = QGuiApplication.primaryScreen().devicePixelRatio() or 1.0
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    # Render into the pixmap's full logical rect. Without an explicit target
    # rect, QSvgRenderer paints the SVG at its native viewBox size (24x24),
    # which is larger than these glyph slots — the glyph then sits off-centre
    # (and slightly clipped) inside the pixmap.
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pix


def _make_grip_pixmap(size=14):
    """Dotted grip glyph for the reorder-row drag handle."""
    return _make_line_svg_pixmap(GRIP_SVG, size)


def _make_eye_pixmaps(size=14):
    """(open, closed) eye glyphs for the per-row show/hide toggle."""
    return (_make_line_svg_pixmap(EYE_OPEN_SVG, size),
            _make_line_svg_pixmap(EYE_CLOSED_SVG, size))


class _GlyphWidget(QWidget):
    """Paints a DPR-aware glyph pixmap exactly centred in its slot.

    QToolButton and QLabel both position icons through the platform style and
    the DPR icon pipeline, which leaves the glyph a pixel or two off-centre
    (and occasionally clipped at the slot edge) — QToolButton's own layout
    pushed the grip down-right in practice. Drawing the pixmap in
    paintEvent() makes the placement deterministic at every DPI: the glyph is
    always dead-centre and can never crowd or cover its neighbour."""

    def __init__(self, pix, parent=None):
        super().__init__(parent)
        self._pix = pix

    def set_pixmap(self, pix):
        """Swap the glyph (used to flip the eye open/closed)."""
        self._pix = pix
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dpr = self._pix.devicePixelRatio() or 1.0
        lw = self._pix.width() / dpr
        lh = self._pix.height() / dpr
        p.drawPixmap(int((self.width() - lw) / 2),
                     int((self.height() - lh) / 2), self._pix)
        p.end()


def _make_tool_row_widget(label_text, grip_pix, eye_pix, tooltip):
    """Per-item widget for the reorder list: label on the left, a show/hide
    eye toggle in the middle, drag-handle grip pinned to the right.

    The widget itself is mouse-transparent so every press/drag event falls
    through to the QListWidget — the grip is purely visual and dragging can
    start from anywhere on the row. Qt propagates the transparent-for-mouse
    attribute to every child, so the eye can never receive events on its own;
    the list intercepts clicks on the eye area in its mousePressEvent()
    instead. The background stays transparent so the stylesheet-driven
    hover/selection highlight shows through."""
    w = QWidget()
    w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    w.setAttribute(Qt.WA_TranslucentBackground, True)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(10, 0, 10, 0)
    lay.setSpacing(6)
    text = QLabel(label_text)
    lay.addWidget(text)
    lay.addStretch()

    # The eye toggle and the drag grip are packed into a single fixed-width
    # unit. Keeping them in their own layout guarantees they are always
    # exactly `spacing` apart — no matter how the outer row gets resized, the
    # grip can never slide over the eye button.
    side = QWidget()
    side.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    side.setAttribute(Qt.WA_TranslucentBackground, True)
    side.setFixedWidth(18 + 6 + 18)
    side.setStyleSheet("background: transparent;")
    side_lay = QHBoxLayout(side)
    side_lay.setContentsMargins(0, 0, 0, 0)
    side_lay.setSpacing(6)
    eye = _GlyphWidget(eye_pix)
    eye.setObjectName("eye_toggle")
    eye.setFixedSize(18, 18)
    eye.setToolTip(tooltip)
    side_lay.addWidget(eye)
    # The drag grip uses the same exact-centred glyph rendering as the eye,
    # so both stay perfectly centred with no style/DPR drift. It is
    # mouse-transparent (inherited), so it stays purely visual.
    grip = _GlyphWidget(grip_pix)
    grip.setObjectName("drag_grip")
    grip.setFixedSize(18, 18)
    side_lay.addWidget(grip)
    lay.addWidget(side)
    return w


class _ReorderToolList(QListWidget):
    """Tool list that can be reordered by dragging, used in the General page.

    Drag-and-drop is driven entirely by hand so the source item can never be
    lost or duplicated by Qt's internal machinery:

    - startDrag() builds a plain QDrag carrying only the source item's key
      (private MIME type) and calls drag.exec() WITHOUT super().startDrag(),
      which bypasses QAbstractItemView::clearOrRemove() — the source item
      never leaves the model mid-drag.
    - dropEvent() computes the destination from the drop indicator, then
      does exactly one takeItem()+insertItem(). Same-slot drops are no-ops.
      The very same QListWidgetItem is reused.
    - setItemWidget is backed by setIndexWidget (persistent-index bound),
      which Qt destroys on take/insert, so attach_row_widgets() rebuilds the
      row widgets (label + eye toggle + right grip) after every move.

    Each row also carries a show/hide eye toggle: clicking it flips the
    tool's visibility in the capsule (persisted via `visibility_changed`),
    without starting a drag — the eye button opts back into mouse events.

    During a drag the `dragging` dynamic property suppresses hover/selection
    backgrounds, leaving only the drop-indicator line as the positional cue.
    """
    order_changed = Signal()
    visibility_changed = Signal(str, bool)  # (tool key, now visible)
    MIME = "application/x-caprise-tool-key"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDropIndicatorShown(True)
        self._tool_labels = {}
        self._grip_pix = None
        self._eye_pix_open = None
        self._eye_pix_closed = None
        self._hidden = {}

    # ---------- row widgets (label left, eye middle, grip right) ----------
    def set_tool_labels(self, labels, grip_pix):
        """Store the key->label map and grip pixmap used to build row widgets."""
        self._tool_labels = dict(labels)
        self._grip_pix = grip_pix

    def set_eye_pixmaps(self, open_pix, closed_pix):
        """Store the open/closed eye glyphs used by the show/hide toggles."""
        self._eye_pix_open = open_pix
        self._eye_pix_closed = closed_pix

    def set_hidden_keys(self, keys):
        """Restore which tools are hidden (from config), then rebuild rows."""
        self._hidden = {k: True for k in (keys or [])}
        self.attach_row_widgets()

    def hidden_keys(self):
        """The ordered list of tool keys currently hidden."""
        return [key for key in self._hidden if self._hidden[key]]

    def attach_row_widgets(self):
        """(Re)build the per-row widget for every item.

        Must be re-run after a move: takeItem()/insertItem() trigger Qt's
        index-widget cleanup, which destroys the row widgets."""
        if self._grip_pix is None:
            return
        for i in range(self.count()):
            item = self.item(i)
            key = item.data(Qt.UserRole)
            label = self._tool_labels.get(key, key)
            hidden = self._hidden.get(key, False)
            eye_pix = self._eye_pix_closed if hidden else self._eye_pix_open
            tooltip = (I18n.tr("tool_show") if hidden
                       else I18n.tr("tool_hide"))

            self.setItemWidget(
                item, _make_tool_row_widget(label, self._grip_pix, eye_pix,
                                            tooltip))

    # ---------- show/hide toggle (clicked on the eye area) ----------
    def _toggle_tool(self, key):
        """Flip a tool's visibility, refresh its row icon and emit the signal."""
        new_hidden = not self._hidden.get(key, False)
        self._hidden[key] = new_hidden
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.UserRole) != key:
                continue
            row = self.itemWidget(item)
            if row is not None:
                eye = row.findChild(_GlyphWidget, "eye_toggle")
                if eye is not None:
                    eye.set_pixmap(
                        self._eye_pix_closed if new_hidden
                        else self._eye_pix_open)
                    eye.setToolTip(
                        I18n.tr("tool_show") if new_hidden
                        else I18n.tr("tool_hide"))
            break
        self.visibility_changed.emit(key, not new_hidden)

    def _eye_at(self, pos):
        """Return the tool key whose eye button covers viewport pos, else None."""
        item = self.itemAt(pos)
        if item is None:
            return None
        row = self.itemWidget(item)
        if row is None:
            return None
        eye = row.findChild(_GlyphWidget, "eye_toggle")
        if eye is None or not eye.isVisible():
            return None
        # The eye now lives inside the fixed-width side container, so
        # eye.geometry() is relative to its parent, not to the row widget.
        parent = eye.parentWidget()
        local = parent.mapFrom(self.viewport(), pos)
        return item.data(Qt.UserRole) if eye.geometry().contains(local) else None

    def mousePressEvent(self, event):
        """Catch clicks that land on an eye toggle and switch visibility.

        The row widgets are mouse-transparent so drags can start anywhere on
        the row, but Qt propagates that transparency to every child — the eye
        button itself never receives events. Intercepting here keeps the
        toggle working without sacrificing drag-from-anywhere: the event is
        swallowed (no row selection, no drag start) when it hits an eye."""
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            key = self._eye_at(pos)
            if key is not None:
                self._toggle_tool(key)
                event.accept()
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Qt does not always re-fit index widgets to the new item rect after
        # the dialog is shown, leaving the rightmost widgets (eye, grip)
        # clipped past the viewport edge. Force a geometry refresh so every
        # row matches the viewport width.
        self.updateGeometries()

    # ---------- drag-state styling ----------
    def _set_dragging_style(self, dragging):
        """Toggle the `dragging` dynamic property to suppress hover/selection
        backgrounds while a drag is in progress."""
        self.setProperty("dragging", "true" if dragging else "")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    # ---------- drag entry points (source side) ----------
    def mimeTypes(self):
        return [self.MIME]

    def mimeData(self, items):
        md = QMimeData()
        if items:
            key = items[0].data(Qt.UserRole) or ""
            md.setData(self.MIME, key.encode("utf-8"))
        return md

    def supportedDropActions(self):
        return Qt.MoveAction

    # ---------- drag entry points (target side) ----------
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.MIME):
            event.acceptProposedAction()
            self._set_dragging_style(True)
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        super().dragLeaveEvent(event)
        self.clearSelection()
        self.setCurrentItem(None)
        self._set_dragging_style(False)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(self.MIME):
            # The default handler updates the drop-indicator line; our
            # mimeTypes()/supportedDropActions() overrides tell it our MIME
            # is acceptable for a MoveAction here.
            super().dragMoveEvent(event)
            event.acceptProposedAction()
            # Suppress the transient row highlight so only the line shows.
            self.clearSelection()
            self.setCurrentItem(None)
        else:
            super().dragMoveEvent(event)

    def dropMimeData(self, index, data, action):
        # Never used in our manual-drag flow; the model stays untouched.
        return False

    def dropEvent(self, event):
        """Manual reorder using the source key carried in our private MIME.

        The source item has never left the model, so it is always found. One
        takeItem()+insertItem() moves it; same-slot drops are accepted as
        no-ops. Row widgets are rebuilt afterwards."""
        md = event.mimeData()
        if not md.hasFormat(self.MIME):
            super().dropEvent(event)
            return

        raw = bytes(md.data(self.MIME)).decode("utf-8")
        if not raw:
            self._set_dragging_style(False)
            event.ignore()
            return

        src_row = -1
        for i in range(self.count()):
            if self.item(i).data(Qt.UserRole) == raw:
                src_row = i
                break
        if src_row < 0:
            self._set_dragging_style(False)
            event.ignore()
            return

        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        target = self.indexAt(pos)
        indicator = self.dropIndicatorPosition()
        if not target.isValid():
            dst_row = self.count()      # empty space below the last item
        elif indicator == QAbstractItemView.AboveItem:
            dst_row = target.row()
        else:                           # BelowItem / OnItem -> insert after
            dst_row = target.row() + 1

        # Compensate for the source removal when it sits above the target.
        if src_row < dst_row:
            dst_row -= 1
        n = self.count()
        dst_row = max(0, min(dst_row, n - 1))

        if dst_row == src_row:
            # Same effective slot -> no-op, never produce a duplicate.
            self.clearSelection()
            self.setCurrentItem(None)
            event.acceptProposedAction()
            self._set_dragging_style(False)
            return

        moved = self.takeItem(src_row)
        self.insertItem(dst_row, moved)
        self.attach_row_widgets()

        self.clearSelection()
        self.setCurrentItem(None)

        event.acceptProposedAction()
        self.order_changed.emit()
        self._set_dragging_style(False)

    # ---------- drag source: start ----------
    def startDrag(self, supportedActions):
        """Start a manual drag; deliberately NOT super().startDrag().

        Never calling the base class means QAbstractItemView's trailing
        clearOrRemove() (which deletes still-selected source rows) never
        runs. The item stays put until our dropEvent() moves it."""
        item = self.currentItem()
        if item is None:
            return
        key = item.data(Qt.UserRole)
        if not key:
            return

        mime = QMimeData()
        mime.setData(self.MIME, key.encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime)
        # Snapshot the row as the drag preview.
        rect = self.visualItemRect(item)
        if rect.isValid() and rect.width() > 0 and rect.height() > 0:
            pm = self.viewport().grab(rect)
            drag.setPixmap(pm)
            drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))

        self._set_dragging_style(True)
        try:
            drag.exec(supportedActions, Qt.MoveAction)
        finally:
            # Runs whether dropped, cancelled, or aborted with ESC.
            self._set_dragging_style(False)


class _Sidebar(QListWidget):
    """Compact navigation column for the settings dialog."""

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setFixedWidth(132)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QListWidget.SingleSelection)
        for key, label in entries:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            item.setSizeHint(QSize(0, 40))
            self.addItem(item)
        self.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                padding: 10px 6px;
                font-size: 13px;
                outline: none;
            }}
            QListWidget::item {{
                color: {self._fg()};
                border-radius: 8px;
                padding-left: 4px;
            }}
            QListWidget::item:hover {{ background: rgba(128,128,128,45); }}
            QListWidget::item:selected {{
                background: {_accent_hex()};
                color: #ffffff;
            }}
        """)
        if self.count() > 0:
            self.setCurrentRow(0)

    def _fg(self):
        c = QApplication.palette().color(QPalette.WindowText)
        return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"


class SettingsDialog(QDialog):
    """Settings dialog split into a left navigation sidebar and a right pane."""

    def __init__(self, capsule=None, hotkey_mgr=None, initial_page=None,
                 parent=None):
        super().__init__(parent)
        self._capsule = capsule
        self._hotkey_mgr = hotkey_mgr
        self._hotkey_warn_timer = None
        self.setWindowTitle(I18n.tr("settings_title"))
        self.setFixedSize(540, 460)
        self._page_anim = None
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint
        )
        self.setup_ui()
        self.load_settings()
        self._connect_signals()
        self.center_on_screen()
        if initial_page:
            self._show_page(initial_page)

    def _show_page(self, key):
        """Jump straight to the sidebar page identified by `key`.

        Used when the search results open the settings on a specific page.
        setCurrentRow fires currentRowChanged, which drives the page fade."""
        for i in range(self.sidebar.count()):
            if self.sidebar.item(i).data(Qt.UserRole) == key:
                self.sidebar.setCurrentRow(i)
                break

    def _connect_signals(self):
        # Changes apply immediately as the user edits each control, rather than
        # waiting for the dialog to close. done() still re-persists as a safety
        # net. Load-order note: signals are wired after load_settings() so the
        # initial population does not trigger redundant saves.
        self.lang_combo.currentIndexChanged.connect(self._persist)
        self.autostart_check.toggled.connect(self._persist)
        self.translate_lang_combo.currentIndexChanged.connect(self._persist)
        self.tool_order_list.order_changed.connect(self._on_tool_order_changed)
        self.tool_order_list.visibility_changed.connect(
            self._on_tool_visibility_changed)

    def _on_tool_order_changed(self, *_):
        """Drag reorder landed: persist the new order and refresh the capsule."""
        order = []
        for i in range(self.tool_order_list.count()):
            key = self.tool_order_list.item(i).data(Qt.UserRole)
            if key:
                order.append(key)
        Config().set("tool_order", order)
        if self._capsule is not None:
            self._capsule.reorder_tools(order)

    def _on_tool_visibility_changed(self, key, visible):
        """Eye toggle clicked: persist the hidden set and refresh the capsule."""
        hidden = self.tool_order_list.hidden_keys()
        Config().set("hidden_tools", hidden)
        if self._capsule is not None:
            self._capsule.set_tools_hidden(hidden)

    def setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- left navigation ---
        self.sidebar = _Sidebar([
            ("general", I18n.tr("settings_general")),
            ("hotkey", I18n.tr("hotkey")),
            ("translate", I18n.tr("settings_translate")),
            ("system", I18n.tr("settings_system")),
            ("about", I18n.tr("settings_about")),
        ])
        outer.addWidget(self.sidebar)

        # --- right content + a menu divider ---
        divider = QFrame(self)
        divider.setFixedWidth(1)
        divider.setStyleSheet("background: rgba(120,120,120,80);")
        outer.addWidget(divider)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_general_page())
        self.stack.addWidget(self._build_hotkey_page())
        self.stack.addWidget(self._build_translate_page())
        self.stack.addWidget(self._build_system_page())
        self.stack.addWidget(AboutPage())

        # Right pane = content stack only. Settings are persisted automatically
        # whenever the dialog closes (see done()), so no Save button is needed.
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self.stack, 1)

        outer.addLayout(right, 1)

        self.sidebar.currentRowChanged.connect(self._switch_page)

    # ----- pages -----

    def _row(self, label_text, widget):
        row = QHBoxLayout()
        row.setSpacing(12)
        label = QLabel(label_text)
        label.setFixedWidth(90)
        row.addWidget(label)
        row.addWidget(widget, 1)
        row.addStretch()
        return row

    def _build_general_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("中文", "zh_CN")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setFixedWidth(180)
        layout.addLayout(self._row(I18n.tr("language"), self.lang_combo))

        # --- tool order: drag to reorder the capsule buttons ---
        order_title = QLabel(I18n.tr("tool_order"))
        order_title.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(order_title)

        self.tool_order_list = _ReorderToolList()
        self.tool_order_list.setFixedHeight(190)
        grip_pix = _make_grip_pixmap(14)
        tool_labels = {
            "screenshot": I18n.tr("screenshot"),
            "annotation": I18n.tr("annotation"),
            "translate": I18n.tr("translate"),
            "clipboard": I18n.tr("clipboard"),
            "search": I18n.tr("search"),
        }
        self.tool_order_list.set_tool_labels(tool_labels, grip_pix)

        def _add_tool_item(key):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, key)
            item.setSizeHint(QSize(0, 30))
            self.tool_order_list.addItem(item)

        order = Config().get(
            "tool_order",
            ["screenshot", "annotation", "translate", "clipboard", "search"])
        for key in order:
            if key not in tool_labels:
                continue
            _add_tool_item(key)
        # Append any tool missing from a stale saved order so the list always
        # shows every tool.
        for key in tool_labels:
            found = any(
                self.tool_order_list.item(i).data(Qt.UserRole) == key
                for i in range(self.tool_order_list.count())
            )
            if not found:
                _add_tool_item(key)
        # Mount the per-row widgets (label left, eye toggle, grip right).
        # set_hidden_keys() restores the saved visibility and rebuilds rows.
        self.tool_order_list.set_eye_pixmaps(*_make_eye_pixmaps(12))
        self.tool_order_list.set_hidden_keys(Config().get("hidden_tools", []))
        self.tool_order_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: 1px solid rgba(128,128,128,60);
                border-radius: 8px;
                padding: 4px;
                font-size: 13px;
                outline: none;
            }}
            QListWidget::item {{
                color: {_text_hex()};
                border-radius: 6px;
                padding: 2px 8px;
            }}
            QListWidget::item:hover {{ background: rgba(128,128,128,45); }}
            QListWidget::item:selected {{
                background: transparent;
                color: {_text_hex()};
            }}
            QListWidget::item:focus {{ outline: none; }}
            /* While a drag is in progress, gate the hover/selected paints so
               the only positional cue is the drop-indicator line. */
            QListWidget[dragging="true"]::item:hover {{ background: transparent; }}
            QListWidget[dragging="true"]::item:selected {{
                background: transparent;
                color: {_text_hex()};
            }}
        """)
        layout.addWidget(self.tool_order_list)

        order_hint = QLabel(I18n.tr("tool_order_hint"))
        order_hint.setStyleSheet("font-size: 11px; color: #868e96;")
        order_hint.setWordWrap(True)
        layout.addWidget(order_hint)

        layout.addStretch()
        return page

    def _build_hotkey_page(self):
        """Hotkey page: one row per feature, edited with QKeySequenceEdit.

        Each change is applied to the live HotkeyManager immediately (global
        hotkeys take effect on the spot) and persisted to config.json.
        Conflicts / invalid combinations are rejected inline, not via modal
        dialogs, and the editor is reverted to its previous value."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        self._hotkey_editors = {}

        for hotkey_id, cfg_key, label_key, default_seq in HOTKEY_SPECS:
            row = QHBoxLayout()
            row.setSpacing(12)
            label = QLabel(I18n.tr(label_key))
            label.setFixedWidth(90)
            row.addWidget(label)

            editor = QKeySequenceEdit()
            editor.setMaximumSequenceLength(1)
            editor.setFixedHeight(30)
            saved = Config().get(cfg_key, default_seq)
            if saved:
                editor.setKeySequence(
                    QKeySequence.fromString(saved, QKeySequence.PortableText))
            self._hotkey_editors[hotkey_id] = editor
            row.addWidget(editor, 1)

            clear_btn = QPushButton(I18n.tr("hotkey_clear"))
            clear_btn.setFixedSize(56, 30)
            clear_btn.setCursor(Qt.PointingHandCursor)
            clear_btn.setToolTip(I18n.tr("hotkey_clear_tip"))
            row.addWidget(clear_btn)

            layout.addLayout(row)

            editor.keySequenceChanged.connect(
                lambda seq, hid=hotkey_id, cfg=cfg_key,
                ed=editor: self._apply_hotkey(hid, cfg, ed))
            clear_btn.clicked.connect(
                lambda checked=False, hid=hotkey_id, cfg=cfg_key,
                ed=editor: self._clear_hotkey(hid, cfg, ed))

        # Inline (non-modal) feedback for rejected combinations.
        self._hotkey_warn = QLabel("")
        self._hotkey_warn.setStyleSheet("font-size: 11px; color: #e5484d;")
        self._hotkey_warn.setWordWrap(True)
        self._hotkey_warn.setVisible(False)
        layout.addWidget(self._hotkey_warn)

        hint = QLabel(I18n.tr("hotkey_hint"))
        hint.setStyleSheet("font-size: 11px; color: #868e96;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Reset-to-defaults action.
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        reset_btn = QPushButton(I18n.tr("hotkey_reset"))
        reset_btn.setFixedSize(70, 30)
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.setToolTip(I18n.tr("hotkey_reset_tip"))
        reset_btn.clicked.connect(self._reset_all_hotkeys)
        btn_row.addWidget(reset_btn)
        layout.addLayout(btn_row)

        layout.addStretch()
        return page

    def _clear_hotkey(self, hotkey_id, cfg_key, editor):
        """Clear the editor and unregister the hotkey for a feature."""
        editor.clear()
        self._apply_hotkey(hotkey_id, cfg_key, editor, QKeySequence())

    def _reset_all_hotkeys(self):
        """Restore every hotkey to its spec default and persist the values.

        Reset works in two passes and skips the occupancy check used for
        manual edits, so it always completes: pass 1 clears every live
        binding (so a leftover combination can never block a default), then
        pass 2 registers the defaults. A default that is unavailable
        elsewhere is simply left unbound, without any inline conflict
        notice, until the combination frees up."""
        if hasattr(self, "_hotkey_warn"):
            self._hotkey_warn.setVisible(False)
        # Pass 1: fill editors with the defaults, persist them, and clear
        # every live binding.
        for hotkey_id, cfg_key, _label, default_seq in HOTKEY_SPECS:
            editor = self._hotkey_editors.get(hotkey_id)
            if editor is None:
                continue
            qseq = QKeySequence.fromString(
                default_seq, QKeySequence.PortableText)
            # Suppress keySequenceChanged so the editor is filled without
            # running the normal validate/register path.
            editor.blockSignals(True)
            editor.setKeySequence(qseq)
            editor.blockSignals(False)
            Config().set(cfg_key, qseq.toString(QKeySequence.PortableText))
            if self._hotkey_mgr is not None:
                self._hotkey_mgr.register(hotkey_id, 0, 0)
        # Pass 2: register the defaults, ignoring occupancy failures.
        if self._hotkey_mgr is not None:
            for hotkey_id, _cfg_key, _label, default_seq in HOTKEY_SPECS:
                qseq = QKeySequence.fromString(
                    default_seq, QKeySequence.PortableText)
                mod, vk = qkeysequence_to_win(qseq)
                self._hotkey_mgr.register(hotkey_id, mod, vk)

    def _apply_hotkey(self, hotkey_id, cfg_key, editor, qseq=None):
        """Validate, register (via the live manager) and persist a hotkey.

        On rejection the editor is reverted to the saved value and an inline
        warning is shown; the manager rolls its own binding back to the
        previous state, so nothing half-applies."""
        if qseq is None:
            qseq = QKeySequence(editor.keySequence())
        mod, vk = qkeysequence_to_win(qseq)
        if not is_valid_hotkey(mod, vk):
            self._reject_hotkey(editor, cfg_key, I18n.tr("hotkey_invalid"), qseq)
            return
        ok = True
        if self._hotkey_mgr is not None:
            ok = self._hotkey_mgr.register(hotkey_id, mod, vk)
        if ok:
            seq_text = qseq.toString(QKeySequence.PortableText) if vk else ""
            Config().set(cfg_key, seq_text)
        else:
            self._reject_hotkey(
                editor, cfg_key, I18n.tr("hotkey_conflict"), qseq)

    def _reject_hotkey(self, editor, cfg_key, message, qseq):
        """Revert the editor and show a transient inline warning."""
        # Fall back to the spec default (e.g. Ctrl+` for the capsule) so the
        # editor shows what is actually registered even when the key was never
        # persisted to config before.
        default_seq = ""
        for _hid, ck, _label, dseq in HOTKEY_SPECS:
            if ck == cfg_key:
                default_seq = dseq
                break
        saved = Config().get(cfg_key, default_seq)
        if saved:
            editor.setKeySequence(
                QKeySequence.fromString(saved, QKeySequence.PortableText))
        else:
            editor.clear()
        try:
            text = message.format(seq=qseq.toString(QKeySequence.PortableText))
        except (KeyError, IndexError):
            text = message
        self._hotkey_warn.setText(text)
        self._hotkey_warn.setVisible(True)
        if self._hotkey_warn_timer is not None:
            self._hotkey_warn_timer.stop()
        self._hotkey_warn_timer = QTimer(self)
        self._hotkey_warn_timer.setSingleShot(True)
        self._hotkey_warn_timer.timeout.connect(
            lambda: self._hotkey_warn.setVisible(False))
        self._hotkey_warn_timer.start(4000)

    def _build_translate_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        self.translate_lang_combo = QComboBox()
        self.translate_lang_combo.addItem("简体中文", "zh-CN")
        self.translate_lang_combo.addItem("繁體中文", "zh-TW")
        self.translate_lang_combo.addItem("English", "en")
        self.translate_lang_combo.addItem("日本語", "ja")
        self.translate_lang_combo.addItem("한국어", "ko")
        self.translate_lang_combo.setFixedWidth(180)
        layout.addLayout(
            self._row(I18n.tr("translate_target_lang"), self.translate_lang_combo))

        hint = QLabel(I18n.tr("translate_source_hint"))
        hint.setStyleSheet("font-size: 11px; color: #868e96;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()
        return page

    def _build_system_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        row = QHBoxLayout()
        row.setSpacing(12)
        label = QLabel(I18n.tr("autostart"))
        label.setFixedWidth(90)
        row.addWidget(label)
        self.autostart_check = QCheckBox()
        row.addWidget(self.autostart_check)
        row.addStretch()
        layout.addLayout(row)

        layout.addStretch()
        return page

    # ----- load / save -----

    def load_settings(self):
        config = Config()
        lang = config.get("language", "zh_CN")
        index = self.lang_combo.findData(lang)
        if index >= 0:
            self.lang_combo.setCurrentIndex(index)

        autostart = config.get("autostart", False)
        self.autostart_check.setChecked(autostart)

        translate_lang = config.get("translate_target_lang", "zh-CN")
        index = self.translate_lang_combo.findData(translate_lang)
        if index >= 0:
            self.translate_lang_combo.setCurrentIndex(index)

    def _persist(self, *_):
        lang = self.lang_combo.currentData()
        I18n.set_language(lang)

        autostart = self.autostart_check.isChecked()
        Config().set("autostart", autostart)
        apply_autostart(autostart)

        Config().set("translate_target_lang", self.translate_lang_combo.currentData())

    def done(self, result):
        # Settings already apply instantly via _connect_signals(); ending here
        # re-persists once more as a safety net so nothing is ever lost.
        self._persist()
        super().done(result)

    # ----- page transition -----

    def _switch_page(self, index):
        """Switch the right-pane page with a short fade-in transition."""
        self.stack.setCurrentIndex(index)
        page = self.stack.currentWidget()
        if page is None:
            return
        # Stop any in-flight transition.
        if self._page_anim is not None:
            try:
                self._page_anim.stop()
                self._page_anim.deleteLater()
            except RuntimeError:
                pass
            self._page_anim = None
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, QByteArray(b"opacity"))
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.Linear)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(self._on_page_fade_finished)
        self._page_anim = anim
        anim.start()

    def _on_page_fade_finished(self):
        """Clear the temporary opacity effect once the fade completes."""
        if self._page_anim is not None:
            try:
                self._page_anim.deleteLater()
            except RuntimeError:
                pass
            self._page_anim = None
        page = self.stack.currentWidget()
        if page is not None and page.graphicsEffect() is not None:
            page.setGraphicsEffect(None)

    def center_on_screen(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2
        )