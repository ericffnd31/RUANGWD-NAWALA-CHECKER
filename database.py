"""
Database SQLite — Nawala Bot
Support Railway persistent volume via RAILWAY_VOLUME_MOUNT_PATH
"""

import os
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_VOL    = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "")
DB_FILE = os.path.join(_VOL, "nawala_bot.db") if _VOL else "nawala_bot.db"


def _conn():
    c = sqlite3.connect(DB_FILE, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS domains (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                domain_name TEXT    NOT NULL UNIQUE,
                full_url    TEXT    NOT NULL DEFAULT '',
                is_blocked  INTEGER,
                checked_at  TEXT,
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        # migrasi kolom full_url jika belum ada
        try:
            c.execute("ALTER TABLE domains ADD COLUMN full_url TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
    logger.info(f"DB: {DB_FILE}")


# ── DOMAIN ────────────────────────────────────────────────────────────────────

def domain_exists(domain_name: str) -> bool:
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM domains WHERE domain_name=?", (domain_name,)
        ).fetchone() is not None

def add_domain(domain_name: str, full_url: str = ""):
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO domains (domain_name, full_url) VALUES (?,?)",
            (domain_name, full_url or domain_name)
        )

def delete_domain(domain_name: str):
    with _conn() as c:
        c.execute("DELETE FROM domains WHERE domain_name=?", (domain_name,))

def update_domain_name(old: str, new: str, new_url: str = ""):
    with _conn() as c:
        c.execute(
            "UPDATE domains SET domain_name=?, full_url=? WHERE domain_name=?",
            (new, new_url or new, old)
        )

def update_status_by_id(domain_id: int, blocked: bool):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        c.execute(
            "UPDATE domains SET is_blocked=?, checked_at=? WHERE id=?",
            (1 if blocked else 0, now, domain_id)
        )

def update_status_by_name(domain_name: str, blocked: bool):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        c.execute(
            "UPDATE domains SET is_blocked=?, checked_at=? WHERE domain_name=?",
            (1 if blocked else 0, now, domain_name)
        )

def get_all_domains() -> list:
    """Returns [(id, domain_name, full_url, is_blocked, checked_at)]"""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, domain_name, full_url, is_blocked, checked_at "
            "FROM domains ORDER BY id"
        ).fetchall()
        return [(r["id"], r["domain_name"], r["full_url"],
                 r["is_blocked"], r["checked_at"]) for r in rows]

def get_domain_count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM domains").fetchone()[0]


# ── SETTINGS ─────────────────────────────────────────────────────────────────

def save_setting(key: str, value):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
            (key, str(value))
        )

def get_settings() -> dict:
    from config import DEFAULT_INTERVAL_MINUTES
    with _conn() as c:
        raw = {r["key"]: r["value"]
               for r in c.execute("SELECT key,value FROM settings").fetchall()}
    return {
        "interval_minutes": int(raw.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)),
        "alerts_active":    raw.get("alerts_active", "True") not in ("False","0","false"),
        "chat_id":          raw.get("chat_id"),
        "site_name":        raw.get("site_name", "Default Site"),
    }

def save_chat_id(chat_id: int):
    save_setting("chat_id", chat_id)
    save_setting("alerts_active", True)
