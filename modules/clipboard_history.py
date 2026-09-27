"""
剪贴板历史
基于 SQLite 的剪贴板历史存储
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import sqlite3
import time
from pathlib import Path


def _db_path():
    return Path.home() / "CapRise" / "clipboard_history.db"


class ClipboardHistory:
    """Persistent clipboard history. Caps at MAX_ITEMS, newest first."""

    MAX_ITEMS = 50

    def __init__(self):
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                origin_peer TEXT,
                timestamp REAL NOT NULL
            )"""
        )
        self._conn.commit()

    def add(self, content, source="local", origin_peer=None):
        """Insert an item. Identical prior content is removed first so the
        new entry bubbles to the top (avoids duplicate streaks). Returns id."""
        self._conn.execute("DELETE FROM history WHERE content = ?", (content,))
        self._conn.execute(
            "INSERT INTO history (content, source, origin_peer, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (content, source, origin_peer, time.time()),
        )
        # Trim to MAX_ITEMS (keep newest)
        self._conn.execute(
            "DELETE FROM history WHERE id NOT IN "
            "(SELECT id FROM history ORDER BY id DESC LIMIT ?)",
            (self.MAX_ITEMS,),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def get_all(self):
        """Return list of dicts (newest first)."""
        cur = self._conn.execute(
            "SELECT id, content, source, origin_peer, timestamp "
            "FROM history ORDER BY id DESC"
        )
        return [
            {
                "id": r[0],
                "content": r[1],
                "source": r[2],
                "origin_peer": r[3],
                "timestamp": r[4],
            }
            for r in cur.fetchall()
        ]

    def delete(self, item_id):
        self._conn.execute("DELETE FROM history WHERE id = ?", (item_id,))
        self._conn.commit()

    def clear(self):
        self._conn.execute("DELETE FROM history")
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
