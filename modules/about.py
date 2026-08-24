"""About page and check-for-update logic for CapRise.

The update check fetches the latest version from a plain-text file hosted on
GitHub Pages (Config.UPDATE_URL), which avoids the Gitee/GitHub raw hotlink
bans and the public-API rate limits of the previous GitHub/Gitee pick-by-
language approach. It then compares that version against the local one.
"""
import re
import urllib.request
import urllib.error
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QApplication, QFrame
)
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPalette, QFont, QFontMetrics, QEnterEvent, QColor

from modules.config import Config
from modules.i18n import I18n


# ---------- version helpers ----------

def _extract_version(text):
    """Pull a dotted version like '1.2.3' out of a tag name. Returns a tuple
    of ints, or None if no version-like token is found."""
    matches = re.findall(r'(\d+(?:\.\d+)*)', text)
    if not matches:
        return None
    best = max(matches, key=lambda t: t.count('.'))
    return tuple(int(x) for x in best.split('.'))


def _compare(a, b):
    """Compare two version tuples of possibly different lengths
    (zero-padded, segment by segment). Returns >0 / 0 / <0."""
    a = list(a)
    b = list(b)
    n = max(len(a), len(b))
    while len(a) < n:
        a.append(0)
    while len(b) < n:
        b.append(0)
    return (a > b) - (a < b)


def _show_message(parent, title, text, icon):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(icon)
    box.addButton(I18n.tr("ok"), QMessageBox.AcceptRole)
    box.exec()


def check_update(parent=None):
    """Check for a newer version and prompt to download if one exists.

    Always fetches Config.UPDATE_URL (the GitHub Pages plain-text version
    file), decodes its body into a version, and compares it against the local
    one — no GitHub/Gitee branching needed.
    """
    try:
        req = urllib.request.Request(Config.UPDATE_URL)
        req.add_header('User-Agent', Config.APP_NAME)
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read().decode()

        latest_version = _extract_version(body)
        if latest_version is None:
            _show_message(parent, I18n.tr("about_check_update"),
                          I18n.tr("about_no_tags"), QMessageBox.Warning)
            return

        current = _extract_version(Config.APP_VERSION)
        if current is None:
            _show_message(parent, I18n.tr("about_check_update"),
                          I18n.tr("about_parse_error"), QMessageBox.Warning)
            return

        if _compare(latest_version, current) > 0:
            revision = ".".join(str(x) for x in latest_version)
            box = QMessageBox(parent)
            box.setWindowTitle(I18n.tr("about_check_update"))
            box.setText(I18n.tr("about_new_version", version=revision))
            box.setIcon(QMessageBox.NoIcon)
            yes = box.addButton(I18n.tr("about_yes"), QMessageBox.YesRole)
            box.addButton(I18n.tr("about_no"), QMessageBox.NoRole)
            box.exec()
            if box.clickedButton() == yes:
                # Download page by language: Gitee for Chinese, GitHub else.
                releases_url = (Config.GITEE_RELEASES
                                if I18n.get_language() == "zh_CN"
                                else Config.GITHUB_RELEASES)
                QDesktopServices.openUrl(QUrl(releases_url))
        else:
            _show_message(parent, I18n.tr("about_check_update"),
                          I18n.tr("about_latest"), QMessageBox.Information)

    except urllib.error.URLError as e:
        _show_message(parent, I18n.tr("about_check_update"),
                      I18n.tr("about_network_error", error=str(e)),
                      QMessageBox.Warning)
    except Exception as e:
        _show_message(parent, I18n.tr("about_check_update"),
                      I18n.tr("about_check_failed", error=str(e)),
                      QMessageBox.Warning)


# ---------- about page widget ----------

def _section_label(text):
    label = QLabel(text)
    label.setStyleSheet("font-size: 12px; color: #868e96;")
    return label


