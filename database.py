"""
Database handler menggunakan SQLite.
Support Railway persistent volume via env RAILWAY_VOLUME_MOUNT_PATH
"""

import os
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_VOLUME = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "")
DB_FILE = os.path.join(_VOLUME, "nawala_bot.db") if _VOLUME else "nawala_bot.db"


class Database:
    def __init__(self):
        self.db_file = DB_FILE

    def _conn(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS domains (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain_name TEXT    NOT NULL UNIQUE,
                    is_blocked  INTEGER,
                    checked_at  TEXT,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
        logger.info(f"Database: {self.db_file}")

    def add_domain(self, domain: str):
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO domains (domain_name) VALUES (?)", (domain,))

    def domain_exists(self, domain: str) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM domains WHERE domain_name = ?", (domain,)).fetchone() is not None

    def delete_domain(self, domain: str):
        with self._conn() as conn:
            conn.execute("DELETE FROM domains WHERE domain_name = ?", (domain,))

    def update_domain_name(self, old: str, new: str):
        with self._conn() as conn:
            conn.execute("UPDATE domains SET domain_name = ? WHERE domain_name = ?", (new, old))

    def update_domain_status(self, domain_id: int, blocked: bool):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            conn.execute("UPDATE domains SET is_blocked = ?, checked_at = ? WHERE id = ?",
                         (1 if blocked else 0, now, domain_id))

    def update_domain_status_by_name(self, domain: str, blocked: bool):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            conn.execute("UPDATE domains SET is_blocked = ?, checked_at = ? WHERE domain_name = ?",
                         (1 if blocked else 0, now, domain))

    def get_all_domains(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, domain_name, is_blocked, checked_at FROM domains ORDER BY domain_name"
            ).fetchall()
            return [(r["id"], r["domain_name"], r["is_blocked"], r["checked_at"]) for r in rows]

    def get_domain_count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) as c FROM domains").fetchone()["c"]

    def save_setting(self, key: str, value):
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))

    def get_settings(self) -> dict:
        from config import DEFAULT_INTERVAL_MINUTES
        with self._conn() as conn:
            raw = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings").fetchall()}
        return {
            "interval_minutes": int(raw.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)),
            "alerts_active":    raw.get("alerts_active", "True") not in ("False", "0", "false"),
            "chat_id":          raw.get("chat_id"),
            "site_name":        raw.get("site_name", "Default Site"),
        }

    def save_chat_id(self, chat_id: int):
        self.save_setting("chat_id", chat_id)
        self.save_setting("alerts_active", True)
