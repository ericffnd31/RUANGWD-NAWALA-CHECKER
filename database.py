"""
Database SQLite — Nawala Bot
Unique key: full_url (bukan domain_name)
Sehingga ruangwd80742.com, ruangwd80742.com/blog, ruangwd80742.com/rtp
tersimpan sebagai 3 entry terpisah, DNS check via domain_name.
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
                domain_name TEXT    NOT NULL,
                full_url    TEXT    NOT NULL UNIQUE,
                is_blocked  INTEGER,
                checked_at  TEXT,
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        # Migrasi dari versi lama (unique domain_name → unique full_url)
        # Tambah kolom jika belum ada
        try:
            c.execute("ALTER TABLE domains ADD COLUMN full_url TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        # Hapus unique constraint lama jika ada & buat index baru
        # (SQLite tidak support DROP CONSTRAINT, tapi CREATE TABLE IF NOT EXISTS sudah benar)
    logger.info(f"DB: {DB_FILE}")


# ── DOMAIN ────────────────────────────────────────────────────────────────────

def url_exists(full_url: str) -> bool:
    """Cek berdasarkan full_url (bukan domain_name)."""
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM domains WHERE full_url=?", (full_url,)
        ).fetchone() is not None

def domain_exists(domain_name: str) -> bool:
    """Backward compat — cek domain_name."""
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM domains WHERE domain_name=?", (domain_name,)
        ).fetchone() is not None

def add_domain(domain_name: str, full_url: str = ""):
    """Simpan entry. Unique berdasarkan full_url."""
    furl = full_url or domain_name
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO domains (domain_name, full_url) VALUES (?,?)",
            (domain_name, furl)
        )

def delete_domain_by_url(full_url: str):
    with _conn() as c:
        c.execute("DELETE FROM domains WHERE full_url=?", (full_url,))

def delete_domain(domain_name: str):
    """Hapus semua entry dengan domain_name tsb."""
    with _conn() as c:
        c.execute("DELETE FROM domains WHERE domain_name=?", (domain_name,))

def update_domain_name(old_url: str, new_domain: str, new_url: str):
    with _conn() as c:
        c.execute(
            "UPDATE domains SET domain_name=?, full_url=? WHERE full_url=?",
            (new_domain, new_url, old_url)
        )

def update_status_by_id(domain_id: int, blocked: bool):
    now = datetime.now().strftime("%Y-%m-%d %H:%M WIB")
    with _conn() as c:
        c.execute(
            "UPDATE domains SET is_blocked=?, checked_at=? WHERE id=?",
            (1 if blocked else 0, now, domain_id)
        )

def update_status_by_name(domain_name: str, blocked: bool):
    """Update semua entry dengan domain_name yang sama."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M WIB")
    with _conn() as c:
        c.execute(
            "UPDATE domains SET is_blocked=?, checked_at=? WHERE domain_name=?",
            (1 if blocked else 0, now, domain_name)
        )

def update_status_by_url(full_url: str, blocked: bool):
    now = datetime.now().strftime("%Y-%m-%d %H:%M WIB")
    with _conn() as c:
        c.execute(
            "UPDATE domains SET is_blocked=?, checked_at=? WHERE full_url=?",
            (1 if blocked else 0, now, full_url)
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


# ── SETTINGS ──────────────────────────────────────────────────────────────────

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
