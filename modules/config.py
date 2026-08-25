import json
from pathlib import Path


class Config:
    _instance = None

    # --- App info (used by the About page / check-for-update) ---
    APP_NAME = "CapRise"
    APP_VERSION = "1.1.5.0"
    APP_AUTHOR = "Lisselde_E"
    APP_AUTHOR_LINK = "https://lisseldee.github.io/#7"  # 项目主页链接

    # Feature switch: show the "check for updates" button.
    ENABLE_CHECK_UPDATE = True

    # Repository info (used by the About page / links).
    GITHUB_REPO = "LisseldeE/CapRise"
    GITEE_REPO = "Lisselde_E/CapRise"

    # Latest version is served as a plain-text file on GitHub Pages
    # (https://lisseldee.github.io/version/caprise) so the update checker
    # avoids Gitee/GitHub raw hotlink bans and public-API rate limits.
    UPDATE_URL = "https://lisseldee.github.io/version/caprise"
    GITHUB_RELEASES = f"https://github.com/{GITHUB_REPO}/releases"
    GITEE_RELEASES = f"https://gitee.com/{GITEE_REPO}/releases"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config = {}
            cls._instance._loaded = False
        return cls._instance

    def _get_config_path(self):
        config_dir = Path.home() / "CapRise"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def _load(self):
        if self._loaded:
            return
        path = self._get_config_path()
        if path.exists():
            try:
                self._config = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self._config = {}
        else:
            self._config = {}
        self._loaded = True

    def save(self):
        path = self._get_config_path()
        path.write_text(
            json.dumps(self._config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def update_reference_info(self, exe_path):
        """Record app name / version / own exe location into config.json.

        Mirrors LANSyncBox's update_reference_info: the installer's update
        flow reads these keys to locate the running exe and compare the
        installed version before replacing the file."""
        if not self.ENABLE_CHECK_UPDATE:
            return
        self._load()
        self._config["version"] = self.APP_VERSION
        self._config["exe_path"] = exe_path
        self._config["app_name"] = self.APP_NAME
        self.save()

    def get(self, key, default=None):
        self._load()
        return self._config.get(key, default)

    def set(self, key, value):
        self._load()
        self._config[key] = value
        self.save()