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


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# STATUS CONSTANTS
# ============================================================

PENDING = 0
APPROVED = 1
REJECTED = 2
REVOKED = 3


# ============================================================
# HELPERS
# ============================================================

def mention(user) -> str:
    return (
        f'<a href="tg://user?id={user.id}">'
        f'{escape(user.first_name or "User")}'
        f'</a>'
    )


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
        member = await update.get_bot().get_chat_member(
            chat.id,
            user_id,
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception as e:
        logger.warning("Admin check failed: %s", e)
        return False


async def check_channel(context, user_id, channel_id) -> bool:
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
            "Membership check failed for %s: %s",
            channel_id,
            e,
        )

        return False


async def is_force_joined(context, user_id):
    missing = []

    for channel in config.FORCE_JOIN_CHANNELS:
        joined = await check_channel(
            context,
            user_id,
            channel["id"],
        )

        if not joined:
            missing.append(channel)

    return len(missing) == 0, missing


async def get_reply_target(update: Update):
    msg = update.effective_message

    if msg and msg.reply_to_message:
        return msg.reply_to_message.from_user

    return None


# ============================================================
# ADD MEMBER / INVITE SYSTEM
# ============================================================

async def send_group_invite(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> tuple[bool, str]:

    # --------------------------------------------------------
    # CHECK TARGET GROUP
    # --------------------------------------------------------

    if not config.TARGET_GROUP_ID:
        logger.error("TARGET_GROUP_ID is empty")

        return (
            False,
            "TARGET_GROUP_ID is not configured in config/.env.",
        )

    logger.info(
        "ADD MEMBER | Target user=%s | Target group=%s",
        user_id,
        config.TARGET_GROUP_ID,
    )

    # --------------------------------------------------------
    # CHECK BOT ACCESS TO TARGET GROUP
    # --------------------------------------------------------

    try:
        bot_user = await context.bot.get_me()

        bot_member = await context.bot.get_chat_member(
            chat_id=config.TARGET_GROUP_ID,
            user_id=bot_user.id,
        )

        logger.info(
            "Bot membership in target group: %s",
            bot_member.status,
        )

        if bot_member.status not in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            return (
                False,
                "The bot is not an administrator in the target group.",
            )

    except Exception as e:
        logger.exception(
            "Could not access target group",
        )

        return (
            False,
            f"Could not access target group: {e}",
        )

    # --------------------------------------------------------
    # CREATE ONE-TIME INVITE
    # --------------------------------------------------------

    try:
        link = await context.bot.create_chat_invite_link(
            chat_id=config.TARGET_GROUP_ID,
            member_limit=1,
            name=f"invite-{user_id}",
        )

        logger.info(
            "Invite link created successfully for %s: %s",
            user_id,
            link.invite_link,
        )

    except Exception as e:
        logger.exception(
            "Invite creation failed",
        )

        return (
            False,
            "Couldn't create invite link.\n\n"
            "Check that the bot is an administrator and has "
            "'Invite Users via Link' permission.\n\n"
            f"Telegram error: {e}",
        )

    # --------------------------------------------------------
    # SEND INVITE TO USER
    # --------------------------------------------------------

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 <b>ACCESS APPROVED</b>\n\n"
                "You have been approved to join the group.\n\n"
                "🔗 <b>Your personal invite link:</b>\n"
                f"{link.invite_link}\n\n"
                "⚠️ This invitation is limited to one member."
            ),
            parse_mode=ParseMode.HTML,
        )

        logger.info(
            "Invite DM successfully sent to user %s",
            user_id,
        )

    except Exception as e:

        logger.exception(
            "Could not DM user %s",
            user_id,
        )

        return (
            False,
            "The invite link was created successfully, "
            "but Telegram would not allow the bot to message "
            f"user <code>{user_id}</code>.\n\n"
            "Make sure that user has opened this bot and pressed "
            "/start first.\n\n"
            f"Telegram error: {escape(str(e))}",
        )

    return True, "Invite link sent successfully."


# ============================================================
# HELP
# ============================================================

