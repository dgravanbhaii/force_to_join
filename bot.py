import logging
import uuid
from html import escape

from telegram import Update, ChatPermissions
from telegram.constants import ChatMemberStatus, ChatType, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler,
)

import config
import database as db
import keyboards as kb

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

PENDING, APPROVED, REJECTED, REVOKED = 0, 1, 2, 3


# ============================================================
# HELPERS
# ============================================================

def mention(user) -> str:
    return f'<a href="tg://user?id={user.id}">{escape(user.first_name or "User")}</a>'


def is_owner(user_id: int) -> bool:
    return user_id == config.OWNER_ID


async def is_admin(update: Update, user_id: int = None) -> bool:
    chat = update.effective_chat
    if not chat or chat.type == ChatType.PRIVATE:
        return False
    user_id = user_id or update.effective_user.id
    if user_id == config.OWNER_ID:
        return True
    try:
        member = await update.get_bot().get_chat_member(chat.id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception as e:
        logger.warning("Admin check failed: %s", e)
        return False


async def check_channel(context, user_id, channel_id) -> bool:
    try:
        member = await context.bot.get_chat_member(channel_id, user_id)
        return member.status in (
            ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER, ChatMemberStatus.RESTRICTED,
        )
    except Exception as e:
        logger.warning("Membership check failed for %s: %s", channel_id, e)
        return False


async def is_force_joined(context, user_id):
    missing = [c for c in config.FORCE_JOIN_CHANNELS if not await check_channel(context, user_id, c["id"])]
    return len(missing) == 0, missing


async def get_reply_target(update: Update):
    """Only resolves a target from a reply — the button flows always originate from a reply."""
    msg = update.effective_message
    if msg and msg.reply_to_message:
        return msg.reply_to_message.from_user
    return None


HELP_TEXT = (
    "🛡️ <b>JoinGuard Bot — Command Reference</b>\n\n"
    "Almost everything below is also reachable through buttons — "
    "use /start (private) or /settings and /admin (groups) as your menus.\n\n"
    "👤 <b>User</b>: /start /help /id /info /rules\n"
    "👮 <b>Admin</b>: /settings /admin (reply to a user) /panel (owner)\n"
    "🌐 <b>Federation</b>: /fedmenu"
)


# ============================================================
# START / MAIN MENU
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    db.add_user(user.id, user.first_name or "", user.username or "")

    if is_owner(user.id):
        await update.effective_message.reply_text(
            "👑 <b>Welcome back, Owner</b>\n\nUse the menu below.",
            reply_markup=kb.main_menu_keyboard(is_owner=True),
            parse_mode=ParseMode.HTML,
        )
        return

    status = db.get_approval_status(user.id)
    if status == APPROVED:
        await update.effective_message.reply_text(
            f"👋 Welcome {mention(user)}!\n\n🟢 Your access is approved.",
            reply_markup=kb.main_menu_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    joined, missing = await is_force_joined(context, user.id)
    if not joined:
        await update.effective_message.reply_text(
            "🔐 <b>ACCESS LOCKED</b>\n\nJoin all required channels, then tap ✅ I've Joined.",
            reply_markup=kb.force_join_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    db.set_verified(user.id, True)
    await send_approval_request(context, user)
    await update.effective_message.reply_text(
        "✅ <b>Channel verification complete</b>\n\n⏳ Waiting for owner approval.",
        parse_mode=ParseMode.HTML,
    )


async def send_approval_request(context, user):
    status = db.get_approval_status(user.id)
    text = (
        "🔔 <b>ACCESS REQUEST</b>\n\n"
        f"👤 Name: {mention(user)}\n"
        f"🔗 Username: {'@' + escape(user.username) if user.username else 'None'}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"📌 Status: <b>{db.get_status_name(status)}</b>"
    )
    try:
        await context.bot.send_message(
            config.OWNER_ID, text, reply_markup=kb.approval_keyboard(user.id), parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error("Approval notification failed: %s", e)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.effective_message.reply_text(
        f"🆔 <b>Your ID:</b> <code>{user.id}</code>", parse_mode=ParseMode.HTML
    )


async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.first_name or "", user.username or "")
    status = db.get_approval_status(user.id)
    await update.effective_message.reply_text(
        f"👤 <b>USER INFO</b>\n\nName: {escape(user.first_name or 'User')}\n"
        f"ID: <code>{user.id}</code>\nAccess: <b>{db.get_status_name(status)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text("📜 Group rules are shown inside groups.")
        return
    settings = db.get_group_settings(update.effective_chat.id)
    await update.effective_message.reply_text(
        f"<b>📜 GROUP RULES</b>\n\n{escape(settings[4])}", parse_mode=ParseMode.HTML
    )


# ============================================================
# OWNER PANEL (entry command)
# ============================================================

async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.effective_message.reply_text("❌ Owner only.")
        return
    await update.effective_message.reply_text(
        "👑 <b>Owner Control Panel</b>", reply_markup=kb.panel_keyboard(), parse_mode=ParseMode.HTML
    )


# ============================================================
# GROUP SETTINGS MENU (entry command)
# ============================================================

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text("⚙️ Use this inside a group.")
        return
    if not await is_admin(update):
        await update.effective_message.reply_text("❌ Admins only.")
        return
    db.ensure_group(update.effective_chat.id)
    await update.effective_message.reply_text(
        "⚙️ <b>Group Settings</b>\n\nTap a button to toggle it.",
        reply_markup=kb.settings_root_keyboard(update.effective_chat.id),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# MODERATION QUICK-ACTIONS MENU (entry command, reply required)
# ============================================================

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text("👮 Use this inside a group.")
        return
    if not await is_admin(update):
        await update.effective_message.reply_text("❌ Admins only.")
        return
    target = await get_reply_target(update)
    if not target:
        await update.effective_message.reply_text("Reply to a user's message with /admin to open their action menu.")
        return
    await update.effective_message.reply_text(
        f"👮 <b>Moderation Menu</b>\n\nTarget: {mention(target)} (<code>{target.id}</code>)",
        reply_markup=kb.modactions_keyboard(update.effective_chat.id, target.id),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# FEDERATION MENU (entry command)
# ============================================================

async def fedmenu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text("🌐 Use this inside a group.")
        return
    if not await is_admin(update):
        await update.effective_message.reply_text("❌ Admins only.")
        return
    await update.effective_message.reply_text(
        "🌐 <b>Federation Menu</b>", reply_markup=kb.fed_menu_keyboard(update.effective_chat.id),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# CALLBACK: verify join
# ============================================================

async def cb_verify_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    db.add_user(user.id, user.first_name or "", user.username or "")

    if db.get_approval_status(user.id) == APPROVED:
        await query.answer("Already approved.", show_alert=True)
        return

    joined, missing = await is_force_joined(context, user.id)
    if not joined:
        names = "\n".join(f"📢 {escape(c['title'])}" for c in missing)
        await query.answer("❌ Join all required channels first.", show_alert=True)
        await query.message.edit_text(
            f"❌ <b>Verification Failed</b>\n\nStill need to join:\n{names}",
            reply_markup=kb.force_join_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    db.set_verified(user.id, True)
    await send_approval_request(context, user)
    await query.answer("✅ Verification successful!", show_alert=True)
    await query.message.edit_text(
        "✅ <b>Verification Successful</b>\n\n⏳ Access pending owner approval.", parse_mode=ParseMode.HTML
    )


# ============================================================
# CALLBACK: main menu navigation
# ============================================================

async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]
    user = query.from_user

    if action == "main":
        await query.message.edit_text(
            "🏠 <b>Main Menu</b>", reply_markup=kb.main_menu_keyboard(is_owner(user.id)), parse_mode=ParseMode.HTML
        )
    elif action == "help":
        await query.message.edit_text(HELP_TEXT, reply_markup=kb.back_button(), parse_mode=ParseMode.HTML)
    elif action == "rules":
        chat_id = update.effective_chat.id if update.effective_chat.type != ChatType.PRIVATE else None
        text = escape(db.get_group_settings(chat_id)[4]) if chat_id else "📜 Rules are set per-group — open this in a group."
        await query.message.edit_text(f"<b>📜 RULES</b>\n\n{text}", reply_markup=kb.back_button(), parse_mode=ParseMode.HTML)
    elif action == "myinfo":
        status = db.get_approval_status(user.id)
        await query.message.edit_text(
            f"👤 <b>USER INFO</b>\n\nName: {escape(user.first_name or 'User')}\n"
            f"ID: <code>{user.id}</code>\nAccess: <b>{db.get_status_name(status)}</b>",
            reply_markup=kb.back_button(), parse_mode=ParseMode.HTML,
        )
    elif action == "myid":
        await query.message.edit_text(
            f"🆔 <b>Your ID:</b> <code>{user.id}</code>", reply_markup=kb.back_button(), parse_mode=ParseMode.HTML
        )


async def cb_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


# ============================================================
# CALLBACK: approval actions (owner)
# ============================================================

async def cb_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != config.OWNER_ID:
        await query.answer("❌ Owner only.", show_alert=True)
        return

    action, user_id_text = query.data.split(":")
    user_id = int(user_id_text)
    row = db.get_user(user_id)
    if not row:
        await query.answer("❌ User not found.", show_alert=True)
        return

    status_map = {"approve": APPROVED, "reject": REJECTED, "reapprove": APPROVED, "revoke": REVOKED}
    status = status_map[action]
    db.set_approval(user_id, status)
    await query.answer("Updated.")

    text = (
        "👤 <b>USER ACCESS CONTROL</b>\n\n"
        f"Name: <b>{escape(row[1] or 'User')}</b>\n"
        f"Username: @{escape(row[2]) if row[2] else 'none'}\n"
        f"ID: <code>{user_id}</code>\n\nStatus: <b>{db.get_status_name(status)}</b>"
    )
    await query.message.edit_text(text, reply_markup=kb.approval_keyboard(user_id), parse_mode=ParseMode.HTML)

    messages = {
        APPROVED: "🎉 <b>ACCESS APPROVED</b>\n\nYou can now use the bot.",
        REJECTED: "🔴 <b>ACCESS REJECTED</b>",
        REVOKED: "🚫 <b>ACCESS REVOKED</b>\n\nJoin the required channels again and re-verify.",
    }
    try:
        await context.bot.send_message(user_id, messages[status], parse_mode=ParseMode.HTML)
    except Exception:
        pass


# ============================================================
# CALLBACK: owner panel
# ============================================================

async def cb_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != config.OWNER_ID:
        await query.answer("❌ Owner only.", show_alert=True)
        return
    await query.answer()

    parts = query.data.split(":")
    section = parts[1]

    if section == "main":
        await query.message.edit_text("👑 <b>Owner Control Panel</b>", reply_markup=kb.panel_keyboard(), parse_mode=ParseMode.HTML)

    elif section == "stats":
        text = (
            "📊 <b>BOT STATISTICS</b>\n\n"
            f"👥 Users: <b>{db.get_user_count()}</b>\n"
            f"✅ Verified: <b>{db.get_verified_count()}</b>\n"
            f"🟢 Approved: <b>{db.get_count_by_status(APPROVED)}</b>\n"
            f"🟡 Pending: <b>{db.get_count_by_status(PENDING)}</b>\n"
            f"🔴 Rejected: <b>{db.get_count_by_status(REJECTED)}</b>\n"
            f"🚫 Revoked: <b>{db.get_count_by_status(REVOKED)}</b>"
        )
        await query.message.edit_text(text, reply_markup=kb.back_button("panel:main"), parse_mode=ParseMode.HTML)

    elif section == "users":
        await query.message.edit_text("👥 <b>User Management</b>\n\nPick a status to view.", reply_markup=kb.users_panel_keyboard(), parse_mode=ParseMode.HTML)

    elif section == "list":
        status = int(parts[2])
        conn = db.get_connection()
        rows = conn.execute(
            "SELECT user_id, first_name, username FROM users WHERE approved=? ORDER BY user_id DESC LIMIT 20",
            (status,),
        ).fetchall()
        conn.close()
        if not rows:
            text = f"No users with status {db.get_status_name(status)}."
        else:
            lines = [f"{db.get_status_name(status)} users (latest 20):\n"]
            for uid, fname, uname in rows:
                lines.append(f"• {escape(fname or 'User')} (@{escape(uname) if uname else 'none'}) — <code>{uid}</code>")
            text = "\n".join(lines)
        await query.message.edit_text(text, reply_markup=kb.back_button("panel:users"), parse_mode=ParseMode.HTML)

    elif section == "fed":
        conn = db.get_connection()
        feds = conn.execute("SELECT fed_id, name, owner_id FROM federations").fetchall()
        conn.close()
        if not feds:
            text = "🌐 No federations exist yet. Create one from a group with /fedmenu."
        else:
            lines = ["🌐 <b>Federations</b>\n"]
            for fed_id, name, owner_id in feds:
                lines.append(f"• {escape(name)} — <code>{fed_id}</code> (owner <code>{owner_id}</code>)")
            text = "\n".join(lines)
        await query.message.edit_text(text, reply_markup=kb.back_button("panel:main"), parse_mode=ParseMode.HTML)

    elif section == "help":
        await query.message.edit_text(HELP_TEXT, reply_markup=kb.back_button("panel:main"), parse_mode=ParseMode.HTML)


# ============================================================
# CALLBACK: group settings
# ============================================================

async def cb_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(update):
        await query.answer("❌ Admins only.", show_alert=True)
        return
    await query.answer()

    chat_id = update.effective_chat.id
    action = query.data.split(":", 1)[1]

    if action == "root":
        await query.message.edit_text("⚙️ <b>Group Settings</b>", reply_markup=kb.settings_root_keyboard(chat_id), parse_mode=ParseMode.HTML)

    elif action == "toggle_welcome":
        s = db.get_group_settings(chat_id)
        db.set_welcome_enabled(chat_id, not s[0])
        await query.message.edit_reply_markup(reply_markup=kb.settings_root_keyboard(chat_id))

    elif action == "toggle_goodbye":
        s = db.get_group_settings(chat_id)
        db.set_goodbye_enabled(chat_id, not s[2])
        await query.message.edit_reply_markup(reply_markup=kb.settings_root_keyboard(chat_id))

    elif action == "warnlimit":
        await query.message.edit_text("⚠️ <b>Warn Limit</b>\n\nHow many warns before auto-ban.", reply_markup=kb.warnlimit_keyboard(chat_id), parse_mode=ParseMode.HTML)

    elif action == "locks":
        await query.message.edit_text("🔒 <b>Locks</b>\n\nTap to toggle each restriction.", reply_markup=kb.locks_keyboard(chat_id), parse_mode=ParseMode.HTML)


async def cb_warnlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(update):
        await query.answer("❌ Admins only.", show_alert=True)
        return
    chat_id = update.effective_chat.id
    current = db.get_group_settings(chat_id)[5]
    delta = 1 if query.data.endswith("+") else -1
    new_limit = db.set_warn_limit(chat_id, current + delta)
    await query.answer(f"Warn limit: {new_limit}")
    await query.message.edit_reply_markup(reply_markup=kb.warnlimit_keyboard(chat_id))


async def cb_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(update):
        await query.answer("❌ Admins only.", show_alert=True)
        return
    chat_id = update.effective_chat.id
    lock_type = query.data.split(":", 1)[1]
    new_state = db.toggle_lock(chat_id, lock_type)
    await query.answer(f"{lock_type.title()} lock: {'ON' if new_state else 'OFF'}")
    await query.message.edit_reply_markup(reply_markup=kb.locks_keyboard(chat_id))


# ============================================================
# CALLBACK: moderation quick actions
# ============================================================

async def cb_modaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(update):
        await query.answer("❌ Admins only.", show_alert=True)
        return

    _, action, chat_id_s, user_id_s = query.data.split(":")
    chat_id, target_id = int(chat_id_s), int(user_id_s)

    try:
        if action == "warn":
            count = db.add_warn(chat_id, target_id)
            limit = db.get_group_settings(chat_id)[5]
            if count >= limit:
                await context.bot.ban_chat_member(chat_id, target_id)
                db.reset_warns(chat_id, target_id)
                await query.answer(f"⚠️→🔨 Warn limit reached, user banned.", show_alert=True)
            else:
                await query.answer(f"⚠️ Warned ({count}/{limit})")

        elif action == "unwarn":
            db.reset_warns(chat_id, target_id)
            await query.answer("♻️ Warnings cleared.")

        elif action == "mute":
            await context.bot.restrict_chat_member(chat_id, target_id, permissions=ChatPermissions(can_send_messages=False))
            await query.answer("🔇 Muted.")

        elif action == "unmute":
            await context.bot.restrict_chat_member(chat_id, target_id, permissions=ChatPermissions.all_permissions())
            await query.answer("🔊 Unmuted.")

        elif action == "kick":
            await context.bot.ban_chat_member(chat_id, target_id)
            await context.bot.unban_chat_member(chat_id, target_id)
            await query.answer("👢 Kicked.")

        elif action == "ban":
            await context.bot.ban_chat_member(chat_id, target_id)
            await query.answer("🔨 Banned.")

        elif action == "unban":
            await context.bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
            await query.answer("✅ Unbanned.")

    except Exception as e:
        await query.answer(f"❌ Failed: {e}", show_alert=True)
        return

    # Refresh the menu text with the latest warn count if relevant
    warns = db.get_warns(chat_id, target_id)
    try:
        await query.message.edit_text(
            f"👮 <b>Moderation Menu</b>\n\nTarget ID: <code>{target_id}</code>\nWarnings: {warns}",
            reply_markup=kb.modactions_keyboard(chat_id, target_id),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass  # message unchanged, Telegram would error on identical edit — harmless


# ============================================================
# CALLBACK: federation menu
# ============================================================

async def cb_fed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(update):
        await query.answer("❌ Admins only.", show_alert=True)
        return
    await query.answer()
    chat_id = update.effective_chat.id
    action = query.data.split(":", 1)[1]

    if action == "new":
        fed_id = uuid.uuid4().hex[:10].upper()
        name = update.effective_chat.title or "Federation"
        db.create_federation(fed_id, name, query.from_user.id)
        db.add_fed_chat(fed_id, chat_id)
        await query.message.edit_text(
            f"🌐 <b>Federation Created</b>\n\nName: {escape(name)}\nID: <code>{fed_id}</code>",
            reply_markup=kb.fed_menu_keyboard(chat_id), parse_mode=ParseMode.HTML,
        )

    elif action == "info":
        fed = db.get_chat_federation(chat_id)
        if not fed:
            text = "🌐 This chat isn't in a federation."
        else:
            fed_id, name, owner_id = fed
            chats = db.get_federation_chats(fed_id)
            text = f"🌐 <b>{escape(name)}</b>\nID: <code>{fed_id}</code>\nLinked chats: {len(chats)}"
        await query.message.edit_text(text, reply_markup=kb.fed_menu_keyboard(chat_id), parse_mode=ParseMode.HTML)


# ============================================================
# MEMBER EVENTS (welcome / goodbye)
# ============================================================

async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return
    result = update.chat_member
    old, new = result.old_chat_member.status, result.new_chat_member.status
    user = result.new_chat_member.user
    chat_id = update.effective_chat.id

    if new in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED) and old not in (
        ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED
    ):
        db.ensure_group(chat_id)
        settings = db.get_group_settings(chat_id)
        if not settings[0]:
            return
        try:
            text = settings[1].format(
                mention=mention(user), name=escape(user.first_name or "User"),
                username=("@" + escape(user.username)) if user.username else "",
                id=user.id, chatname=escape(update.effective_chat.title or ""),
            )
        except Exception:
            text = f"🌹 Welcome {mention(user)}!"
        await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)

    elif old in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED) and new in (
        ChatMemberStatus.LEFT, ChatMemberStatus.BANNED
    ):
        db.ensure_group(chat_id)
        settings = db.get_group_settings(chat_id)
        if not settings[2]:
            return
        try:
            text = settings[3].format(
                mention=mention(user), name=escape(user.first_name or "User"),
                username=("@" + escape(user.username)) if user.username else "",
                id=user.id, chatname=escape(update.effective_chat.title or ""),
            )
        except Exception:
            text = f"👋 {escape(user.first_name or 'User')} has left the group."
        await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)


async def error_handler(update, context):
    logger.error("Update error:", exc_info=context.error)


# ============================================================
# MAIN
# ============================================================

def main():
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))
    app.add_handler(CommandHandler("panel", panel_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("fedmenu", fedmenu_cmd))

    # callbacks
    app.add_handler(CallbackQueryHandler(cb_verify_join, pattern=r"^verify_join$"))
    app.add_handler(CallbackQueryHandler(cb_menu, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(cb_noop, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(cb_approval, pattern=r"^(approve|reject|reapprove|revoke):"))
    app.add_handler(CallbackQueryHandler(cb_panel, pattern=r"^panel:"))
    app.add_handler(CallbackQueryHandler(cb_warnlimit, pattern=r"^warnlimit:"))
    app.add_handler(CallbackQueryHandler(cb_lock, pattern=r"^lock:"))
    app.add_handler(CallbackQueryHandler(cb_settings, pattern=r"^settings:"))
    app.add_handler(CallbackQueryHandler(cb_modaction, pattern=r"^mod:"))
    app.add_handler(CallbackQueryHandler(cb_fed, pattern=r"^fed:"))

    # member events
    app.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))

    app.add_error_handler(error_handler)

    logger.info("Bot starting (button-driven UI)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