class ClickableLabel(QLabel):
    """Clickable link label with hover underline (mirrors LANSyncBox).

    Used for the "查看详情" / "问题反馈" links on the About page."""

    clicked = Signal()

    def __init__(self, text, normal_color, hover_color):
        super().__init__(text)
        self._normal_color = normal_color
        self._hover_color = hover_color
        self._original_font = self.font()
        self.setStyleSheet(
            f"QLabel {{ font-size: 12px; color: {normal_color}; }}")
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, event):
        if isinstance(event, QEnterEvent):
            self.setStyleSheet(
                f"QLabel {{ font-size: 12px; color: {self._hover_color}; }}")
            font = QFont(self._original_font)
            font.setUnderline(True)
            self.setFont(font)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(
            f"QLabel {{ font-size: 12px; color: {self._normal_color}; }}")
        font = QFont(self._original_font)
        font.setUnderline(False)
        self.setFont(font)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class AboutPage(QWidget):
    """About settings page: app info + check-for-update button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("about_page")
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        def _accent_hex():
            c = QApplication.palette().color(QPalette.Highlight)
            return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"

        accent = QColor(_accent_hex())
        hover = accent.lighter(130) if accent.lightness() < 128 \
            else accent.darker(115)
        hover_hex = f"#{hover.red():02x}{hover.green():02x}{hover.blue():02x}"

        title = QLabel(Config.APP_NAME)
        title.setAlignment(Qt.AlignLeft)
        title.setStyleSheet(f"font-size: 26px; font-weight: bold; "
                            f"color: {_accent_hex()};")
        layout.addWidget(title)

        version = QLabel(f"{I18n.tr('about_version_label')}: "
                         f"{Config.APP_VERSION}")
        version.setStyleSheet("font-size: 12px; color: #495057;")
        layout.addWidget(version)

        author = QLabel(f"{I18n.tr('about_author')}: {Config.APP_AUTHOR}")
        author.setStyleSheet("font-size: 11px; color: #868e96;")
        layout.addWidget(author)

        # GitHub repo link — clickable, opens the repository page.
        repo = ClickableLabel(f"GitHub: {Config.GITHUB_REPO}", "#868e96", hover_hex)
        repo.clicked.connect(self._open_github)
        layout.addWidget(repo)

        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: rgba(120,120,120,90);")
        layout.addSpacing(6)
        layout.addWidget(line)
        layout.addSpacing(6)

        # Link row: 问题反馈 opens the GitHub issues page, 查看详情 opens
        # the author's project homepage (mirrors LANSyncBox).
        link_row = QHBoxLayout()
        link_row.setSpacing(20)
        feedback_link = ClickableLabel(
            I18n.tr("about_feedback"), _accent_hex(), hover_hex)
        feedback_link.clicked.connect(self._open_issues)
        link_row.addWidget(feedback_link)
        details_link = ClickableLabel(
            I18n.tr("about_details"), _accent_hex(), hover_hex)
        details_link.clicked.connect(self._open_details)
        link_row.addWidget(details_link)
        link_row.addStretch()
        layout.addLayout(link_row)

        if Config.ENABLE_CHECK_UPDATE:
            # 检查更新 sits below the link row and spans the same width as
            # the two links together (text width + 20 px spacing).
            link_font = QFont(self.font())
            link_font.setPixelSize(12)
            fm = QFontMetrics(link_font)
            links_width = (
                fm.horizontalAdvance(I18n.tr("about_feedback"))
                + 20
                + fm.horizontalAdvance(I18n.tr("about_details"))
            )
            check_btn = QPushButton(I18n.tr("about_check_update"))
            check_btn.setCursor(Qt.PointingHandCursor)
            # Never smaller than the button's own text at 13px (English
            # "Check for Updates" is long and overflows the link-row width),
            # but at least links_width so it still aligns with the links.
            btn_font = QFont(self.font())
            btn_font.setPixelSize(13)
            btn_fm = QFontMetrics(btn_font)
            btn_min = btn_fm.horizontalAdvance(
                I18n.tr("about_check_update")) + 32
            check_btn.setFixedSize(max(links_width, btn_min), 34)
            check_btn.setStyleSheet(
                f"QPushButton {{ background: {_accent_hex()}; color: white;"
                f" border: none; border-radius: 8px; font-size: 13px; }}"
                f"QPushButton:hover {{ opacity: .9; }}")
            check_btn.clicked.connect(
                lambda: check_update(self.window()))
            layout.addWidget(check_btn, alignment=Qt.AlignLeft)

        layout.addStretch()

    def _open_github(self):
        """Open the GitHub repository page."""
        QDesktopServices.openUrl(
            QUrl(f"https://github.com/{Config.GITHUB_REPO}"))

    def _open_issues(self):
        """Open the GitHub issues page (问题反馈)."""
        QDesktopServices.openUrl(
            QUrl(f"https://github.com/{Config.GITHUB_REPO}/issues"))

    def _open_details(self):
        """Open the author's project homepage (查看详情)."""
        QDesktopServices.openUrl(QUrl(Config.APP_AUTHOR_LINK))