HELP_TEXT = (
    "🛡️ <b>JoinGuard Bot — Command Reference</b>\n\n"
    "Almost everything below is also reachable through buttons.\n\n"
    "👤 <b>User</b>\n"
    "/start /help /id /info /rules\n\n"
    "👮 <b>Admin</b>\n"
    "/settings /admin\n\n"
    "👑 <b>Owner</b>\n"
    "/panel /addmember\n\n"
    "🌐 <b>Federation</b>\n"
    "/fedmenu"
)


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user:
        return

    db.add_user(
        user.id,
        user.first_name or "",
        user.username or "",
    )

    if is_owner(user.id):

        await update.effective_message.reply_text(
            "👑 <b>Welcome back, Owner</b>\n\n"
            "Use the menu below.",
            reply_markup=kb.main_menu_keyboard(
                is_owner=True
            ),
            parse_mode=ParseMode.HTML,
        )

        return

    status = db.get_approval_status(user.id)

    if status == APPROVED:

        await update.effective_message.reply_text(
            f"👋 Welcome {mention(user)}!\n\n"
            "🟢 Your access is approved.",
            reply_markup=kb.main_menu_keyboard(),
            parse_mode=ParseMode.HTML,
        )

        return

    joined, missing = await is_force_joined(
        context,
        user.id,
    )

    if not joined:

        await update.effective_message.reply_text(
            "🔐 <b>ACCESS LOCKED</b>\n\n"
            "Join all required channels, then tap "
            "✅ I've Joined.",
            reply_markup=kb.force_join_keyboard(),
            parse_mode=ParseMode.HTML,
        )

        return

    db.set_verified(
        user.id,
        True,
    )

    await send_approval_request(
        context,
        user,
    )

    await update.effective_message.reply_text(
        "✅ <b>Channel verification complete</b>\n\n"
        "⏳ Waiting for owner approval.",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# APPROVAL REQUEST
# ============================================================

async def send_approval_request(
    context,
    user,
):

    status = db.get_approval_status(
        user.id
    )

    text = (
        "🔔 <b>ACCESS REQUEST</b>\n\n"
        f"👤 Name: {mention(user)}\n"
        f"🔗 Username: "
        f"{'@' + escape(user.username) if user.username else 'None'}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"📌 Status: <b>{db.get_status_name(status)}</b>"
    )

    try:

        await context.bot.send_message(
            config.OWNER_ID,
            text,
            reply_markup=kb.approval_keyboard(
                user.id
            ),
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:

        logger.error(
            "Approval notification failed: %s",
            e,
        )


# ============================================================
# BASIC COMMANDS
# ============================================================

async def help_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.effective_message.reply_text(
        HELP_TEXT,
        parse_mode=ParseMode.HTML,
    )


async def id_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user
    chat = update.effective_chat

    if chat.type == ChatType.PRIVATE:

        await update.effective_message.reply_text(
            f"🆔 <b>Your ID:</b> "
            f"<code>{user.id}</code>",
            parse_mode=ParseMode.HTML,
        )

    else:

        await update.effective_message.reply_text(
            f"🆔 <b>Your ID:</b> "
            f"<code>{user.id}</code>\n"
            f"💬 <b>This chat's ID:</b> "
            f"<code>{chat.id}</code>",
            parse_mode=ParseMode.HTML,
        )


async def info_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    msg = update.effective_message

    target = (
        msg.reply_to_message.from_user
        if msg.reply_to_message
        else update.effective_user
    )

    db.add_user(
        target.id,
        target.first_name or "",
        target.username or "",
    )

    status = db.get_approval_status(
        target.id
    )

    await msg.reply_text(
        f"👤 <b>USER INFO</b>\n\n"
        f"Name: {escape(target.first_name or 'User')}\n"
        f"ID: <code>{target.id}</code>\n"
        f"Access: <b>{db.get_status_name(status)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def rules_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_chat.type == ChatType.PRIVATE:

        await update.effective_message.reply_text(
            "📜 Group rules are shown inside groups."
        )

        return

    settings = db.get_group_settings(
        update.effective_chat.id
    )

    await update.effective_message.reply_text(
        f"<b>📜 GROUP RULES</b>\n\n"
        f"{escape(settings[4])}",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ADD MEMBER COMMAND
# ============================================================

async def addmember_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user
    msg = update.effective_message

    logger.info(
        "ADD MEMBER called | owner=%s | chat=%s | args=%s",
        user.id if user else None,
        update.effective_chat.id
        if update.effective_chat
        else None,
        context.args,
    )

    if not user or not is_owner(user.id):

        logger.warning(
            "ADD MEMBER denied | user=%s | configured_owner=%s",
            user.id if user else None,
            config.OWNER_ID,
        )

        await msg.reply_text(
            "❌ Owner only."
        )

        return

    if not context.args:

        await msg.reply_text(
            "Usage:\n"
            "/addmember <user_id>\n\n"
            "Example:\n"
            "/addmember 8420696977"
        )

        return

    if not context.args[0].lstrip("-").isdigit():

        await msg.reply_text(
            "❌ Invalid user ID."
        )

        return

    user_id = int(
        context.args[0]
    )

    await msg.reply_text(
        f"🔄 Processing invite for "
        f"<code>{user_id}</code>...",
        parse_mode=ParseMode.HTML,
    )

    ok, note = await send_group_invite(
        context,
        user_id,
    )

    logger.info(
        "ADD MEMBER result | user=%s | success=%s | result=%s",
        user_id,
        ok,
        note,
    )

    await msg.reply_text(
        f"{'✅' if ok else '⚠️'} {note}",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# OWNER PANEL
# ============================================================

async def panel_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_owner(
        update.effective_user.id
    ):

        await update.effective_message.reply_text(
            "❌ Owner only."
        )

        return

    await update.effective_message.reply_text(
        "👑 <b>Owner Control Panel</b>",
        reply_markup=kb.panel_keyboard(),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# GROUP SETTINGS
# ============================================================

async def settings_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_chat.type == ChatType.PRIVATE:

        await update.effective_message.reply_text(
            "⚙️ Use this inside a group."
        )

        return

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    db.ensure_group(
        update.effective_chat.id
    )

    await update.effective_message.reply_text(
        "⚙️ <b>Group Settings</b>\n\n"
        "Tap a button to toggle it.",
        reply_markup=kb.settings_root_keyboard(
            update.effective_chat.id
        ),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ADMIN MENU
# ============================================================

async def admin_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_chat.type == ChatType.PRIVATE:

        await update.effective_message.reply_text(
            "👮 Use this inside a group."
        )

        return

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    target = await get_reply_target(update)

    if not target:

        await update.effective_message.reply_text(
            "Reply to a user's message with "
            "/admin to open their action menu."
        )

        return

    await update.effective_message.reply_text(
        f"👮 <b>Moderation Menu</b>\n\n"
        f"Target: {mention(target)} "
        f"(<code>{target.id}</code>)",
        reply_markup=kb.modactions_keyboard(
            update.effective_chat.id,
            target.id,
        ),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# FEDERATION MENU
# ============================================================

async def fedmenu_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_chat.type == ChatType.PRIVATE:

        await update.effective_message.reply_text(
            "🌐 Use this inside a group."
        )

        return

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    await update.effective_message.reply_text(
        "🌐 <b>Federation Menu</b>",
        reply_markup=kb.fed_menu_keyboard(
            update.effective_chat.id
        ),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# VERIFY JOIN CALLBACK
# ============================================================

async def cb_verify_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    user = query.from_user

    db.add_user(
        user.id,
        user.first_name or "",
        user.username or "",
    )

    if db.get_approval_status(user.id) == APPROVED:

        await query.answer(
            "Already approved.",
            show_alert=True,
        )

        return

    joined, missing = await is_force_joined(
        context,
        user.id,
    )

    if not joined:

        names = "\n".join(
            f"📢 {escape(c['title'])}"
            for c in missing
        )

        await query.answer(
            "❌ Join all required channels first.",
            show_alert=True,
        )

        await query.message.edit_text(
            f"❌ <b>Verification Failed</b>\n\n"
            f"Still need to join:\n{names}",
            reply_markup=kb.force_join_keyboard(),
            parse_mode=ParseMode.HTML,
        )

        return

    db.set_verified(
        user.id,
        True,
    )

    await send_approval_request(
        context,
        user,
    )

    await query.answer(
        "✅ Verification successful!",
        show_alert=True,
    )

    await query.message.edit_text(
        "✅ <b>Verification Successful</b>\n\n"
        "⏳ Access pending owner approval.",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# MAIN MENU CALLBACK
# ============================================================

async def cb_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    action = query.data.split(
        ":",
        1,
    )[1]

    user = query.from_user

    if action == "main":

        await query.message.edit_text(
            "🏠 <b>Main Menu</b>",
            reply_markup=kb.main_menu_keyboard(
                is_owner(user.id)
            ),
            parse_mode=ParseMode.HTML,
        )

    elif action == "help":

        await query.message.edit_text(
            HELP_TEXT,
            reply_markup=kb.back_button(),
            parse_mode=ParseMode.HTML,
        )

    elif action == "rules":

        chat_id = (
            update.effective_chat.id
            if update.effective_chat.type != ChatType.PRIVATE
            else None
        )

        text = (
            escape(
                db.get_group_settings(chat_id)[4]
            )
            if chat_id
            else
            "📜 Rules are set per-group — "
            "open this in a group."
        )

        await query.message.edit_text(
            f"<b>📜 RULES</b>\n\n{text}",
            reply_markup=kb.back_button(),
            parse_mode=ParseMode.HTML,
        )

    elif action == "myinfo":

        status = db.get_approval_status(
            user.id
        )

        await query.message.edit_text(
            f"👤 <b>USER INFO</b>\n\n"
            f"Name: {escape(user.first_name or 'User')}\n"
            f"ID: <code>{user.id}</code>\n"
            f"Access: <b>{db.get_status_name(status)}</b>",
            reply_markup=kb.back_button(),
            parse_mode=ParseMode.HTML,
        )

    elif action == "myid":

        await query.message.edit_text(
            f"🆔 <b>Your ID:</b> "
            f"<code>{user.id}</code>",
            reply_markup=kb.back_button(),
            parse_mode=ParseMode.HTML,
        )


async def cb_noop(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.callback_query.answer()


# ============================================================
# APPROVAL CALLBACK
# ============================================================

async def cb_approval(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if query.from_user.id != config.OWNER_ID:

        await query.answer(
            "❌ Owner only.",
            show_alert=True,
        )

        return

    action, user_id_text = query.data.split(
        ":"
    )

    user_id = int(
        user_id_text
    )

    row = db.get_user(
        user_id
    )

    if not row:

        await query.answer(
            "❌ User not found.",
            show_alert=True,
        )

        return

    status_map = {
        "approve": APPROVED,
        "reject": REJECTED,
        "reapprove": APPROVED,
        "revoke": REVOKED,
    }

    status = status_map[action]

    db.set_approval(
        user_id,
        status,
    )

    await query.answer(
        "Updated."
    )

    text = (
        "👤 <b>USER ACCESS CONTROL</b>\n\n"
        f"Name: <b>{escape(row[1] or 'User')}</b>\n"
        f"Username: "
        f"@{escape(row[2]) if row[2] else 'none'}\n"
        f"ID: <code>{user_id}</code>\n\n"
        f"Status: <b>{db.get_status_name(status)}</b>"
    )

    await query.message.edit_text(
        text,
        reply_markup=kb.approval_keyboard(
            user_id
        ),
        parse_mode=ParseMode.HTML,
    )

    messages = {
        APPROVED:
            "🎉 <b>ACCESS APPROVED</b>\n\n"
            "You can now use the bot.",

        REJECTED:
            "🔴 <b>ACCESS REJECTED</b>",

        REVOKED:
            "🚫 <b>ACCESS REVOKED</b>\n\n"
            "Join the required channels again "
            "and re-verify.",
    }

    try:

        await context.bot.send_message(
            user_id,
            messages[status],
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:

        logger.warning(
            "Could not notify user %s: %s",
            user_id,
            e,
        )

    if status == APPROVED:

        ok, note = await send_group_invite(
            context,
            user_id,
        )

        await query.message.reply_text(
            f"{'✅' if ok else '⚠️'} {note}",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# USER LIST
# ============================================================

def build_user_list_view(
    status: int,
):

    conn = db.get_connection()

    rows = conn.execute(
        """
        SELECT user_id, first_name, username
        FROM users
        WHERE approved=?
        ORDER BY user_id DESC
        LIMIT 10
        """,
        (status,),
    ).fetchall()

    conn.close()

    if not rows:

        text = (
            f"No users with status "
            f"{db.get_status_name(status)}."
        )

    else:

        lines = [
            f"{db.get_status_name(status)} "
            f"users (latest {len(rows)}):\n"
        ]

        for uid, fname, uname in rows:

            lines.append(
                f"• {escape(fname or 'User')} "
                f"(@{escape(uname) if uname else 'none'}) "
                f"— <code>{uid}</code>"
            )

        text = "\n".join(
            lines
        )

    return text, kb.user_list_keyboard(
        rows,
        status,
    )


async def cb_list_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if query.from_user.id != config.OWNER_ID:

        await query.answer(
            "❌ Owner only.",
            show_alert=True,
        )

        return

    _, action, status_s, uid_s = (
        query.data.split(":")
    )

    uid = int(uid_s)

    status_map = {
        "approve": APPROVED,
        "reject": REJECTED,
        "revoke": REVOKED,
    }

    new_status = status_map[action]

    db.set_approval(
        uid,
        new_status,
    )

    messages = {
        APPROVED:
            "🎉 <b>ACCESS APPROVED</b>\n\n"
            "You can now use the bot.",

        REJECTED:
            "🔴 <b>ACCESS REJECTED</b>",

        REVOKED:
            "🚫 <b>ACCESS REVOKED</b>\n\n"
            "Join the required channels again "
            "and re-verify.",
    }

    try:

        await context.bot.send_message(
            uid,
            messages[new_status],
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:

        logger.warning(
            "Could not notify %s: %s",
            uid,
            e,
        )

    if new_status == APPROVED:

        ok, note = await send_group_invite(
            context,
            uid,
        )

        await query.answer(
            "✅ Approved. Invite link sent."
            if ok
            else
            f"✅ Approved, but: {note}",
            show_alert=not ok,
        )

    else:

        await query.answer(
            f"Updated to "
            f"{db.get_status_name(new_status)}."
        )

    text, markup = build_user_list_view(
        int(status_s)
    )

    await query.message.edit_text(
        text,
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# OWNER PANEL CALLBACK
# ============================================================

async def cb_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if query.from_user.id != config.OWNER_ID:

        await query.answer(
            "❌ Owner only.",
            show_alert=True,
        )

        return

    await query.answer()

    parts = query.data.split(":")
    section = parts[1]

    if section == "main":

        await query.message.edit_text(
            "👑 <b>Owner Control Panel</b>",
            reply_markup=kb.panel_keyboard(),
            parse_mode=ParseMode.HTML,
        )

    elif section == "stats":

        text = (
            "📊 <b>BOT STATISTICS</b>\n\n"
            f"👥 Users: "
            f"<b>{db.get_user_count()}</b>\n"
            f"✅ Verified: "
            f"<b>{db.get_verified_count()}</b>\n"
            f"🟢 Approved: "
            f"<b>{db.get_count_by_status(APPROVED)}</b>\n"
            f"🟡 Pending: "
            f"<b>{db.get_count_by_status(PENDING)}</b>\n"
            f"🔴 Rejected: "
            f"<b>{db.get_count_by_status(REJECTED)}</b>\n"
            f"🚫 Revoked: "
            f"<b>{db.get_count_by_status(REVOKED)}</b>"
        )

        await query.message.edit_text(
            text,
            reply_markup=kb.back_button(
                "panel:main"
            ),
            parse_mode=ParseMode.HTML,
        )

    elif section == "users":

        await query.message.edit_text(
            "👥 <b>User Management</b>\n\n"
            "Pick a status to view.",
            reply_markup=kb.users_panel_keyboard(),
            parse_mode=ParseMode.HTML,
        )

    elif section == "list":

        status = int(parts[2])

        text, markup = build_user_list_view(
            status
        )

        await query.message.edit_text(
            text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )

    elif section == "fed":

        conn = db.get_connection()

        feds = conn.execute(
            """
            SELECT fed_id, name, owner_id
            FROM federations
            """
        ).fetchall()

        conn.close()

        if not feds:

            text = (
                "🌐 No federations exist yet. "
                "Create one from a group with "
                "/fedmenu."
            )

        else:

            lines = [
                "🌐 <b>Federations</b>\n"
            ]

            for fed_id, name, owner_id in feds:

                lines.append(
                    f"• {escape(name)} — "
                    f"<code>{fed_id}</code> "
                    f"(owner <code>{owner_id}</code>)"
                )

            text = "\n".join(
                lines
            )

        await query.message.edit_text(
            text,
            reply_markup=kb.back_button(
                "panel:main"
            ),
            parse_mode=ParseMode.HTML,
        )

    elif section == "help":

        await query.message.edit_text(
            HELP_TEXT,
            reply_markup=kb.back_button(
                "panel:main"
            ),
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# GROUP SETTINGS CALLBACK
# ============================================================

async def cb_settings(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not await is_admin(update):

        await query.answer(
            "❌ Admins only.",
            show_alert=True,
        )

        return

    await query.answer()

    chat_id = update.effective_chat.id

    action = query.data.split(
        ":",
        1,
    )[1]

    if action == "root":

        await query.message.edit_text(
            "⚙️ <b>Group Settings</b>",
            reply_markup=kb.settings_root_keyboard(
                chat_id
            ),
            parse_mode=ParseMode.HTML,
        )

    elif action == "toggle_welcome":

        s = db.get_group_settings(
            chat_id
        )

        db.set_welcome_enabled(
            chat_id,
            not s[0],
        )

        await query.message.edit_reply_markup(
            reply_markup=kb.settings_root_keyboard(
                chat_id
            )
        )

    elif action == "toggle_goodbye":

        s = db.get_group_settings(
            chat_id
        )

        db.set_goodbye_enabled(
            chat_id,
            not s[2],
        )

        await query.message.edit_reply_markup(
            reply_markup=kb.settings_root_keyboard(
                chat_id
            )
        )

    elif action == "warnlimit":

        await query.message.edit_text(
            "⚠️ <b>Warn Limit</b>\n\n"
            "How many warns before auto-ban.",
            reply_markup=kb.warnlimit_keyboard(
                chat_id
            ),
            parse_mode=ParseMode.HTML,
        )

    elif action == "locks":

        await query.message.edit_text(
            "🔒 <b>Locks</b>\n\n"
            "Tap to toggle each restriction.",
            reply_markup=kb.locks_keyboard(
                chat_id
            ),
            parse_mode=ParseMode.HTML,
        )


async def cb_warnlimit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not await is_admin(update):

        await query.answer(
            "❌ Admins only.",
            show_alert=True,
        )

        return

    chat_id = update.effective_chat.id

    current = db.get_group_settings(
        chat_id
    )[5]

    delta = (
        1
        if query.data.endswith("+")
        else -1
    )

    new_limit = db.set_warn_limit(
        chat_id,
        current + delta,
    )

    await query.answer(
        f"Warn limit: {new_limit}"
    )

    await query.message.edit_reply_markup(
        reply_markup=kb.warnlimit_keyboard(
            chat_id
        )
    )


async def cb_lock(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not await is_admin(update):

        await query.answer(
            "❌ Admins only.",
            show_alert=True,
        )

        return

    chat_id = update.effective_chat.id

    lock_type = query.data.split(
        ":",
        1,
    )[1]

    new_state = db.toggle_lock(
        chat_id,
        lock_type,
    )

    await query.answer(
        f"{lock_type.title()} lock: "
        f"{'ON' if new_state else 'OFF'}"
    )

    await query.message.edit_reply_markup(
        reply_markup=kb.locks_keyboard(
            chat_id
        )
    )


# ============================================================
# MODERATION
# ============================================================

async def cb_modaction(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not await is_admin(update):

        await query.answer(
            "❌ Admins only.",
            show_alert=True,
        )

        return

    _, action, chat_id_s, user_id_s = (
        query.data.split(":")
    )

    chat_id = int(chat_id_s)
    target_id = int(user_id_s)

    try:

        if action == "warn":

            count = db.add_warn(
                chat_id,
                target_id,
            )

            limit = db.get_group_settings(
                chat_id
            )[5]

            if count >= limit:

                await context.bot.ban_chat_member(
                    chat_id,
                    target_id,
                )

                db.reset_warns(
                    chat_id,
                    target_id,
                )

                await query.answer(
                    "⚠️→🔨 Warn limit reached, "
                    "user banned.",
                    show_alert=True,
                )

            else:

                await query.answer(
                    f"⚠️ Warned ({count}/{limit})"
                )

        elif action == "unwarn":

            db.reset_warns(
                chat_id,
                target_id,
            )

            await query.answer(
                "♻️ Warnings cleared."
            )

        elif action == "mute":

            await context.bot.restrict_chat_member(
                chat_id,
                target_id,
                permissions=ChatPermissions(
                    can_send_messages=False
                ),
            )

            await query.answer(
                "🔇 Muted."
            )

        elif action == "unmute":

            await context.bot.restrict_chat_member(
                chat_id,
                target_id,
                permissions=ChatPermissions.all_permissions(),
            )

            await query.answer(
                "🔊 Unmuted."
            )

        elif action == "kick":

            await context.bot.ban_chat_member(
                chat_id,
                target_id,
            )

            await context.bot.unban_chat_member(
                chat_id,
                target_id,
            )

            await query.answer(
                "👢 Kicked."
            )

        elif action == "ban":

            await context.bot.ban_chat_member(
                chat_id,
                target_id,
            )

            await query.answer(
                "🔨 Banned."
            )

        elif action == "unban":

            await context.bot.unban_chat_member(
                chat_id,
                target_id,
                only_if_banned=True,
            )

            await query.answer(
                "✅ Unbanned."
            )

    except Exception as e:

        logger.exception(
            "Moderation action failed"
        )

        await query.answer(
            f"❌ Failed: {e}",
            show_alert=True,
        )

        return

    warns = db.get_warns(
        chat_id,
        target_id,
    )

    try:

        await query.message.edit_text(
            f"👮 <b>Moderation Menu</b>\n\n"
            f"Target ID: <code>{target_id}</code>\n"
            f"Warnings: {warns}",
            reply_markup=kb.modactions_keyboard(
                chat_id,
                target_id,
            ),
            parse_mode=ParseMode.HTML,
        )

    except Exception:
        pass


# ============================================================
# FEDERATION CALLBACK
# ============================================================

async def cb_fed(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not await is_admin(update):

        await query.answer(
            "❌ Admins only.",
            show_alert=True,
        )

        return

    await query.answer()

    chat_id = update.effective_chat.id

    action = query.data.split(
        ":",
        1,
    )[1]

    if action == "new":

        fed_id = uuid.uuid4().hex[:10].upper()

        name = (
            update.effective_chat.title
            or "Federation"
        )

        db.create_federation(
            fed_id,
            name,
            query.from_user.id,
        )

        db.add_fed_chat(
            fed_id,
            chat_id,
        )

        await query.message.edit_text(
            f"🌐 <b>Federation Created</b>\n\n"
            f"Name: {escape(name)}\n"
            f"ID: <code>{fed_id}</code>",
            reply_markup=kb.fed_menu_keyboard(
                chat_id
            ),
            parse_mode=ParseMode.HTML,
        )

    elif action == "info":

        fed = db.get_chat_federation(
            chat_id
        )

        if not fed:

            text = (
                "🌐 This chat isn't in a federation."
            )

        else:

            fed_id, name, owner_id = fed

            chats = db.get_federation_chats(
                fed_id
            )

            text = (
                f"🌐 <b>{escape(name)}</b>\n"
                f"ID: <code>{fed_id}</code>\n"
                f"Linked chats: {len(chats)}"
            )

        await query.message.edit_text(
            text,
            reply_markup=kb.fed_menu_keyboard(
                chat_id
            ),
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# MEMBER EVENTS
# ============================================================

async def member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.chat_member:
        return

    result = update.chat_member

    old = result.old_chat_member.status
    new = result.new_chat_member.status

    user = result.new_chat_member.user

    chat_id = update.effective_chat.id

    # --------------------------------------------------------
    # WELCOME
    # --------------------------------------------------------

    if (
        new in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.RESTRICTED,
        )
        and old not in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.RESTRICTED,
        )
    ):

        db.ensure_group(chat_id)

        settings = db.get_group_settings(
            chat_id
        )

        if not settings[0]:
            return

        try:

            text = settings[1].format(
                mention=mention(user),
                name=escape(
                    user.first_name or "User"
                ),
                username=(
                    "@"
                    + escape(user.username)
                    if user.username
                    else ""
                ),
                id=user.id,
                chatname=escape(
                    update.effective_chat.title
                    or ""
                ),
            )

        except Exception:

            text = (
                f"🌹 Welcome "
                f"{mention(user)}!"
            )

        await context.bot.send_message(
            chat_id,
            text,
            parse_mode=ParseMode.HTML,
        )

    # --------------------------------------------------------
    # GOODBYE
    # --------------------------------------------------------

    elif (
        old in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.RESTRICTED,
        )
        and new in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.BANNED,
        )
    ):

        db.ensure_group(chat_id)

        settings = db.get_group_settings(
            chat_id
        )

        if not settings[2]:
            return

        try:

            text = settings[3].format(
                mention=mention(user),
                name=escape(
                    user.first_name or "User"
                ),
                username=(
                    "@"
                    + escape(user.username)
                    if user.username
                    else ""
                ),
                id=user.id,
                chatname=escape(
                    update.effective_chat.title
                    or ""
                ),
            )

        except Exception:

            text = (
                f"👋 "
                f"{escape(user.first_name or 'User')} "
                f"has left the group."
            )

        await context.bot.send_message(
            chat_id,
            text,
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context,
):

    logger.error(
        "Update error: %s",
        context.error,
        exc_info=(
            type(context.error),
            context.error,
            context.error.__traceback__
            if context.error
            else None,
        ),
    )


# ============================================================
# MAIN
# ============================================================

def main():

    db.init_db()

    app = (
        Application
        .builder()
        .token(config.BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_cmd,
        )
    )

    app.add_handler(
        CommandHandler(
            "id",
            id_cmd,
        )
    )

    app.add_handler(
        CommandHandler(
            "info",
            info_cmd,
        )
    )

    app.add_handler(
        CommandHandler(
            "rules",
            rules_cmd,
        )
    )

    app.add_handler(
        CommandHandler(
            "panel",
            panel_cmd,
        )
    )

    app.add_handler(
        CommandHandler(
            "addmember",
            addmember_cmd,
        )
    )

    app.add_handler(
        CommandHandler(
            "settings",
            settings_cmd,
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_cmd,
        )
    )

    app.add_handler(
        CommandHandler(
            "fedmenu",
            fedmenu_cmd,
        )
    )

    # --------------------------------------------------------
    # CALLBACKS
    # --------------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            cb_verify_join,
            pattern=r"^verify_join$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cb_menu,
            pattern=r"^menu:",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cb_noop,
            pattern=r"^noop$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cb_approval,
            pattern=r"^(approve|reject|reapprove|revoke):",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cb_panel,
            pattern=r"^panel:",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cb_list_action,
            pattern=r"^lact:",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cb_warnlimit,
            pattern=r"^warnlimit:",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cb_lock,
            pattern=r"^lock:",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cb_settings,
            pattern=r"^settings:",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cb_modaction,
            pattern=r"^mod:",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cb_fed,
            pattern=r"^fed:",
        )
    )

    # --------------------------------------------------------
    # MEMBER EVENTS
    # --------------------------------------------------------

    app.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    # --------------------------------------------------------
    # ERROR HANDLER
    # --------------------------------------------------------

    app.add_error_handler(
        error_handler
    )

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    logger.info(
        "Bot starting (button-driven UI)..."
    )

    app.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
