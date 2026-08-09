```python
import os
import sqlite3
import logging
import uuid
from html import escape

from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler,
)


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

DB_NAME = "forcejoin.db"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing in .env")

if not OWNER_ID:
    raise ValueError("OWNER_ID is missing in .env")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# APPROVAL STATUS
# ============================================================

PENDING = 0
APPROVED = 1
REJECTED = 2
REVOKED = 3


# ============================================================
# FORCE JOIN CHANNELS
# ============================================================

FORCE_JOIN_CHANNELS = [
    {
        "id": -1003998560024,
        "title": "Channel 1",
        "link": "https://t.me/+RsAsljvxgWZkNzg1",
    },
    {
        "id": -1004077604887,
        "title": "Channel 2",
        "link": "https://t.me/Il_Ravan_bhai_ll",
    },
]


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():

    conn = get_connection()
    cur = conn.cursor()

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            verified INTEGER DEFAULT 0,
            approved INTEGER DEFAULT 0
        )
    """)

    # --------------------------------------------------------
    # CHANNELS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            invite_link TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # GROUP SETTINGS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # WARNINGS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY(chat_id, user_id)
        )
    """)

    # --------------------------------------------------------
    # LOCKS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS locks (
            chat_id INTEGER NOT NULL,
            lock_type TEXT NOT NULL,
            enabled INTEGER DEFAULT 0,
            PRIMARY KEY(chat_id, lock_type)
        )
    """)

    # --------------------------------------------------------
    # FEDERATIONS
    # --------------------------------------------------------

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
            PRIMARY KEY(fed_id, chat_id),
            FOREIGN KEY(fed_id)
                REFERENCES federations(fed_id)
                ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS federation_bans (
            fed_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(fed_id, user_id),
            FOREIGN KEY(fed_id)
                REFERENCES federations(fed_id)
                ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS federation_mutes (
            fed_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(fed_id, user_id),
            FOREIGN KEY(fed_id)
                REFERENCES federations(fed_id)
                ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# USER DATABASE
# ============================================================

def save_user(user):

    conn = get_connection()

    conn.execute("""
        INSERT INTO users(
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
        user.id,
        user.first_name or "",
        user.username or "",
    ))

    conn.commit()
    conn.close()


def get_user(user_id):

    conn = get_connection()

    row = conn.execute("""
        SELECT
            user_id,
            first_name,
            username,
            verified,
            approved
        FROM users
        WHERE user_id = ?
    """, (user_id,)).fetchone()

    conn.close()

    return row


def get_user_by_username(username):

    username = username.strip().lstrip("@").lower()

    conn = get_connection()

    row = conn.execute("""
        SELECT
            user_id,
            first_name,
            username,
            verified,
            approved
        FROM users
        WHERE LOWER(username) = ?
        LIMIT 1
    """, (username,)).fetchone()

    conn.close()

    return row


def set_verified(user_id, verified=True):

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


def get_approval_status(user_id):

    conn = get_connection()

    row = conn.execute("""
        SELECT approved
        FROM users
        WHERE user_id = ?
    """, (user_id,)).fetchone()

    conn.close()

    if not row:
        return PENDING

    return int(row[0])


def set_approval(user_id, status):

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


def status_name(status):

    return {
        PENDING: "🟡 Pending",
        APPROVED: "🟢 Approved",
        REJECTED: "🔴 Rejected",
        REVOKED: "🚫 Revoked",
    }.get(status, "❓ Unknown")


# ============================================================
# STATISTICS
# ============================================================

def get_user_count():

    conn = get_connection()

    value = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    conn.close()

    return value


def get_verified_count():

    conn = get_connection()

    value = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE verified = 1
    """).fetchone()[0]

    conn.close()

    return value


def get_approved_count():

    conn = get_connection()

    value = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE approved = 1
    """).fetchone()[0]

    conn.close()

    return value


def get_pending_count():

    conn = get_connection()

    value = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE approved = 0
    """).fetchone()[0]

    conn.close()

    return value


def get_rejected_count():

    conn = get_connection()

    value = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE approved = 2
    """).fetchone()[0]

    conn.close()

    return value


def get_revoked_count():

    conn = get_connection()

    value = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE approved = 3
    """).fetchone()[0]

    conn.close()

    return value


# ============================================================
# GROUP SETTINGS
# ============================================================

DEFAULT_WELCOME = (
    "🌹 Welcome {mention}!\n\n"
    "Welcome to {chatname}.\n\n"
    "Please read the group rules and enjoy your stay! ❤️"
)

DEFAULT_GOODBYE = (
    "👋 {name} has left the group.\n\n"
    "Goodbye!"
)

DEFAULT_RULES = (
    "📜 Group Rules\n\n"
    "1. Be respectful.\n"
    "2. No spam.\n"
    "3. No unwanted links.\n"
    "4. No illegal content.\n"
    "5. Follow admin instructions."
)


def ensure_group(chat_id):

    conn = get_connection()

    conn.execute("""
        INSERT OR IGNORE INTO group_settings(
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


def get_group_settings(chat_id):

    ensure_group(chat_id)

    conn = get_connection()

    row = conn.execute("""
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

    return row


def set_welcome(chat_id, enabled):

    ensure_group(chat_id)

    conn = get_connection()

    conn.execute("""
        UPDATE group_settings
        SET welcome_enabled = ?
        WHERE chat_id = ?
    """, (
        1 if enabled else 0,
        chat_id,
    ))

    conn.commit()
    conn.close()


def set_goodbye(chat_id, enabled):

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


def set_rules(chat_id, rules):

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

def get_warns(chat_id, user_id):

    conn = get_connection()

    row = conn.execute("""
        SELECT count
        FROM warnings
        WHERE chat_id = ?
        AND user_id = ?
    """, (
        chat_id,
        user_id,
    )).fetchone()

    conn.close()

    return row[0] if row else 0


def add_warn(chat_id, user_id):

    count = get_warns(
        chat_id,
        user_id,
    ) + 1

    conn = get_connection()

    conn.execute("""
        INSERT INTO warnings(
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
        count,
    ))

    conn.commit()
    conn.close()

    return count


def reset_warns(chat_id, user_id):

    conn = get_connection()

    conn.execute("""
        DELETE FROM warnings
        WHERE chat_id = ?
        AND user_id = ?
    """, (
        chat_id,
        user_id,
    ))

    conn.commit()
    conn.close()


# ============================================================
# LOCKS
# ============================================================

def set_lock(chat_id, lock_type, enabled):

    conn = get_connection()

    conn.execute("""
        INSERT INTO locks(
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


# ============================================================
# FEDERATION DATABASE
# ============================================================

def create_federation(
    fed_id,
    name,
    owner_id,
):

    conn = get_connection()

    conn.execute("""
        INSERT INTO federations(
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


def get_federation(fed_id):

    conn = get_connection()

    row = conn.execute("""
        SELECT
            fed_id,
            name,
            owner_id
        FROM federations
        WHERE fed_id = ?
    """, (fed_id,)).fetchone()

    conn.close()

    return row


def get_chat_federation(chat_id):

    conn = get_connection()

    row = conn.execute("""
        SELECT
            f.fed_id,
            f.name,
            f.owner_id
        FROM federations f
        INNER JOIN federation_chats fc
            ON f.fed_id = fc.fed_id
        WHERE fc.chat_id = ?
        LIMIT 1
    """, (chat_id,)).fetchone()

    conn.close()

    return row


def add_fed_chat(
    fed_id,
    chat_id,
):

    conn = get_connection()

    conn.execute("""
        INSERT OR IGNORE INTO federation_chats(
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


def remove_fed_chat(
    fed_id,
    chat_id,
):

    conn = get_connection()

    conn.execute("""
        DELETE FROM federation_chats
        WHERE fed_id = ?
        AND chat_id = ?
    """, (
        fed_id,
        chat_id,
    ))

    conn.commit()
    conn.close()


def get_federation_chats(fed_id):

    conn = get_connection()

    rows = conn.execute("""
        SELECT chat_id
        FROM federation_chats
        WHERE fed_id = ?
    """, (fed_id,)).fetchall()

    conn.close()

    return [row[0] for row in rows]


def fed_ban(
    fed_id,
    user_id,
):

    conn = get_connection()

    conn.execute("""
        INSERT OR IGNORE INTO federation_bans(
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


def fed_unban(
    fed_id,
    user_id,
):

    conn = get_connection()

    conn.execute("""
        DELETE FROM federation_bans
        WHERE fed_id = ?
        AND user_id = ?
    """, (
        fed_id,
        user_id,
    ))

    conn.commit()
    conn.close()


def is_fed_banned(
    fed_id,
    user_id,
):

    conn = get_connection()

    row = conn.execute("""
        SELECT 1
        FROM federation_bans
        WHERE fed_id = ?
        AND user_id = ?
    """, (
        fed_id,
        user_id,
    )).fetchone()

    conn.close()

    return bool(row)


def fed_mute(
    fed_id,
    user_id,
):

    conn = get_connection()

    conn.execute("""
        INSERT OR IGNORE INTO federation_mutes(
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


def fed_unmute(
    fed_id,
    user_id,
):

    conn = get_connection()

    conn.execute("""
        DELETE FROM federation_mutes
        WHERE fed_id = ?
        AND user_id = ?
    """, (
        fed_id,
        user_id,
    ))

    conn.commit()
    conn.close()


# ============================================================
# HELPERS
# ============================================================

def mention(user):

    return (
        f'<a href="tg://user?id={user.id}">'
        f'{escape(user.first_name or "User")}'
        f'</a>'
    )


def username_text(user):

    if user.username:
        return "@" + escape(user.username)

    return "No username"


def is_owner(user_id):

    return user_id == OWNER_ID


# ============================================================
# ADMIN CHECK
# ============================================================

async def is_admin(
    update,
    user_id=None,
):

    chat = update.effective_chat

    if not chat:
        return False

    if user_id is None:

        if not update.effective_user:
            return False

        user_id = update.effective_user.id

    if user_id == OWNER_ID:
        return True

    if chat.type == ChatType.PRIVATE:
        return False

    try:

        member = await context_bot_member(
            update,
            user_id,
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception:
        return False


async def context_bot_member(
    update,
    user_id,
):

    return await update.get_bot().get_chat_member(
        update.effective_chat.id,
        user_id,
    )


# ============================================================
# FORCE JOIN
# ============================================================

async def check_channel(
    context,
    user_id,
    channel_id,
):

    try:

        member = await context.bot.get_chat_member(
            channel_id,
            user_id,
        )

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            ChatMemberStatus.RESTRICTED,
        )

    except Exception as e:

        logger.warning(
            "Channel membership check failed: %s",
            e,
        )

        return False


async def is_force_joined(
    context,
    user_id,
):

    missing = []

    for channel in FORCE_JOIN_CHANNELS:

        joined = await check_channel(
            context,
            user_id,
            channel["id"],
        )

        if not joined:
            missing.append(channel)

    return (
        len(missing) == 0,
        missing,
    )


def force_join_keyboard():

    rows = []

    for index, channel in enumerate(
        FORCE_JOIN_CHANNELS,
        start=1,
    ):

        rows.append([
            InlineKeyboardButton(
                f"📢 Join Channel {index}",
                url=channel["link"],
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "✅ I've Joined",
            callback_data="verify_join",
        )
    ])

    return InlineKeyboardMarkup(rows)


async def force_join_message(
    update,
    context,
):

    text = (
        "🔐 <b>ACCESS LOCKED</b>\n\n"
        "You must join all required channels "
        "before using this bot.\n\n"
        "Join both channels and then press:\n\n"
        "✅ <b>I've Joined</b>"
    )

    keyboard = force_join_keyboard()

    if update.callback_query:

        await update.callback_query.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    else:

        await update.effective_message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )


# ============================================================
# APPROVAL REQUEST
# ============================================================

def approval_keyboard(user_id):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"approve:{user_id}",
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"reject:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Reapprove",
                callback_data=f"reapprove:{user_id}",
            ),
            InlineKeyboardButton(
                "🚫 Revoke",
                callback_data=f"revoke:{user_id}",
            ),
        ],
    ])


async def send_approval_request(
    context,
    user,
):

    status = get_approval_status(user.id)

    text = (
        "🔔 <b>ACCESS REQUEST</b>\n\n"
        f"👤 Name: {mention(user)}\n"
        f"🔗 Username: {username_text(user)}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"📌 Status: <b>{status_name(status)}</b>\n\n"
        "The user completed channel verification "
        "and is requesting access."
    )

    try:

        await context.bot.send_message(
            OWNER_ID,
            text,
            reply_markup=approval_keyboard(user.id),
            parse_mode="HTML",
        )

        return True

    except Exception as e:

        logger.error(
            "Approval notification failed: %s",
            e,
        )

        return False


# ============================================================
# START
# ============================================================

async def start(
    update,
    context,
):

    user = update.effective_user

    if not user:
        return

    save_user(user)

    if is_owner(user.id):

        await update.effective_message.reply_text(
            "👑 <b>OWNER ACCESS</b>\n\n"
            "🛡️ JoinGuard Bot is running.\n\n"
            "Use /panel for the control panel.",
            parse_mode="HTML",
        )

        return

    status = get_approval_status(user.id)

    if status == APPROVED:

        await update.effective_message.reply_text(
            f"👋 Welcome {mention(user)}!\n\n"
            "🟢 Your access is approved.\n\n"
            "Use /help for commands.",
            parse_mode="HTML",
        )

        return

    joined, missing = await is_force_joined(
        context,
        user.id,
    )

    if not joined:

        await force_join_message(
            update,
            context,
        )

        return

    set_verified(
        user.id,
        True,
    )

    await send_approval_request(
        context,
        user,
    )

    await update.effective_message.reply_text(
        "✅ <b>CHANNEL VERIFICATION COMPLETE</b>\n\n"
        "⏳ Your access is waiting for owner approval.\n\n"
        "🔔 Your request has been sent.",
        parse_mode="HTML",
    )


# ============================================================
# VERIFY JOIN
# ============================================================

async def verify_join(
    update,
    context,
):

    query = update.callback_query
    user = query.from_user

    await query.answer()

    save_user(user)

    status = get_approval_status(user.id)

    if status == APPROVED:

        await query.message.edit_text(
            "🟢 <b>Already Approved</b>\n\n"
            "You already have access to the bot.",
            parse_mode="HTML",
        )

        return

    joined, missing = await is_force_joined(
        context,
        user.id,
    )

    if not joined:

        names = "\n".join(
            f"📢 {escape(x['title'])}"
            for x in missing
        )

        await query.answer(
            "❌ You have not joined all channels.",
            show_alert=True,
        )

        await query.message.edit_text(
            "❌ <b>Verification Failed</b>\n\n"
            "You still need to join:\n\n"
            f"{names}\n\n"
            "After joining, press "
            "✅ <b>I've Joined</b> again.",
            reply_markup=force_join_keyboard(),
            parse_mode="HTML",
        )

        return

    set_verified(
        user.id,
        True,
    )

    await send_approval_request(
        context,
        user,
    )

    await query.message.edit_text(
        "✅ <b>VERIFICATION SUCCESSFUL</b>\n\n"
        "You joined all required channels.\n\n"
        "⏳ <b>Access Pending Approval</b>\n\n"
        "🔔 Your request has been sent to the owner.",
        parse_mode="HTML",
    )


# ============================================================
# APPROVAL CALLBACK
# ============================================================

async def approval_callback(
    update,
    context,
):

    query = update.callback_query

    if query.from_user.id != OWNER_ID:

        await query.answer(
            "❌ Owner only.",
            show_alert=True,
        )

        return

    try:

        action, user_id_text = query.data.split(":")

        user_id = int(user_id_text)

    except Exception:

        await query.answer(
            "❌ Invalid request.",
            show_alert=True,
        )

        return

    user = get_user(user_id)

    if not user:

        await query.answer(
            "❌ User not found.",
            show_alert=True,
        )

        return

    if action == "approve":
        status = APPROVED

    elif action == "reject":
        status = REJECTED

    elif action == "reapprove":
        status = APPROVED

    elif action == "revoke":
        status = REVOKED

    else:
        return

    set_approval(
        user_id,
        status,
    )

    await query.answer(
        "Updated successfully."
    )

    text = (
        "👤 <b>USER ACCESS CONTROL</b>\n\n"
        f"👤 Name: <b>{escape(user[1] or 'User')}</b>\n"
        f"🔗 Username: @{escape(user[2]) if user[2] else 'none'}\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"📌 Status: <b>{status_name(status)}</b>"
    )

    await query.message.edit_text(
        text,
        reply_markup=approval_keyboard(user_id),
        parse_mode="HTML",
    )

    try:

        if status == APPROVED:

            await context.bot.send_message(
                user_id,
                "🎉 <b>ACCESS APPROVED</b>\n\n"
                "The owner approved your access.\n\n"
                "🔓 You can now use the bot.",
                parse_mode="HTML",
            )

        elif status == REJECTED:

            await context.bot.send_message(
                user_id,
                "❌ <b>ACCESS REJECTED</b>\n\n"
                "Your access request was rejected.\n\n"
                "You may request access again later.",
                parse_mode="HTML",
            )

        elif status == REVOKED:

            await context.bot.send_message(
                user_id,
                "🚫 <b>ACCESS REVOKED</b>\n\n"
                "Your access has been revoked.\n\n"
                "Join the required channels again and "
                "press ✅ I've Joined to request access again.",
                parse_mode="HTML",
            )

    except Exception:
        pass


# ============================================================
# OWNER APPROVAL COMMANDS
# ============================================================

async def find_command_user(
    update,
    context,
):

    if (
        update.message
        and update.message.reply_to_message
    ):

        return update.message.reply_to_message.from_user

    if not context.args:
        return None

    value = context.args[0]

    if value.lstrip("-").isdigit():

        try:

            member = await context.bot.get_chat_member(
                update.effective_chat.id,
                int(value),
            )

            return member.user

        except Exception:
            row = get_user(int(value))

            if not row:
                return None

            class User:
                pass

            u = User()
            u.id = row[0]
            u.first_name = row[1]
            u.username = row[2]

            return u

    row = get_user_by_username(value)

    if not row:
        return None

    class User:
        pass

    u = User()
    u.id = row[0]
    u.first_name = row[1]
    u.username = row[2]

    return u


async def approve_command(
    update,
    context,
):

    if not is_owner(update.effective_user.id):

        await update.effective_message.reply_text(
            "❌ Owner only."
        )

        return

    user = await find_command_user(
        update,
        context,
    )

    if not user:

        await update.effective_message.reply_text(
            "Usage:\n/approve @username"
        )

        return

    save_user(user)
    set_approval(user.id, APPROVED)

    await update.effective_message.reply_text(
        f"✅ <b>Approved</b>\n\n"
        f"👤 {mention(user)}\n"
        f"🆔 <code>{user.id}</code>",
        parse_mode="HTML",
    )


async def reject_command(
    update,
    context,
):

    if not is_owner(update.effective_user.id):

        await update.effective_message.reply_text(
            "❌ Owner only."
        )

        return

    user = await find_command_user(
        update,
        context,
    )

    if not user:

        await update.effective_message.reply_text(
            "Usage:\n/reject @username"
        )

        return

    save_user(user)
    set_approval(user.id, REJECTED)

    await update.effective_message.reply_text(
        f"❌ <b>Rejected</b>\n\n"
        f"👤 {mention(user)}\n"
        f"🆔 <code>{user.id}</code>",
        parse_mode="HTML",
    )


async def reapprove_command(
    update,
    context,
):

    if not is_owner(update.effective_user.id):

        await update.effective_message.reply_text(
            "❌ Owner only."
        )

        return

    user = await find_command_user(
        update,
        context,
    )

    if not user:

        await update.effective_message.reply_text(
            "Usage:\n/reapprove @username"
        )

        return

    save_user(user)
    set_approval(user.id, APPROVED)

    await update.effective_message.reply_text(
        f"🔄 <b>Reapproved</b>\n\n"
        f"👤 {mention(user)}\n"
        f"🆔 <code>{user.id}</code>",
        parse_mode="HTML",
    )


async def revoke_command(
    update,
    context,
):

    if not is_owner(update.effective_user.id):

        await update.effective_message.reply_text(
            "❌ Owner only."
        )

        return

    user = await find_command_user(
        update,
        context,
    )

    if not user:

        await update.effective_message.reply_text(
            "Usage:\n/revoke @username"
        )

        return

    save_user(user)
    set_approval(user.id, REVOKED)

    await update.effective_message.reply_text(
        f"🚫 <b>Access Revoked</b>\n\n"
        f"👤 {mention(user)}\n"
        f"🆔 <code>{user.id}</code>",
        parse_mode="HTML",
    )


# ============================================================
# HELP
# ============================================================

async def help_command(
    update,
    context,
):

    user = update.effective_user

    if not user:
        return

    if user.id != OWNER_ID:

        status = get_approval_status(user.id)

        if status != APPROVED:

            joined, missing = await is_force_joined(
                context,
                user.id,
            )

            if not joined:

                await force_join_message(
                    update,
                    context,
                )

                return

            await update.effective_message.reply_text(
                "⏳ <b>Access Pending</b>\n\n"
                "Your access has not been approved yet.",
                parse_mode="HTML",
            )

            return

    text = (
        "🛡️ <b>JoinGuard Bot</b>\n\n"

        "👤 <b>User</b>\n"
        "/start\n"
        "/help\n"
        "/id\n"
        "/info\n"
        "/rules\n\n"

        "👮 <b>Admin</b>\n"
        "/warn\n"
        "/unwarn\n"
        "/ban\n"
        "/unban\n"
        "/mute\n"
        "/unmute\n"
        "/purge\n"
        "/lock\n"
        "/unlock\n"
        "/welcome on/off\n"
        "/goodbye on/off\n"
        "/setrules\n\n"

        "🌐 <b>Federation</b>\n"
        "/newfed Name\n"
        "/fedban USER_ID\n"
        "/fedunban USER_ID\n"
        "/fedmute USER_ID\n"
        "/fedunmute USER_ID"
    )

    if user.id == OWNER_ID:

        text += (
            "\n\n👑 <b>Owner</b>\n"
            "/panel\n"
            "/approve @username\n"
            "/reject @username\n"
            "/reapprove @username\n"
            "/revoke @username"
        )

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# ID
# ============================================================

async def id_command(
    update,
    context,
):

    user = update.effective_user

    await update.effective_message.reply_text(
        f"🆔 <b>Your ID:</b>\n"
        f"<code>{user.id}</code>",
        parse_mode="HTML",
    )


# ============================================================
# INFO
# ============================================================

async def info_command(
    update,
    context,
):

    user = update.effective_user
    save_user(user)

    status = get_approval_status(user.id)

    await update.effective_message.reply_text(
        "👤 <b>USER INFORMATION</b>\n\n"
        f"📝 Name: {escape(user.first_name or 'User')}\n"
        f"🔗 Username: {username_text(user)}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"📌 Access: <b>{status_name(status)}</b>",
        parse_mode="HTML",
    )


# ============================================================
# RULES
# ============================================================

async def rules_command(
    update,
    context,
):

    settings = get_group_settings(
        update.effective_chat.id
    )

    await update.effective_message.reply_text(
        f"<b>📜 GROUP RULES</b>\n\n"
        f"{escape(settings[4])}",
        parse_mode="HTML",
    )


# ============================================================
# WELCOME
# ============================================================

async def welcome_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    if not context.args:

        settings = get_group_settings(
            update.effective_chat.id
        )

        await update.effective_message.reply_text(
            "👋 Welcome: "
            f"<b>{'ON' if settings[0] else 'OFF'}</b>",
            parse_mode="HTML",
        )

        return

    option = context.args[0].lower()

    if option == "on":

        set_welcome(
            update.effective_chat.id,
            True,
        )

        await update.effective_message.reply_text(
            "✅ Welcome enabled."
        )

    elif option == "off":

        set_welcome(
            update.effective_chat.id,
            False,
        )

        await update.effective_message.reply_text(
            "❌ Welcome disabled."
        )


# ============================================================
# GOODBYE
# ============================================================

async def goodbye_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    if not context.args:

        settings = get_group_settings(
            update.effective_chat.id
        )

        await update.effective_message.reply_text(
            "👋 Goodbye: "
            f"<b>{'ON' if settings[2] else 'OFF'}</b>",
            parse_mode="HTML",
        )

        return

    option = context.args[0].lower()

    if option == "on":

        set_goodbye(
            update.effective_chat.id,
            True,
        )

        await update.effective_message.reply_text(
            "✅ Goodbye enabled."
        )

    elif option == "off":

        set_goodbye(
            update.effective_chat.id,
            False,
        )

        await update.effective_message.reply_text(
            "❌ Goodbye disabled."
        )


# ============================================================
# SET RULES
# ============================================================

async def setrules_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    if not context.args:

        await update.effective_message.reply_text(
            "Usage:\n/setrules Your rules here"
        )

        return

    rules = " ".join(context.args)

    set_rules(
        update.effective_chat.id,
        rules,
    )

    await update.effective_message.reply_text(
        "✅ Rules updated."
    )


# ============================================================
# TARGET USER
# ============================================================

async def get_target_user(
    update,
    context,
):

    if (
        update.message
        and update.message.reply_to_message
    ):

        return update.message.reply_to_message.from_user

    if not context.args:
        return None

    value = context.args[0]

    if value.lstrip("-").isdigit():

        try:

            member = await context.bot.get_chat_member(
                update.effective_chat.id,
                int(value),
            )

            return member.user

        except Exception:
            return None

    row = get_user_by_username(value)

    if not row:
        return None

    class User:
        pass

    user = User()
    user.id = row[0]
    user.first_name = row[1]
    user.username = row[2]

    return user


# ============================================================
# WARN
# ============================================================

async def warn_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:

        await update.effective_message.reply_text(
            "Reply to a user or use /warn USER_ID"
        )

        return

    count = add_warn(
        update.effective_chat.id,
        target.id,
    )

    settings = get_group_settings(
        update.effective_chat.id
    )

    limit = settings[5]

    if count >= limit:

        try:

            await context.bot.ban_chat_member(
                update.effective_chat.id,
                target.id,
            )

            reset_warns(
                update.effective_chat.id,
                target.id,
            )

            await update.effective_message.reply_text(
                f"🔨 {mention(target)} banned after "
                f"{limit} warnings.",
                parse_mode="HTML",
            )

        except Exception as e:

            await update.effective_message.reply_text(
                f"❌ Ban failed:\n"
                f"<code>{escape(str(e))}</code>",
                parse_mode="HTML",
            )

        return

    await update.effective_message.reply_text(
        f"⚠️ {mention(target)} warned.\n\n"
        f"Warnings: <b>{count}/{limit}</b>",
        parse_mode="HTML",
    )


# ============================================================
# UNWARN
# ============================================================

async def unwarn_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:

        await update.effective_message.reply_text(
            "Reply to a user or use /unwarn USER_ID"
        )

        return

    reset_warns(
        update.effective_chat.id,
        target.id,
    )

    await update.effective_message.reply_text(
        f"✅ Warnings cleared for {mention(target)}.",
        parse_mode="HTML",
    )


# ============================================================
# BAN
# ============================================================

async def ban_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:

        await update.effective_message.reply_text(
            "Reply to a user or use /ban USER_ID"
        )

        return

    try:

        await context.bot.ban_chat_member(
            update.effective_chat.id,
            target.id,
        )

        await update.effective_message.reply_text(
            f"🔨 {mention(target)} banned.",
            parse_mode="HTML",
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ Ban failed:\n"
            f"<code>{escape(str(e))}</code>",
            parse_mode="HTML",
        )


# ============================================================
# UNBAN
# ============================================================

async def unban_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    if not context.args:

        await update.effective_message.reply_text(
            "Usage:\n/unban USER_ID"
        )

        return

    try:

        user_id = int(context.args[0])

        await context.bot.unban_chat_member(
            update.effective_chat.id,
            user_id,
            only_if_banned=True,
        )

        await update.effective_message.reply_text(
            f"✅ <code>{user_id}</code> unbanned.",
            parse_mode="HTML",
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ Unban failed:\n"
            f"<code>{escape(str(e))}</code>",
            parse_mode="HTML",
        )


# ============================================================
# MUTE
# ============================================================

async def mute_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:

        await update.effective_message.reply_text(
            "Reply to a user or use /mute USER_ID"
        )

        return

    try:

        permissions = ChatPermissions(
            can_send_messages=False
        )

        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=permissions,
        )

        await update.effective_message.reply_text(
            f"🔇 {mention(target)} muted.",
            parse_mode="HTML",
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ Mute failed:\n"
            f"<code>{escape(str(e))}</code>",
            parse_mode="HTML",
        )


# ============================================================
# UNMUTE
# ============================================================

async def unmute_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:

        await update.effective_message.reply_text(
            "Reply to a user or use /unmute USER_ID"
        )

        return

    try:

        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        )

        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=permissions,
        )

        await update.effective_message.reply_text(
            f"🔊 {mention(target)} unmuted.",
            parse_mode="HTML",
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ Unmute failed:\n"
            f"<code>{escape(str(e))}</code>",
            parse_mode="HTML",
        )


# ============================================================
# PURGE
# ============================================================

async def purge_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    if not context.args:

        await update.effective_message.reply_text(
            "Usage:\n/purge 10"
        )

        return

    try:

        amount = int(context.args[0])

        if amount < 1 or amount > 100:

            await update.effective_message.reply_text(
                "Use a number between 1 and 100."
            )

            return

        message_id = update.effective_message.message_id

        deleted = 0

        for msg_id in range(
            message_id,
            max(0, message_id - amount),
            -1,
        ):

            try:

                await context.bot.delete_message(
                    update.effective_chat.id,
                    msg_id,
                )

                deleted += 1

            except Exception:
                pass

        await context.bot.send_message(
            update.effective_chat.id,
            f"🧹 Deleted {deleted} messages.",
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ Purge failed:\n"
            f"<code>{escape(str(e))}</code>",
            parse_mode="HTML",
        )


# ============================================================
# LOCK
# ============================================================

async def lock_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    lock_type = (
        context.args[0]
        if context.args
        else "messages"
    )

    set_lock(
        update.effective_chat.id,
        lock_type,
        True,
    )

    await update.effective_message.reply_text(
        f"🔒 {escape(lock_type)} locked.",
        parse_mode="HTML",
    )


# ============================================================
# UNLOCK
# ============================================================

async def unlock_command(
    update,
    context,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    lock_type = (
        context.args[0]
        if context.args
        else "messages"
    )

    set_lock(
        update.effective_chat.id,
        lock_type,
        False,
    )

    await update.effective_message.reply_text(
        f"🔓 {escape(lock_type)} unlocked.",
        parse_mode="HTML",
    )


# ============================================================
# FEDERATION ADMIN CHECK
# ============================================================

async def federation_admin(
    update,
):

    if update.effective_chat.type == ChatType.PRIVATE:

        await update.effective_message.reply_text(
            "❌ Federation commands can only be used in groups."
        )

        return False

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ <b>Group admins only.</b>",
            parse_mode="HTML",
        )

        return False

    return True


# ============================================================
# /NEWFED
# ============================================================

async def newfed_command(
    update,
    context,
):

    if not await federation_admin(update):
        return

    if not context.args:

        await update.effective_message.reply_text(
            "🌐 <b>CREATE FEDERATION</b>\n\n"
            "Usage:\n"
            "<code>/newfed Federation Name</code>\n\n"
            "Example:\n"
            "<code>/newfed DG Network</code>",
            parse_mode="HTML",
        )

        return

    name = " ".join(context.args).strip()

    fed_id = uuid.uuid4().hex[:10].upper()

    create_federation(
        fed_id,
        name,
        update.effective_user.id,
    )

    add_fed_chat(
        fed_id,
        update.effective_chat.id,
    )

    await update.effective_message.reply_text(
        "🌐 <b>FEDERATION CREATED</b>\n\n"
        f"📛 Name: <b>{escape(name)}</b>\n"
        f"🆔 Federation ID: <code>{fed_id}</code>\n"
        f"👑 Owner ID: <code>{update.effective_user.id}</code>\n\n"
        "🏠 This group has been connected automatically.\n\n"
        "Use:\n"
        "<code>/fedban USER_ID</code>\n"
        "<code>/fedunban USER_ID</code>\n"
        "<code>/fedmute USER_ID</code>\n"
        "<code>/fedunmute USER_ID</code>",
        parse_mode="HTML",
    )


# ============================================================
# FEDERATION TARGET
# ============================================================

async def get_fed_target(
    update,
    context,
):

    if (
        update.message
        and update.message.reply_to_message
    ):

        return update.message.reply_to_message.from_user

    if not context.args:
        return None

    value = context.args[0]

    if value.lstrip("-").isdigit():

        try:

            member = await context.bot.get_chat_member(
                update.effective_chat.id,
                int(value),
            )

            return member.user

        except Exception:

            row = get_user(
                int(value)
            )

            if not row:
                return None

            class User:
                pass

            user = User()
            user.id = row[0]
            user.first_name = row[1]
            user.username = row[2]

            return user

    row = get_user_by_username(value)

    if not row:
        return None

    class User:
        pass

    user = User()
    user.id = row[0]
    user.first_name = row[1]
    user.username = row[2]

    return user


# ============================================================
# /FEDBAN
# ============================================================

async def fedban_command(
    update,
    context,
):

    if not await federation_admin(update):
        return

    fed = get_chat_federation(
        update.effective_chat.id
    )

    if not fed:

        await update.effective_message.reply_text(
            "❌ <b>This group is not connected to a federation.</b>\n\n"
            "Create one with:\n"
            "<code>/newfed DG Network</code>",
            parse_mode="HTML",
        )

        return

    fed_id, fed_name, fed_owner = fed

    target = await get_fed_target(
        update,
        context,
    )

    if not target:

        await update.effective_message.reply_text(
            "❌ User not found.\n\n"
            "Reply to a user or use:\n"
            "<code>/fedban USER_ID</code>",
            parse_mode="HTML",
        )

        return

    save_user(target)

    fed_ban(
        fed_id,
        target.id,
    )

    chats = get_federation_chats(
        fed_id
    )

    success = 0
    failed = 0

    for chat_id in chats:

        try:

            await context.bot.ban_chat_member(
                chat_id,
                target.id,
            )

            success += 1

        except Exception as e:

            logger.warning(
                "Fed ban failed in %s: %s",
                chat_id,
                e,
            )

            failed += 1

    await update.effective_message.reply_text(
        "🌐 <b>FEDERATION BAN</b>\n\n"
        f"📛 Federation: <b>{escape(fed_name)}</b>\n"
        f"👤 User: {mention(target)}\n"
        f"🆔 ID: <code>{target.id}</code>\n\n"
        f"🔨 Banned: <b>{success}</b> group(s)\n"
        f"⚠️ Failed: <b>{failed}</b>",
        parse_mode="HTML",
    )


# ============================================================
# /FEDUNBAN
# ============================================================

async def fedunban_command(
    update,
    context,
):

    if not await federation_admin(update):
        return

    fed = get_chat_federation(
        update.effective_chat.id
    )

    if not fed:

        await update.effective_message.reply_text(
            "❌ This group is not connected to a federation."
        )

        return

    fed_id, fed_name, fed_owner = fed

    target = await get_fed_target(
        update,
        context,
    )

    if not target:

        await update.effective_message.reply_text(
            "Usage:\n/fedunban USER_ID"
        )

        return

    fed_unban(
        fed_id,
        target.id,
    )

    chats = get_federation_chats(
        fed_id
    )

    success = 0
    failed = 0

    for chat_id in chats:

        try:

            await context.bot.unban_chat_member(
                chat_id,
                target.id,
                only_if_banned=True,
            )

            success += 1

        except Exception as e:

            logger.warning(
                "Fed unban failed in %s: %s",
                chat_id,
                e,
            )

            failed += 1

    await update.effective_message.reply_text(
        "🌐 <b>FEDERATION UNBAN</b>\n\n"
        f"📛 Federation: <b>{escape(fed_name)}</b>\n"
        f"👤 User: {mention(target)}\n"
        f"🆔 ID: <code>{target.id}</code>\n\n"
        f"🔓 Unbanned: <b>{success}</b> group(s)\n"
        f"⚠️ Failed: <b>{failed}</b>",
        parse_mode="HTML",
    )


# ============================================================
# /FEDMUTE
# ============================================================

async def fedmute_command(
    update,
    context,
):

    if not await federation_admin(update):
        return

    fed = get_chat_federation(
        update.effective_chat.id
    )

    if not fed:

        await update.effective_message.reply_text(
            "❌ This group is not connected to a federation."
        )

        return

    fed_id, fed_name, fed_owner = fed

    target = await get_fed_target(
        update,
        context,
    )

    if not target:

        await update.effective_message.reply_text(
            "Usage:\n/fedmute USER_ID"
        )

        return

    fed_mute(
        fed_id,
        target.id,
    )

    chats = get_federation_chats(
        fed_id
    )

    success = 0
    failed = 0

    for chat_id in chats:

        try:

            await context.bot.restrict_chat_member(
                chat_id,
                target.id,
                permissions=ChatPermissions(
                    can_send_messages=False
                ),
            )

            success += 1

        except Exception as e:

            logger.warning(
                "Fed mute failed in %s: %s",
                chat_id,
                e,
            )

            failed += 1

    await update.effective_message.reply_text(
        "🌐 <b>FEDERATION MUTE</b>\n\n"
        f"📛 Federation: <b>{escape(fed_name)}</b>\n"
        f"👤 User: {mention(target)}\n"
        f"🆔 ID: <code>{target.id}</code>\n\n"
        f"🔇 Muted: <b>{success}</b> group(s)\n"
        f"⚠️ Failed: <b>{failed}</b>",
        parse_mode="HTML",
    )


# ============================================================
# /FEDUNMUTE
# ============================================================

async def fedunmute_command(
    update,
    context,
):

    if not await federation_admin(update):
        return

    fed = get_chat_federation(
        update.effective_chat.id
    )

    if not fed:

        await update.effective_message.reply_text(
            "❌ This group is not connected to a federation."
        )

        return

    fed_id, fed_name, fed_owner = fed

    target = await get_fed_target(
        update,
        context,
    )

    if not target:

        await update.effective_message.reply_text(
            "Usage:\n/fedunmute USER_ID"
        )

        return

    fed_unmute(
        fed_id,
        target.id,
    )

    chats = get_federation_chats(
        fed_id
    )

    success = 0
    failed = 0

    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )

    for chat_id in chats:

        try:

            await context.bot.restrict_chat_member(
                chat_id,
                target.id,
                permissions=permissions,
            )

            success += 1

        except Exception as e:

            logger.warning(
                "Fed unmute failed in %s: %s",
                chat_id,
                e,
            )

            failed += 1

    await update.effective_message.reply_text(
        "🌐 <b>FEDERATION UNMUTE</b>\n\n"
        f"📛 Federation: <b>{escape(fed_name)}</b>\n"
        f"👤 User: {mention(target)}\n"
        f"🆔 ID: <code>{target.id}</code>\n\n"
        f"🔊 Unmuted: <b>{success}</b> group(s)\n"
        f"⚠️ Failed: <b>{failed}</b>",
        parse_mode="HTML",
    )


# ============================================================
# PANEL
# ============================================================

def panel_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="panel_stats",
            ),
            InlineKeyboardButton(
                "👥 Users",
                callback_data="panel_users",
            ),
        ],
        [
            InlineKeyboardButton(
                "🌐 Federation",
                callback_data="panel_fed",
            ),
        ],
        [
            InlineKeyboardButton(
                "🌹 Rose",
                callback_data="panel_rose",
            ),
            InlineKeyboardButton(
                "⚙️ Group",
                callback_data="panel_group",
            ),
        ],
        [
            InlineKeyboardButton(
                "📖 Help",
                callback_data="panel_help",
            ),
        ],
    ])


async def panel(
    update,
    context,
):

    if update.effective_user.id != OWNER_ID:

        await update.effective_message.reply_text(
            "❌ Owner only."
        )

        return

    await update.effective_message.reply_text(
        "👑 <b>OWNER CONTROL PANEL</b>\n\n"
        "🛡️ JoinGuard Bot\n\n"
        "Select an option:",
        reply_markup=panel_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# PANEL CALLBACK
# ============================================================

async def panel_callback(
    update,
    context,
):

    query = update.callback_query

    if query.from_user.id != OWNER_ID:

        await query.answer(
            "❌ Owner only.",
            show_alert=True,
        )

        return

    await query.answer()

    data = query.data

    if data == "panel_stats":

        text = (
            "📊 <b>BOT STATISTICS</b>\n\n"
            f"👥 Users: <b>{get_user_count()}</b>\n"
            f"✅ Verified: <b>{get_verified_count()}</b>\n"
            f"🟢 Approved: <b>{get_approved_count()}</b>\n"
            f"🟡 Pending: <b>{get_pending_count()}</b>\n"
            f"🔴 Rejected: <b>{get_rejected_count()}</b>\n"
            f"🚫 Revoked: <b>{get_revoked_count()}</b>"
        )

    elif data == "panel_users":

        text = (
            "👥 <b>USER MANAGEMENT</b>\n\n"
            f"Total: {get_user_count()}\n"
            f"Approved: {get_approved_count()}\n"
            f"Pending: {get_pending_count()}\n"
            f"Rejected: {get_rejected_count()}\n"
            f"Revoked: {get_revoked_count()}\n\n"
            "Commands:\n"
            "/approve @username\n"
            "/reject @username\n"
            "/reapprove @username\n"
            "/revoke @username"
        )

    elif data == "panel_fed":

        text = (
            "🌐 <b>FEDERATION</b>\n\n"
            "<code>/newfed Federation Name</code>\n"
            "<code>/fedban USER_ID</code>\n"
            "<code>/fedunban USER_ID</code>\n"
            "<code>/fedmute USER_ID</code>\n"
            "<code>/fedunmute USER_ID</code>\n\n"
            "📌 A federation connects multiple groups.\n\n"
            "⚠️ The bot must be administrator in every "
            "connected group."
        )

    elif data == "panel_rose":

        text = (
            "🌹 <b>ROSE COMMANDS</b>\n\n"
            "/welcome on\n"
            "/welcome off\n"
            "/goodbye on\n"
            "/goodbye off\n"
            "/rules\n"
            "/setrules\n"
            "/warn\n"
            "/unwarn\n"
            "/ban\n"
            "/unban\n"
            "/mute\n"
            "/unmute\n"
            "/purge\n"
            "/lock\n"
            "/unlock"
        )

    elif data == "panel_group":

        text = (
            "⚙️ <b>GROUP MANAGEMENT</b>\n\n"
            "/welcome\n"
            "/goodbye\n"
            "/setrules\n"
            "/warn\n"
            "/unwarn\n"
            "/ban\n"
            "/unban\n"
            "/mute\n"
            "/unmute\n"
            "/purge\n"
            "/lock\n"
            "/unlock"
        )

    elif data == "panel_help":

        text = (
            "📖 <b>HELP</b>\n\n"
            "Use /help to see all available commands."
        )

    else:

        text = (
            "👑 <b>OWNER CONTROL PANEL</b>\n\n"
            "Select an option:"
        )

    await query.message.edit_text(
        text,
        reply_markup=panel_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# NEW MEMBERS
# ============================================================

async def member_update(
    update,
    context,
):

    if not update.chat_member:
        return

    result = update.chat_member

    old = result.old_chat_member.status
    new = result.new_chat_member.status

    user = result.new_chat_member.user

    if new in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    ) and old not in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    ):

        ensure_group(
            update.effective_chat.id
        )

        settings = get_group_settings(
            update.effective_chat.id
        )

        if not settings[0]:
            return

        try:

            text = settings[1].format(
                mention=mention(user),
                name=escape(user.first_name or "User"),
                username=(
                    "@" + escape(user.username)
                    if user.username
                    else ""
                ),
                id=user.id,
                chatname=escape(
                    update.effective_chat.title or ""
                ),
            )

        except Exception:

            text = (
                f"🌹 Welcome {mention(user)}!"
            )

        await context.bot.send_message(
            update.effective_chat.id,
            text,
            parse_mode="HTML",
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context,
):

    logger.error(
        "Update error:",
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("🚀 Starting Force Join Bot...")
    print("✅ Initializing SQLite database...")

    init_db()

    print("✅ Database ready")
    print("✅ Federation system loaded")
    print("✅ Approval system loaded")
    print("✅ Force join system loaded")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # USER
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "id",
            id_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "info",
            info_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "rules",
            rules_command,
        )
    )

    # --------------------------------------------------------
    # OWNER APPROVAL
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "approve",
            approve_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "reject",
            reject_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "reapprove",
            reapprove_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "revoke",
            revoke_command,
        )
    )

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "welcome",
            welcome_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "goodbye",
            goodbye_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "setrules",
            setrules_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "warn",
            warn_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "unwarn",
            unwarn_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "ban",
            ban_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "unban",
            unban_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "mute",
            mute_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "unmute",
            unmute_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "purge",
            purge_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "lock",
            lock_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "unlock",
            unlock_command,
        )
    )

    # --------------------------------------------------------
    # FEDERATION
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "newfed",
            newfed_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "fedban",
            fedban_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "fedunban",
            fedunban_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "fedmute",
            fedmute_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "fedunmute",
            fedunmute_command,
        )
    )

    # --------------------------------------------------------
    # CALLBACKS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            verify_join,
            pattern=r"^verify_join$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            approval_callback,
            pattern=r"^(approve|reject|reapprove|revoke):",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            panel_callback,
            pattern=r"^panel_",
        )
    )

    # --------------------------------------------------------
    # MEMBER EVENTS
    # --------------------------------------------------------

    application.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    # --------------------------------------------------------
    # PANEL
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "panel",
            panel,
        )
    )

    # --------------------------------------------------------
    # ERRORS
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    # --------------------------------------------------------
    # RUN
    # --------------------------------------------------------

    print()
    print("======================================")
    print("   JOIN GUARD BOT IS RUNNING")
    print("======================================")
    print("✅ Force Join")
    print("✅ Approval / Revoke / Reject")
    print("✅ Owner Panel")
    print("✅ Group Management")
    print("✅ Rose Commands")
    print("✅ Federation Commands")
    print("✅ SQLite")
    print("======================================")
    print()

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
```
