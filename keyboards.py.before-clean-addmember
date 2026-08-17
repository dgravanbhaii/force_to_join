from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
import database as db

# Emoji "colors" — Telegram buttons can't be recolored directly, so status/
# category color is conveyed with a leading colored-circle or icon emoji.
ON = "🟢"
OFF = "🔴"


# ---------------- force join ----------------

def force_join_keyboard():
    rows = []
    for i, channel in enumerate(config.FORCE_JOIN_CHANNELS, 1):
        rows.append([InlineKeyboardButton(f"📢 Join Channel {i}", url=channel["link"])])
    rows.append([InlineKeyboardButton("✅ I've Joined", callback_data="verify_join")])
    return InlineKeyboardMarkup(rows)


# ---------------- main menu ----------------

def main_menu_keyboard(is_owner: bool = False):
    rows = [
        [
            InlineKeyboardButton("📖 Help", callback_data="menu:help"),
            InlineKeyboardButton("📜 Rules", callback_data="menu:rules"),
        ],
        [
            InlineKeyboardButton("👤 My Info", callback_data="menu:myinfo"),
            InlineKeyboardButton("🆔 My ID", callback_data="menu:myid"),
        ],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton("👑 Owner Panel", callback_data="panel:main")])
    return InlineKeyboardMarkup(rows)


def back_button(target: str = "menu:main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data=target)]])


# ---------------- owner panel ----------------

def panel_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Statistics", callback_data="panel:stats"),
            InlineKeyboardButton("👥 Users", callback_data="panel:users"),
        ],
        [
            InlineKeyboardButton("🌐 Federations", callback_data="panel:fed"),
            InlineKeyboardButton("📖 All Commands", callback_data="panel:help"),
        ],
    ])


def users_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟡 Pending", callback_data="panel:list:0")],
        [InlineKeyboardButton("🟢 Approved", callback_data="panel:list:1")],
        [InlineKeyboardButton("🔴 Rejected", callback_data="panel:list:2")],
        [InlineKeyboardButton("🚫 Revoked", callback_data="panel:list:3")],
        [InlineKeyboardButton("◀️ Back", callback_data="panel:main")],
    ])


def approval_keyboard(user_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Approve", callback_data=f"approve:{user_id}"),
            InlineKeyboardButton("🔴 Reject", callback_data=f"reject:{user_id}"),
        ],
        [
            InlineKeyboardButton("🔄 Reapprove", callback_data=f"reapprove:{user_id}"),
            InlineKeyboardButton("🚫 Revoke", callback_data=f"revoke:{user_id}"),
        ],
    ])


# ---------------- group settings (admin, per-chat) ----------------

def settings_root_keyboard(chat_id: int):
    s = db.get_group_settings(chat_id)
    welcome_state = ON if s[0] else OFF
    goodbye_state = ON if s[2] else OFF
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{welcome_state} Welcome Messages", callback_data="settings:toggle_welcome")],
        [InlineKeyboardButton(f"{goodbye_state} Goodbye Messages", callback_data="settings:toggle_goodbye")],
        [InlineKeyboardButton(f"⚠️ Warn Limit: {s[5]}", callback_data="settings:warnlimit")],
        [InlineKeyboardButton("🔒 Locks", callback_data="settings:locks")],
        [InlineKeyboardButton("📜 View Rules", callback_data="menu:rules")],
    ])


def warnlimit_keyboard(chat_id: int):
    limit = db.get_group_settings(chat_id)[5]
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖", callback_data="warnlimit:-"),
            InlineKeyboardButton(f"⚠️ {limit}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data="warnlimit:+"),
        ],
        [InlineKeyboardButton("◀️ Back", callback_data="settings:root")],
    ])


def locks_keyboard(chat_id: int):
    rows = []
    icons = {
        "photo": "🖼️", "video": "🎥", "sticker": "😀", "gif": "🎞️",
        "url": "🔗", "forward": "↪️", "document": "📄", "voice": "🎙️", "poll": "📊",
    }
    for lt in db.LOCK_TYPES:
        state = ON if db.is_locked(chat_id, lt) else OFF
        icon = icons.get(lt, "🔸")
        rows.append([InlineKeyboardButton(f"{state} {icon} {lt.title()}", callback_data=f"lock:{lt}")])
    rows.append([InlineKeyboardButton("◀️ Back", callback_data="settings:root")])
    return InlineKeyboardMarkup(rows)


# ---------------- moderation quick-actions (reply-to-user menu) ----------------

def modactions_keyboard(chat_id: int, user_id: int):
    tag = f"{chat_id}:{user_id}"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ Warn", callback_data=f"mod:warn:{tag}"),
            InlineKeyboardButton("♻️ Clear Warns", callback_data=f"mod:unwarn:{tag}"),
        ],
        [
            InlineKeyboardButton("🔇 Mute", callback_data=f"mod:mute:{tag}"),
            InlineKeyboardButton("🔊 Unmute", callback_data=f"mod:unmute:{tag}"),
        ],
        [
            InlineKeyboardButton("👢 Kick", callback_data=f"mod:kick:{tag}"),
            InlineKeyboardButton("🔨 Ban", callback_data=f"mod:ban:{tag}"),
        ],
        [InlineKeyboardButton("✅ Unban", callback_data=f"mod:unban:{tag}")],
    ])


def undo_ban_keyboard(chat_id: int, user_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ Undo (Unban)", callback_data=f"mod:unban:{chat_id}:{user_id}")
    ]])


# ---------------- federation menu ----------------

def fed_menu_keyboard(chat_id: int):
    fed = db.get_chat_federation(chat_id)
    rows = []
    if fed:
        rows.append([InlineKeyboardButton("ℹ️ Federation Info", callback_data="fed:info")])
    else:
        rows.append([InlineKeyboardButton("🌐 Create Federation", callback_data="fed:new")])
    rows.append([InlineKeyboardButton("◀️ Back", callback_data="settings:root")])
    return InlineKeyboardMarkup(rows)
