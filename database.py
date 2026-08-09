import sqlite3
from typing import List, Tuple

DB_NAME = "forcejoin.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ============================================================
# INITIALIZE DATABASE
# ============================================================

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Existing users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            verified INTEGER DEFAULT 0,
            approved INTEGER DEFAULT 0
        )
    """)

    # Existing channels
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            invite_link TEXT NOT NULL
        )
    """)

    # Group settings
    cursor.execute("""
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

    # Warnings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    # Locks
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS locks (
            chat_id INTEGER NOT NULL,
            lock_type TEXT NOT NULL,
            enabled INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, lock_type)
        )
    """)

    # Federation
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS federations (
            fed_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner_id INTEGER NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS federation_chats (
            fed_id TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            PRIMARY KEY (fed_id, chat_id),
            FOREIGN KEY (fed_id)
                REFERENCES federations(fed_id)
                ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS federation_bans (
            fed_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (fed_id, user_id),
            FOREIGN KEY (fed_id)
                REFERENCES federations(fed_id)
                ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS federation_mutes (
            fed_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (fed_id, user_id),
            FOREIGN KEY (fed_id)
                REFERENCES federations(fed_id)
                ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# USERS
# ============================================================

def add_user(user_id: int, first_name: str, username: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO users (
            user_id,
            first_name,
            username
        )
        VALUES (?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            first_name = excluded.first_name,
            username = excluded.username
    """, (
        user_id,
        first_name,
        username,
    ))

    conn.commit()
    conn.close()


def set_verified(user_id: int, verified: bool = True):
    conn = get_connection()
    conn.execute("""
        UPDATE users
        SET verified = ?
        WHERE user_id = ?
    """, (
        1 if verified else 0,
        user_id,
    ))
    conn.commit()
    conn.close()


def is_verified(user_id: int) -> bool:
    conn = get_connection()
    result = conn.execute("""
        SELECT verified
        FROM users
        WHERE user_id = ?
    """, (user_id,)).fetchone()

    conn.close()

    return bool(result and result[0])


# ============================================================
# APPROVAL
# ============================================================

def set_approval(user_id: int, status: int):
    conn = get_connection()

    conn.execute("""
        UPDATE users
        SET approved = ?
        WHERE user_id = ?
    """, (
        status,
        user_id,
    ))

    conn.commit()
    conn.close()


def get_approval_status(user_id: int) -> int:
    conn = get_connection()

    result = conn.execute("""
        SELECT approved
        FROM users
        WHERE user_id = ?
    """, (user_id,)).fetchone()

    conn.close()

    if not result:
        return 0

    return result[0]


def is_approved(user_id: int) -> bool:
    return get_approval_status(user_id) == 1


def get_pending_users():
    conn = get_connection()

    users = conn.execute("""
        SELECT user_id, first_name, username
        FROM users
        WHERE approved = 0
        ORDER BY user_id DESC
    """).fetchall()

    conn.close()
    return users


def get_pending_count() -> int:
    conn = get_connection()
    count = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE approved = 0
    """).fetchone()[0]

    conn.close()
    return count


def get_approved_count() -> int:
    conn = get_connection()
    count = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE approved = 1
    """).fetchone()[0]

    conn.close()
    return count


# ============================================================
# CHANNELS
# ============================================================

def add_channel(chat_id: str, title: str, invite_link: str):
    conn = get_connection()

    conn.execute("""
        INSERT OR REPLACE INTO channels (
            chat_id,
            title,
            invite_link
        )
        VALUES (?, ?, ?)
    """, (
        chat_id,
        title,
        invite_link,
    ))

    conn.commit()
    conn.close()


def remove_channel(chat_id: str):
    conn = get_connection()

    conn.execute("""
        DELETE FROM channels
        WHERE chat_id = ?
    """, (chat_id,))

    conn.commit()
    conn.close()


def get_channels() -> List[Tuple]:
    conn = get_connection()

    channels = conn.execute("""
        SELECT chat_id, title, invite_link
        FROM channels
        ORDER BY id ASC
    """).fetchall()

    conn.close()
    return channels


# ============================================================
# STATISTICS
# ============================================================

def get_user_count() -> int:
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    conn.close()
    return count


def get_verified_count() -> int:
    conn = get_connection()

    count = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE verified = 1
    """).fetchone()[0]

    conn.close()
    return count


# ============================================================
# GROUP SETTINGS
# ============================================================

DEFAULT_WELCOME = (
    "🌹 <b>Welcome {mention}!</b>\n\n"
    "Welcome to <b>{chatname}</b>.\n\n"
    "Please read the group rules and enjoy your stay! ❤️"
)

DEFAULT_GOODBYE = (
    "👋 <b>{name}</b> has left the group.\n\n"
    "Goodbye!"
)

DEFAULT_RULES = (
    "📜 <b>Group Rules</b>\n\n"
    "1. Be respectful.\n"
    "2. No spam.\n"
    "3. No unwanted links.\n"
    "4. No illegal content.\n"
    "5. Follow admin instructions."
)


def ensure_group(chat_id: int):
    conn = get_connection()

    conn.execute("""
        INSERT OR IGNORE INTO group_settings (
            chat_id,
            welcome_enabled,
            welcome_text,
            goodbye_enabled,
            goodbye_text,
            rules,
            warn_limit
        )
        VALUES (?, 1, ?, 0, ?, ?, 3)
    """, (
        chat_id,
        DEFAULT_WELCOME,
        DEFAULT_GOODBYE,
        DEFAULT_RULES,
    ))

    conn.commit()
    conn.close()


def get_group_settings(chat_id: int):
    ensure_group(chat_id)

    conn = get_connection()

    result = conn.execute("""
        SELECT
            welcome_enabled,
            welcome_text,
            goodbye_enabled,
            goodbye_text,
            rules,
            warn_limit
        FROM group_settings
        WHERE chat_id = ?
    """, (chat_id,)).fetchone()

    conn.close()
    return result


def set_welcome(chat_id: int, enabled: bool, text=None):
    ensure_group(chat_id)

    conn = get_connection()

    if text is None:
        conn.execute("""
            UPDATE group_settings
            SET welcome_enabled = ?
            WHERE chat_id = ?
        """, (
            1 if enabled else 0,
            chat_id,
        ))
    else:
        conn.execute("""
            UPDATE group_settings
            SET welcome_enabled = ?, welcome_text = ?
            WHERE chat_id = ?
        """, (
            1 if enabled else 0,
            text,
            chat_id,
        ))

    conn.commit()
    conn.close()


def set_goodbye(chat_id: int, enabled: bool):
    ensure_group(chat_id)

    conn = get_connection()

    conn.execute("""
        UPDATE group_settings
        SET goodbye_enabled = ?
        WHERE chat_id = ?
    """, (
        1 if enabled else 0,
        chat_id,
    ))

    conn.commit()
    conn.close()


def set_rules(chat_id: int, rules: str):
    ensure_group(chat_id)

    conn = get_connection()

    conn.execute("""
        UPDATE group_settings
        SET rules = ?
        WHERE chat_id = ?
    """, (
        rules,
        chat_id,
    ))

    conn.commit()
    conn.close()


# ============================================================
# WARNINGS
# ============================================================

def get_warns(chat_id: int, user_id: int) -> int:
    conn = get_connection()

    result = conn.execute("""
        SELECT count
        FROM warnings
        WHERE chat_id = ? AND user_id = ?
    """, (
        chat_id,
        user_id,
    )).fetchone()

    conn.close()

    return result[0] if result else 0


def add_warn(chat_id: int, user_id: int) -> int:
    current = get_warns(chat_id, user_id)
    new_count = current + 1

    conn = get_connection()

    conn.execute("""
        INSERT INTO warnings (
            chat_id,
            user_id,
            count
        )
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET count = excluded.count
    """, (
        chat_id,
        user_id,
        new_count,
    ))

    conn.commit()
    conn.close()

    return new_count


def reset_warns(chat_id: int, user_id: int):
    conn = get_connection()

    conn.execute("""
        DELETE FROM warnings
        WHERE chat_id = ? AND user_id = ?
    """, (
        chat_id,
        user_id,
    ))

    conn.commit()
    conn.close()


# ============================================================
# LOCKS
# ============================================================

def set_lock(chat_id: int, lock_type: str, enabled: bool):
    conn = get_connection()

    conn.execute("""
        INSERT INTO locks (
            chat_id,
            lock_type,
            enabled
        )
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id, lock_type)
        DO UPDATE SET enabled = excluded.enabled
    """, (
        chat_id,
        lock_type,
        1 if enabled else 0,
    ))

    conn.commit()
    conn.close()


def is_locked(chat_id: int, lock_type: str) -> bool:
    conn = get_connection()

    result = conn.execute("""
        SELECT enabled
        FROM locks
        WHERE chat_id = ? AND lock_type = ?
    """, (
        chat_id,
        lock_type,
    )).fetchone()

    conn.close()

    return bool(result and result[0])


def get_locks(chat_id: int):
    conn = get_connection()

    rows = conn.execute("""
        SELECT lock_type
        FROM locks
        WHERE chat_id = ? AND enabled = 1
        ORDER BY lock_type
    """, (chat_id,)).fetchall()

    conn.close()

    return [row[0] for row in rows]


# ============================================================
# FEDERATION
# ============================================================

def create_federation(fed_id: str, name: str, owner_id: int):
    conn = get_connection()

    conn.execute("""
        INSERT OR REPLACE INTO federations (
            fed_id,
            name,
            owner_id
        )
        VALUES (?, ?, ?)
    """, (
        fed_id,
        name,
        owner_id,
    ))

    conn.commit()
    conn.close()


def get_federation(fed_id: str):
    conn = get_connection()

    result = conn.execute("""
        SELECT fed_id, name, owner_id
        FROM federations
        WHERE fed_id = ?
    """, (fed_id,)).fetchone()

    conn.close()
    return result


def add_fed_chat(fed_id: str, chat_id: int):
    conn = get_connection()

    conn.execute("""
        INSERT OR IGNORE INTO federation_chats (
            fed_id,
            chat_id
        )
        VALUES (?, ?)
    """, (
        fed_id,
        chat_id,
    ))

    conn.commit()
    conn.close()


def fed_ban(fed_id: str, user_id: int):
    conn = get_connection()

    conn.execute("""
        INSERT OR IGNORE INTO federation_bans (
            fed_id,
            user_id
        )
        VALUES (?, ?)
    """, (
        fed_id,
        user_id,
    ))

    conn.commit()
    conn.close()


def fed_unban(fed_id: str, user_id: int):
    conn = get_connection()

    conn.execute("""
        DELETE FROM federation_bans
        WHERE fed_id = ? AND user_id = ?
    """, (
        fed_id,
        user_id,
    ))

    conn.commit()
    conn.close()


def is_fed_banned(fed_id: str, user_id: int) -> bool:
    conn = get_connection()

    result = conn.execute("""
        SELECT 1
        FROM federation_bans
        WHERE fed_id = ? AND user_id = ?
    """, (
        fed_id,
        user_id,
    )).fetchone()

    conn.close()

    return bool(result)


def fed_mute(fed_id: str, user_id: int):
    conn = get_connection()

    conn.execute("""
        INSERT OR IGNORE INTO federation_mutes (
            fed_id,
            user_id
        )
        VALUES (?, ?)
    """, (
        fed_id,
        user_id,
    ))

    conn.commit()
    conn.close()


def fed_unmute(fed_id: str, user_id: int):
    conn = get_connection()

    conn.execute("""
        DELETE FROM federation_mutes
        WHERE fed_id = ? AND user_id = ?
    """, (
        fed_id,
        user_id,
    ))

    conn.commit()
    conn.close()


def is_fed_muted(fed_id: str, user_id: int) -> bool:
    conn = get_connection()

    result = conn.execute("""
        SELECT 1
        FROM federation_mutes
        WHERE fed_id = ? AND user_id = ?
    """, (
        fed_id,
        user_id,
    )).fetchone()

    conn.close()

    return bool(result)
