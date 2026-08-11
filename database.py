import sqlite3
from typing import List, Tuple

DB_NAME = "forcejoin.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            verified INTEGER DEFAULT 0,
            approved INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            welcome_enabled INTEGER DEFAULT 1,
            welcome_text TEXT,
            goodbye_enabled INTEGER DEFAULT 0,
            goodbye_text TEXT,
            rules TEXT,
            warn_limit INTEGER DEFAULT 3
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS locks (
            chat_id INTEGER NOT NULL,
            lock_type TEXT NOT NULL,
            enabled INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, lock_type)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS federations (
            fed_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner_id INTEGER NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS federation_chats (
            fed_id TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            PRIMARY KEY (fed_id, chat_id),
            FOREIGN KEY (fed_id) REFERENCES federations(fed_id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS federation_bans (
            fed_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (fed_id, user_id),
            FOREIGN KEY (fed_id) REFERENCES federations(fed_id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS federation_mutes (
            fed_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (fed_id, user_id),
            FOREIGN KEY (fed_id) REFERENCES federations(fed_id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


# ---------------- users ----------------

def add_user(user_id: int, first_name: str, username: str):
    conn = get_connection()
    conn.execute("""
        INSERT INTO users (user_id, first_name, username)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            first_name = excluded.first_name,
            username = excluded.username
    """, (user_id, first_name, username))
    conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = get_connection()
    row = conn.execute(
        "SELECT user_id, first_name, username, verified, approved FROM users WHERE user_id=?",
        (user_id,),
    ).fetchone()
    conn.close()
    return row


def get_user_by_username(username: str):
    username = username.strip().lstrip("@").lower()
    conn = get_connection()
    row = conn.execute(
        "SELECT user_id, first_name, username, verified, approved FROM users WHERE LOWER(username)=?",
        (username,),
    ).fetchone()
    conn.close()
    return row


def set_verified(user_id: int, verified: bool = True):
    conn = get_connection()
    conn.execute("UPDATE users SET verified=? WHERE user_id=?", (1 if verified else 0, user_id))
    conn.commit()
    conn.close()


def set_approval(user_id: int, status: int):
    """0=Pending 1=Approved 2=Rejected 3=Revoked"""
    conn = get_connection()
    conn.execute("UPDATE users SET approved=? WHERE user_id=?", (status, user_id))
    conn.commit()
    conn.close()


def get_approval_status(user_id: int) -> int:
    conn = get_connection()
    row = conn.execute("SELECT approved FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def get_status_name(status: int) -> str:
    return {0: "🟡 PENDING", 1: "🟢 APPROVED", 2: "🔴 REJECTED", 3: "🚫 REVOKED"}.get(status, "❔ UNKNOWN")


def get_user_count() -> int:
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return n


def get_verified_count() -> int:
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM users WHERE verified=1").fetchone()[0]
    conn.close()
    return n


def get_count_by_status(status: int) -> int:
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM users WHERE approved=?", (status,)).fetchone()[0]
    conn.close()
    return n


# ---------------- group settings ----------------

DEFAULT_WELCOME = "🌹 Welcome {mention}!\n\nWelcome to {chatname}.\n\nPlease read the group rules and enjoy your stay! ❤️"
DEFAULT_GOODBYE = "👋 {name} has left the group.\n\nGoodbye!"
DEFAULT_RULES = "📜 Group Rules\n\n1. Be respectful.\n2. No spam.\n3. No unwanted links.\n4. No illegal content.\n5. Follow admin instructions."


def ensure_group(chat_id: int):
    conn = get_connection()
    conn.execute("""
        INSERT OR IGNORE INTO group_settings
            (chat_id, welcome_enabled, welcome_text, goodbye_enabled, goodbye_text, rules, warn_limit)
        VALUES (?, 1, ?, 0, ?, ?, 3)
    """, (chat_id, DEFAULT_WELCOME, DEFAULT_GOODBYE, DEFAULT_RULES))
    conn.commit()
    conn.close()


def get_group_settings(chat_id: int):
    ensure_group(chat_id)
    conn = get_connection()
    row = conn.execute("""
        SELECT welcome_enabled, welcome_text, goodbye_enabled, goodbye_text, rules, warn_limit
        FROM group_settings WHERE chat_id=?
    """, (chat_id,)).fetchone()
    conn.close()
    return row


def set_welcome_enabled(chat_id: int, enabled: bool):
    ensure_group(chat_id)
    conn = get_connection()
    conn.execute("UPDATE group_settings SET welcome_enabled=? WHERE chat_id=?", (1 if enabled else 0, chat_id))
    conn.commit()
    conn.close()


def set_goodbye_enabled(chat_id: int, enabled: bool):
    ensure_group(chat_id)
    conn = get_connection()
    conn.execute("UPDATE group_settings SET goodbye_enabled=? WHERE chat_id=?", (1 if enabled else 0, chat_id))
    conn.commit()
    conn.close()


def set_rules(chat_id: int, rules: str):
    ensure_group(chat_id)
    conn = get_connection()
    conn.execute("UPDATE group_settings SET rules=? WHERE chat_id=?", (rules, chat_id))
    conn.commit()
    conn.close()


def set_warn_limit(chat_id: int, limit: int):
    ensure_group(chat_id)
    limit = max(1, min(limit, 20))
    conn = get_connection()
    conn.execute("UPDATE group_settings SET warn_limit=? WHERE chat_id=?", (limit, chat_id))
    conn.commit()
    conn.close()
    return limit


# ---------------- warnings ----------------

def get_warns(chat_id: int, user_id: int) -> int:
    conn = get_connection()
    row = conn.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    conn.close()
    return row[0] if row else 0


def add_warn(chat_id: int, user_id: int) -> int:
    new_count = get_warns(chat_id, user_id) + 1
    conn = get_connection()
    conn.execute("""
        INSERT INTO warnings (chat_id, user_id, count) VALUES (?, ?, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET count=excluded.count
    """, (chat_id, user_id, new_count))
    conn.commit()
    conn.close()
    return new_count


def reset_warns(chat_id: int, user_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()
    conn.close()


# ---------------- locks ----------------

LOCK_TYPES = ["photo", "video", "sticker", "gif", "url", "forward", "document", "voice", "poll"]


def set_lock(chat_id: int, lock_type: str, enabled: bool):
    conn = get_connection()
    conn.execute("""
        INSERT INTO locks (chat_id, lock_type, enabled) VALUES (?, ?, ?)
        ON CONFLICT(chat_id, lock_type) DO UPDATE SET enabled=excluded.enabled
    """, (chat_id, lock_type, 1 if enabled else 0))
    conn.commit()
    conn.close()


def is_locked(chat_id: int, lock_type: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT enabled FROM locks WHERE chat_id=? AND lock_type=?", (chat_id, lock_type)
    ).fetchone()
    conn.close()
    return bool(row and row[0])


def toggle_lock(chat_id: int, lock_type: str) -> bool:
    """Flips the lock and returns the new state."""
    new_state = not is_locked(chat_id, lock_type)
    set_lock(chat_id, lock_type, new_state)
    return new_state


# ---------------- federations ----------------

def create_federation(fed_id: str, name: str, owner_id: int):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO federations (fed_id, name, owner_id) VALUES (?, ?, ?)",
        (fed_id, name, owner_id),
    )
    conn.commit()
    conn.close()


def get_federation(fed_id: str):
    conn = get_connection()
    row = conn.execute("SELECT fed_id, name, owner_id FROM federations WHERE fed_id=?", (fed_id,)).fetchone()
    conn.close()
    return row


def get_chat_federation(chat_id: int):
    conn = get_connection()
    row = conn.execute("""
        SELECT f.fed_id, f.name, f.owner_id
        FROM federations f
        JOIN federation_chats fc ON f.fed_id = fc.fed_id
        WHERE fc.chat_id=? LIMIT 1
    """, (chat_id,)).fetchone()
    conn.close()
    return row


def add_fed_chat(fed_id: str, chat_id: int):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO federation_chats (fed_id, chat_id) VALUES (?, ?)", (fed_id, chat_id))
    conn.commit()
    conn.close()


def get_federation_chats(fed_id: str) -> List[int]:
    conn = get_connection()
    rows = conn.execute("SELECT chat_id FROM federation_chats WHERE fed_id=?", (fed_id,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def fed_ban(fed_id: str, user_id: int):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO federation_bans (fed_id, user_id) VALUES (?, ?)", (fed_id, user_id))
    conn.commit()
    conn.close()


def fed_unban(fed_id: str, user_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM federation_bans WHERE fed_id=? AND user_id=?", (fed_id, user_id))
    conn.commit()
    conn.close()


def fed_mute(fed_id: str, user_id: int):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO federation_mutes (fed_id, user_id) VALUES (?, ?)", (fed_id, user_id))
    conn.commit()
    conn.close()


def fed_unmute(fed_id: str, user_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM federation_mutes WHERE fed_id=? AND user_id=?", (fed_id, user_id))
    conn.commit()
    conn.close()
