import sqlite3
from typing import List, Tuple

DB_NAME = "forcejoin.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            invite_link TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            verified INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


def add_user(user_id: int, first_name: str, username: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO users (user_id, first_name, username)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            first_name = excluded.first_name,
            username = excluded.username
    """, (user_id, first_name, username))

    conn.commit()
    conn.close()


def set_verified(user_id: int, verified: bool = True):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE users SET verified = ? WHERE user_id = ?",
        (1 if verified else 0, user_id)
    )

    conn.commit()
    conn.close()


def is_verified(user_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT verified FROM users WHERE user_id = ?",
        (user_id,)
    )

    result = cursor.fetchone()
    conn.close()

    return bool(result and result[0])


def add_channel(chat_id: str, title: str, invite_link: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO channels
        (chat_id, title, invite_link)
        VALUES (?, ?, ?)
    """, (chat_id, title, invite_link))

    conn.commit()
    conn.close()


def remove_channel(chat_id: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM channels WHERE chat_id = ?",
        (chat_id,)
    )

    conn.commit()
    conn.close()


def get_channels() -> List[Tuple]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT chat_id, title, invite_link
        FROM channels
        ORDER BY id ASC
    """)

    channels = cursor.fetchall()
    conn.close()

    return channels


def get_user_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]

    conn.close()
    return count


def get_verified_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE verified = 1"
    )

    count = cursor.fetchone()[0]

    conn.close()
    return count
