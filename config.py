import sqlite3
from typing import List, Tuple

DB_NAME = "forcejoin.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            verified INTEGER DEFAULT 0,
            approved INTEGER DEFAULT 0
        )
    """)

    # Automatic migration for existing database
    cursor.execute("PRAGMA table_info(users)")

    columns = [
        row[1]
        for row in cursor.fetchall()
    ]

    if "approved" not in columns:
        cursor.execute(
            "ALTER TABLE users "
            "ADD COLUMN approved INTEGER DEFAULT 0"
        )

    # Force-join channels
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            invite_link TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# USERS
# ============================================================

def add_user(
    user_id: int,
    first_name: str,
    username: str,
):
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


def set_verified(
    user_id: int,
    verified: bool = True,
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE users
        SET verified = ?
        WHERE user_id = ?
        """,
        (
            1 if verified else 0,
            user_id,
        ),
    )

    conn.commit()
    conn.close()


def is_verified(user_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT verified
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    )

    result = cursor.fetchone()

    conn.close()

    return bool(
        result and result[0]
    )


# ============================================================
# APPROVAL SYSTEM
# ============================================================

def set_approval(
    user_id: int,
    status: int,
):
    """
    Approval status:
    0  = pending
    1  = approved
    -1 = rejected
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE users
        SET approved = ?
        WHERE user_id = ?
        """,
        (
            status,
            user_id,
        ),
    )

    conn.commit()
    conn.close()


def get_approval_status(
    user_id: int,
) -> int:

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT approved
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    )

    result = cursor.fetchone()

    conn.close()

    if not result:
        return 0

    return result[0]


def is_approved(
    user_id: int,
) -> bool:

    return get_approval_status(
        user_id
    ) == 1


def get_pending_users():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            user_id,
            first_name,
            username
        FROM users
        WHERE approved = 0
        ORDER BY user_id DESC
    """)

    users = cursor.fetchall()

    conn.close()

    return users


def get_pending_count() -> int:

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE approved = 0
        """
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count


def get_approved_count() -> int:

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE approved = 1
        """
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count


# ============================================================
# CHANNELS
# ============================================================

def add_channel(
    chat_id: str,
    title: str,
    invite_link: str,
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
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


def remove_channel(
    chat_id: str,
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM channels
        WHERE chat_id = ?
        """,
        (chat_id,),
    )

    conn.commit()
    conn.close()


def get_channels() -> List[Tuple]:

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            chat_id,
            title,
            invite_link
        FROM channels
        ORDER BY id ASC
    """)

    channels = cursor.fetchall()

    conn.close()

    return channels


# ============================================================
# STATISTICS
# ============================================================

def get_user_count() -> int:

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM users"
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count


def get_verified_count() -> int:

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE verified = 1
        """
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count
