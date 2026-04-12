"""
Database SQLite — Nawala Bot
Unique key: full_url → 35 link = 35 row berbeda
Import pakai INSERT OR REPLACE agar selalu masuk semua
"""

import os
import sqlite3
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_VOL    = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "")
DB_FILE = os.path.join(_VOL, "nawala_bot.db") if _VOL else "nawala_bot.db"
WIB     = ZoneInfo("Asia/Jakarta")


def _conn():
    c = sqlite3.connect(DB_FILE, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with _conn() as c:
        # Buat tabel baru jika belum ada
        c.executescript("""
            CREATE TABLE IF NOT EXISTS domains (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                domain_name TEXT    NOT NULL,
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

        # Tambah kolom full_url jika belum ada (migrasi dari versi lama)
        cols = [r[1] for r in c.execute("PRAGMA table_info(domains)").fetchall()]
        if "full_url" not in cols:
            c.execute("ALTER TABLE domains ADD COLUMN full_url TEXT NOT NULL DEFAULT ''")

        # Isi full_url untuk row lama yang masih kosong
        c.execute("UPDATE domains SET full_url = domain_name WHERE full_url = '' OR full_url IS NULL")

        # Buat unique index pada full_url jika belum ada
        indexes = [r[1] for r in c.execute("PRAGMA index_list(domains)").fetchall()]
        if "idx_full_url" not in indexes:
            # Hapus duplikat full_url sebelum buat index
            c.execute("""
                DELETE FROM domains WHERE id NOT IN (
                    SELECT MIN(id) FROM domains GROUP BY full_url
                )
            """)
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_full_url ON domains(full_url)")

    logger.info(f"DB ready: {DB_FILE}")


def now_wib() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")


# ── DOMAIN ────────────────────────────────────────────────────────────────────

def url_exists(full_url: str) -> bool:
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM domains WHERE full_url=?", (full_url,)
        ).fetchone() is not None

def domain_exists(domain_name: str) -> bool:
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM domains WHERE domain_name=?", (domain_name,)
        ).fetchone() is not None

def add_domain(domain_name: str, full_url: str = ""):
    """Tambah 1 domain. Jika full_url sudah ada → skip (INSERT OR IGNORE)."""
    furl = full_url or domain_name
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO domains (domain_name, full_url) VALUES (?,?)",
            (domain_name, furl)
        )

def bulk_import(entries: list) -> dict:
    """
    Import banyak domain sekaligus.
    entries: [(domain_name, full_url), ...]

    Logika:
    - Jika full_url sudah ada DAN full_url = domain_name (entry lama tanpa path)
      → UPDATE full_url ke versi lengkap (dengan path)
    - Jika full_url sudah ada DAN sudah benar → skip (sudah ada)
    - Jika belum ada → INSERT baru

    Returns: {"added": [...], "updated": [...], "skipped": [...], "errors": [...]}
    """
    result = {"added": [], "updated": [], "skipped": [], "errors": []}

    with _conn() as c:
        for domain_name, full_url in entries:
            try:
                # 1. Cek apakah full_url sudah ada persis
                row_exact = c.execute(
                    "SELECT id FROM domains WHERE full_url=?", (full_url,)
                ).fetchone()

                if row_exact:
                    # Sudah ada persis → skip
                    result["skipped"].append(full_url)
                    continue

                # 2. Cek apakah ada entry lama: domain_name sama, full_url = domain_name (tanpa path)
                row_old = c.execute(
                    "SELECT id FROM domains WHERE domain_name=? AND full_url=?",
                    (domain_name, domain_name)
                ).fetchone()

                if row_old and full_url != domain_name:
                    # Entry lama simpan domain saja → UPDATE full_url ke versi lengkap
                    c.execute(
                        "UPDATE domains SET full_url=? WHERE id=?",
                        (full_url, row_old["id"])
                    )
                    result["updated"].append((domain_name, full_url))
                else:
                    # Benar-benar baru → INSERT
                    c.execute(
                        "INSERT INTO domains (domain_name, full_url) VALUES (?,?)",
                        (domain_name, full_url)
                    )
                    result["added"].append((domain_name, full_url))

            except Exception as e:
                logger.error(f"Import error {full_url}: {e}")
                result["errors"].append(full_url)

    return result

def delete_domain_by_url(full_url: str):
    with _conn() as c:
        c.execute("DELETE FROM domains WHERE full_url=?", (full_url,))

def delete_domain(domain_name: str):
    with _conn() as c:
        c.execute("DELETE FROM domains WHERE domain_name=?", (domain_name,))

def delete_all_domains():
    """Hapus semua domain dan reset auto-increment ID."""
    with _conn() as c:
        c.execute("DELETE FROM domains")
        try:
            c.execute("DELETE FROM sqlite_sequence WHERE name='domains'")
        except Exception:
            pass
    logger.info("Semua domain dihapus.")

def update_domain_name(old_url: str, new_domain: str, new_url: str):
    with _conn() as c:
        c.execute(
            "UPDATE domains SET domain_name=?, full_url=? WHERE full_url=?",
            (new_domain, new_url, old_url)
        )

def update_status_by_id(domain_id: int, blocked: bool):
    with _conn() as c:
        c.execute(
            "UPDATE domains SET is_blocked=?, checked_at=? WHERE id=?",
            (1 if blocked else 0, now_wib(), domain_id)
        )

def update_status_by_name(domain_name: str, blocked: bool):
    with _conn() as c:
        c.execute(
            "UPDATE domains SET is_blocked=?, checked_at=? WHERE domain_name=?",
            (1 if blocked else 0, now_wib(), domain_name)
        )

def update_status_by_url(full_url: str, blocked: bool):
    with _conn() as c:
        c.execute(
            "UPDATE domains SET is_blocked=?, checked_at=? WHERE full_url=?",
            (1 if blocked else 0, now_wib(), full_url)
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
