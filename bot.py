import os
import logging

from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler,
)

import database


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

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
# DATABASE
# ============================================================

database.init_db()


# ============================================================
# FORCE JOIN
# ============================================================

FORCE_JOIN_CHANNELS = [
    "-1003998560024",
    "-1004077604887",
]


# ============================================================
# APPROVAL STATUS
# ============================================================

PENDING = 0
APPROVED = 1
REJECTED = 2
REVOKED = 3


# ============================================================
# HELPERS
# ============================================================

def mention_user(user):

    return user.first_name or "User"


def status_name(status):

    return {
        PENDING: "⏳ Pending",
        APPROVED: "✅ Approved",
        REJECTED: "❌ Rejected",
        REVOKED: "🚫 Revoked",
    }.get(status, "❓ Unknown")


# ============================================================
# ADMIN
# ============================================================

async def is_admin(
    update: Update,
    user_id: int = None,
) -> bool:

    if not update.effective_chat:
        return False

    if user_id is None:

        if not update.effective_user:
            return False

        user_id = update.effective_user.id

    if user_id == OWNER_ID:
        return True

    if update.effective_chat.type == "private":
        return False

    try:

        member = await update.effective_chat.get_member(
            user_id
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception as e:

        logger.error(
            "Admin check failed: %s",
            e,
        )

        return False


# ============================================================
# MEMBERSHIP CHECK
# ============================================================

async def check_membership(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: str,
) -> bool:

    try:

        member = await context.bot.get_chat_member(
            chat_id=int(chat_id),
            user_id=user_id,
        )

        logger.info(
            "Membership | user=%s | channel=%s | status=%s",
            user_id,
            chat_id,
            member.status,
        )

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            ChatMemberStatus.RESTRICTED,
        )

    except Exception as e:

        logger.error(
            "Membership failed | user=%s | channel=%s | error=%s",
            user_id,
            chat_id,
            e,
        )

        return False


async def is_force_joined(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> bool:

    for channel_id in FORCE_JOIN_CHANNELS:

        if not await check_membership(
            context,
            user_id,
            channel_id,
        ):

            return False

    return True


# ============================================================
# FORCE JOIN KEYBOARD
# ============================================================

def force_join_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📢 Join Channel 1",
                url="https://t.me/+RsAsljvxgWZKkNzg1",
            )
        ],

        [
            InlineKeyboardButton(
                "📢 Join Channel 2",
                url="https://t.me/Il_Ravan_bhai_ll",
            )
        ],

        [
            InlineKeyboardButton(
                "✅ I've Joined",
                callback_data="verify_join",
            )
        ],

    ])


# ============================================================
# REQUEST APPROVAL KEYBOARD
# ============================================================

def request_approval_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📨 Request Approval",
                callback_data="request_approval",
            )
        ],

        [
            InlineKeyboardButton(
                "🔄 Check Membership",
                callback_data="verify_join",
            )
        ],

    ])


# ============================================================
# OWNER APPROVAL BUTTONS
# ============================================================

def approval_keyboard(
    user_id: int,
):

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
                "🚫 Revoke",
                callback_data=f"revoke:{user_id}",
            ),

            InlineKeyboardButton(
                "🔄 Re-Approve",
                callback_data=f"reapprove:{user_id}",
            ),
        ],

    ])


# ============================================================
# FORCE JOIN MESSAGE
# ============================================================

async def force_join_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "🔐 <b>Access Locked</b>\n\n"
        "To use this bot, you must join all required channels.\n\n"
        "1️⃣ Join Channel 1\n"
        "2️⃣ Join Channel 2\n\n"
        "After joining both channels, press "
        "<b>I've Joined</b>."
    )

    if update.callback_query:

        await update.callback_query.message.edit_text(
            text,
            reply_markup=force_join_keyboard(),
            parse_mode="HTML",
        )

    else:

        await update.effective_message.reply_text(
            text,
            reply_markup=force_join_keyboard(),
            parse_mode="HTML",
        )


# ============================================================
# SEND APPROVAL REQUEST TO OWNER
# ============================================================

async def send_approval_request(
    context: ContextTypes.DEFAULT_TYPE,
    user,
):

    username = (
        f"@{user.username}"
        if user.username
        else "No username"
    )

    text = (
        "🔔 <b>NEW ACCESS REQUEST</b>\n\n"
        f"👤 Name: <b>{mention_user(user)}</b>\n"
        f"🔗 Username: <b>{username}</b>\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        "📢 User has joined all required channels.\n\n"
        "Select an action:"
    )

    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=text,
        reply_markup=approval_keyboard(user.id),
        parse_mode="HTML",
    )


# ============================================================
# ACCESS REQUEST
# ============================================================

async def request_approval(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    user = query.from_user

    try:
        await query.answer(
            "📨 Sending approval request..."
        )
    except Exception:
        pass

    # Check membership again
    joined = await is_force_joined(
        context,
        user.id,
    )

    if not joined:

        await query.message.edit_text(
            "❌ <b>Channels Not Joined</b>\n\n"
            "You must join all required channels first.",
            reply_markup=force_join_keyboard(),
            parse_mode="HTML",
        )

        return

    database.add_user(
        user.id,
        user.first_name or "",
        user.username or "",
    )

    current_status = database.get_approval_status(
        user.id
    )

    # Already approved
    if current_status == APPROVED:

        await query.message.edit_text(
            "✅ <b>Already Approved</b>\n\n"
            "Your access is already active.\n\n"
            "Use /help to continue.",
            parse_mode="HTML",
        )

        return

    # Already pending
    if current_status == PENDING:

        await query.message.edit_text(
            "⏳ <b>Request Already Sent</b>\n\n"
            "Your approval request is waiting for the owner.\n\n"
            "Please wait for the decision.",
            parse_mode="HTML",
        )

        return

    # Rejected / revoked -> allowed to request again
    database.set_approval(
        user.id,
        PENDING,
    )

    await send_approval_request(
        context,
        user,
    )

    await query.message.edit_text(
        "📨 <b>Approval Request Sent</b>\n\n"
        "Your request has been sent to the owner.\n\n"
        "⏳ Please wait for approval.",
        parse_mode="HTML",
    )


# ============================================================
# VERIFY JOIN
# ============================================================

async def verify_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    user = query.from_user

    try:

        await query.answer(
            "🔍 Checking your membership..."
        )

        await query.message.edit_text(
            "🔍 <b>Checking your membership...</b>\n\n"
            "Please wait...",
            parse_mode="HTML",
        )

    except Exception as e:

        logger.warning(
            "Verification UI error: %s",
            e,
        )

    try:

        joined = await is_force_joined(
            context,
            user.id,
        )

        if not joined:

            await query.message.edit_text(
                "❌ <b>Verification Failed</b>\n\n"
                "You have not joined all required channels.\n\n"
                "Please join both channels and try again.",
                reply_markup=force_join_keyboard(),
                parse_mode="HTML",
            )

            return

        database.add_user(
            user.id,
            user.first_name or "",
            user.username or "",
        )

        status = database.get_approval_status(
            user.id
        )

        # ----------------------------------------------------
        # ALREADY APPROVED
        # ----------------------------------------------------

        if status == APPROVED:

            await query.message.edit_text(
                "✅ <b>Already Approved</b>\n\n"
                "🔓 Your access is already active.\n\n"
                "Use /help to see available commands.",
                parse_mode="HTML",
            )

            return

        # ----------------------------------------------------
        # PENDING
        # ----------------------------------------------------

        if status == PENDING:

            await query.message.edit_text(
                "⏳ <b>Approval Pending</b>\n\n"
                "You have joined all required channels.\n\n"
                "📨 Your approval request is already "
                "waiting for the owner.\n\n"
                "Please wait.",
                parse_mode="HTML",
            )

            return

        # ----------------------------------------------------
        # REJECTED / REVOKED
        # ----------------------------------------------------

        if status in (
            REJECTED,
            REVOKED,
        ):

            await query.message.edit_text(
                f"{status_name(status)}\n\n"
                "Your previous access is no longer active.\n\n"
                "You can request access again.",
                reply_markup=request_approval_keyboard(),
                parse_mode="HTML",
            )

            return

        # ----------------------------------------------------
        # FIRST REQUEST
        # ----------------------------------------------------

        database.set_verified(
            user.id,
            True,
        )

        database.set_approval(
            user.id,
            PENDING,
        )

        await send_approval_request(
            context,
            user,
        )

        await query.message.edit_text(
            "📨 <b>Approval Request Sent</b>\n\n"
            "You have successfully joined all required "
            "channels.\n\n"
            "⏳ Your request has been sent to the owner.\n"
            "Please wait for approval.",
            parse_mode="HTML",
        )

    except Exception as e:

        logger.exception(
            "Verification error: %s",
            e,
        )

        try:

            await query.message.edit_text(
                "⚠️ <b>Verification Error</b>\n\n"
                "Please try again.",
                reply_markup=force_join_keyboard(),
                parse_mode="HTML",
            )

        except Exception:
            pass


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

    database.add_user(
        user.id,
        user.first_name or "",
        user.username or "",
    )

    # Owner bypass
    if user.id == OWNER_ID:

        await update.effective_message.reply_text(
            "👑 <b>Welcome Owner!</b>\n\n"
            "🛡️ <b>JoinGuard Bot</b>\n\n"
            "Use /panel for the owner panel.\n"
            "Use /help for commands.",
            parse_mode="HTML",
        )

        return

    # Check channels
    joined = await is_force_joined(
        context,
        user.id,
    )

    if not joined:

        await force_join_message(
            update,
            context,
        )

        return

    status = database.get_approval_status(
        user.id
    )

    # Approved
    if status == APPROVED:

        await update.effective_message.reply_text(
            f"👋 <b>Welcome {mention_user(user)}!</b>\n\n"
            "🟢 <b>Access: APPROVED</b>\n\n"
            "Use /help to see available commands.",
            parse_mode="HTML",
        )

        return

    # Pending
    if status == PENDING:

        await update.effective_message.reply_text(
            "⏳ <b>Approval Pending</b>\n\n"
            "Your request is waiting for owner approval.\n\n"
            "Please wait.",
            parse_mode="HTML",
        )

        return

    # Rejected / revoked
    if status in (
        REJECTED,
        REVOKED,
    ):

        await update.effective_message.reply_text(
            f"{status_name(status)}\n\n"
            "Your previous access is not active.\n\n"
            "You can request access again.",
            reply_markup=request_approval_keyboard(),
            parse_mode="HTML",
        )

        return

    # First time
    await update.effective_message.reply_text(
        "📨 <b>Access Request</b>\n\n"
        "You have joined all required channels.\n\n"
        "Click below to request approval.",
        reply_markup=request_approval_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# APPROVE COMMAND
# ============================================================

async def approve_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user or user.id != OWNER_ID:

        await update.effective_message.reply_text(
            "❌ Owner only."
        )

        return

    if not context.args:

        await update.effective_message.reply_text(
            "Usage:\n"
            "/approve @username"
        )

        return

    username = context.args[0]

    target = database.get_user_by_username(
        username
    )

    if not target:

        await update.effective_message.reply_text(
            f"❌ User {username} was not found.\n\n"
            "The user must have started the bot first."
        )

        return

    user_id = target[0]
    name = target[1] or "User"
    current = target[4]

    database.set_approval(
        user_id,
        APPROVED,
    )

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "✅ <b>Access Approved!</b>\n\n"
                "🎉 Your request has been approved by the owner.\n\n"
                "🔓 Your bot access is now active.\n\n"
                "Use /help to continue."
            ),
            parse_mode="HTML",
        )

    except Exception as e:

        logger.warning(
            "Could not notify approved user %s: %s",
            user_id,
            e,
        )

    await update.effective_message.reply_text(
        "✅ <b>User Approved</b>\n\n"
        f"👤 {name}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"🔗 {username}\n\n"
        f"Previous status: <b>{status_name(current)}</b>\n"
        "New status: <b>✅ Approved</b>",
        parse_mode="HTML",
    )


# ============================================================
# REJECT COMMAND
# ============================================================

async def reject_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_user.id != OWNER_ID:

        await update.effective_message.reply_text(
            "❌ Owner only."
        )

        return

    if not context.args:

        await update.effective_message.reply_text(
            "Usage:\n"
            "/reject @username"
        )

        return

    target = database.get_user_by_username(
        context.args[0]
    )

    if not target:

        await update.effective_message.reply_text(
            "❌ User not found."
        )

        return

    user_id = target[0]

    database.set_approval(
        user_id,
        REJECTED,
    )

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ <b>Access Rejected</b>\n\n"
                "Your access request has been rejected.\n\n"
                "You may request access again later."
            ),
            reply_markup=request_approval_keyboard(),
            parse_mode="HTML",
        )

    except Exception:
        pass

    await update.effective_message.reply_text(
        "❌ User rejected successfully."
    )


# ============================================================
# REVOKE COMMAND
# ============================================================

async def revoke_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_user.id != OWNER_ID:

        await update.effective_message.reply_text(
            "❌ Owner only."
        )

        return

    if not context.args:

        await update.effective_message.reply_text(
            "Usage:\n"
            "/revoke @username"
        )

        return

    target = database.get_user_by_username(
        context.args[0]
    )

    if not target:

        await update.effective_message.reply_text(
            "❌ User not found."
        )

        return

    user_id = target[0]

    database.set_approval(
        user_id,
        REVOKED,
    )

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🚫 <b>Access Revoked</b>\n\n"
                "Your bot access has been revoked.\n\n"
                "If you need access again, you can submit "
                "a new request."
            ),
            reply_markup=request_approval_keyboard(),
            parse_mode="HTML",
        )

    except Exception:
        pass

    await update.effective_message.reply_text(
        "🚫 User access revoked."
    )


# ============================================================
# RE-APPROVE COMMAND
# ============================================================

async def reapprove_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_user.id != OWNER_ID:

        await update.effective_message.reply_text(
            "❌ Owner only."
        )

        return

    if not context.args:

        await update.effective_message.reply_text(
            "Usage:\n"
            "/reapprove @username"
        )

        return

    target = database.get_user_by_username(
        context.args[0]
    )

    if not target:

        await update.effective_message.reply_text(
            "❌ User not found."
        )

        return

    user_id = target[0]

    database.set_approval(
        user_id,
        APPROVED,
    )

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🔄 <b>Access Re-Approved!</b>\n\n"
                "Your access has been restored.\n\n"
                "🔓 You can use the bot again."
            ),
            parse_mode="HTML",
        )

    except Exception:
        pass

    await update.effective_message.reply_text(
        "🔄 User re-approved successfully."
    )


# ============================================================
# APPROVAL BUTTON CALLBACK
# ============================================================

async def approval_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    if query.from_user.id != OWNER_ID:

        await query.answer(
            "❌ Owner only.",
            show_alert=True,
        )

        return

    data = query.data

    try:

        action, user_id_text = data.split(
            ":",
            1,
        )

        user_id = int(user_id_text)

    except Exception:

        await query.answer(
            "❌ Invalid request.",
            show_alert=True,
        )

        return

    target = database.get_user(
        user_id
    )

    if not target:

        await query.answer(
            "❌ User not found.",
            show_alert=True,
        )

        return

    name = target[1] or "User"
    username = target[2] or "No username"
    old_status = target[4]

    # --------------------------------------------------------
    # APPROVE
    # --------------------------------------------------------

    if action == "approve":

        database.set_approval(
            user_id,
            APPROVED,
        )

        new_status = APPROVED

        message = (
            "✅ <b>Access Approved</b>\n\n"
            f"👤 {name}\n"
            f"🔗 @{username.lstrip('@') if username != 'No username' else 'No username'}\n"
            f"🆔 <code>{user_id}</code>"
        )

        user_message = (
            "✅ <b>Access Approved!</b>\n\n"
            "🎉 The owner approved your request.\n\n"
            "🔓 Your access is now active.\n\n"
            "Use /help to continue."
        )

    # --------------------------------------------------------
    # REJECT
    # --------------------------------------------------------

    elif action == "reject":

        database.set_approval(
            user_id,
            REJECTED,
        )

        new_status = REJECTED

        message = (
            "❌ <b>Access Rejected</b>\n\n"
            f"👤 {name}\n"
            f"🆔 <code>{user_id}</code>\n\n"
            "User can request again."
        )

        user_message = (
            "❌ <b>Access Rejected</b>\n\n"
            "Your request has been rejected.\n\n"
            "You can request access again later."
        )

    # --------------------------------------------------------
    # REVOKE
    # --------------------------------------------------------

    elif action == "revoke":

        database.set_approval(
            user_id,
            REVOKED,
        )

        new_status = REVOKED

        message = (
            "🚫 <b>Access Revoked</b>\n\n"
            f"👤 {name}\n"
            f"🆔 <code>{user_id}</code>\n\n"
            "User can request access again."
        )

        user_message = (
            "🚫 <b>Access Revoked</b>\n\n"
            "Your bot access has been revoked.\n\n"
            "You can submit a new request if you "
            "need access again."
        )

    # --------------------------------------------------------
    # RE-APPROVE
    # --------------------------------------------------------

    elif action == "reapprove":

        database.set_approval(
            user_id,
            APPROVED,
        )

        new_status = APPROVED

        message = (
            "🔄 <b>Access Re-Approved</b>\n\n"
            f"👤 {name}\n"
            f"🆔 <code>{user_id}</code>\n\n"
            "Access restored."
        )

        user_message = (
            "🔄 <b>Access Re-Approved!</b>\n\n"
            "Your access has been restored.\n\n"
            "🔓 You can use the bot again."
        )

    else:

        await query.answer(
            "❌ Unknown action.",
            show_alert=True,
        )

        return

    # Answer callback
    try:

        await query.answer(
            "✅ Action completed."
        )

    except Exception:
        pass

    # Notify user
    try:

        keyboard = None

        if new_status in (
            REJECTED,
            REVOKED,
        ):

            keyboard = request_approval_keyboard()

        await context.bot.send_message(
            chat_id=user_id,
            text=user_message,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    except Exception as e:

        logger.warning(
            "Could not notify user %s: %s",
            user_id,
            e,
        )

    # Update owner message
    await query.message.edit_text(
        message
        + "\n\n"
        + f"Previous: <b>{status_name(old_status)}</b>\n"
        + f"Current: <b>{status_name(new_status)}</b>",
        parse_mode="HTML",
    )


# ============================================================
# PANEL KEYBOARD
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
                "📢 Channels",
                callback_data="panel_channels",
            ),
            InlineKeyboardButton(
                "⚙️ Group",
                callback_data="panel_group",
            ),
        ],

        [
            InlineKeyboardButton(
                "🌹 Rose Commands",
                callback_data="rose_menu",
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
                "📖 Help",
                callback_data="panel_help",
            ),
        ],

    ])


# ============================================================
# PANEL
# ============================================================

async def panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user:
        return

    if user.id != OWNER_ID:

        await update.effective_message.reply_text(
            "❌ <b>Owner Only</b>\n\n"
            "You are not authorized to use the owner panel.",
            parse_mode="HTML",
        )

        return

    await update.effective_message.reply_text(
        "👑 <b>OWNER CONTROL PANEL</b>\n\n"
        "🛡️ JoinGuard Bot\n\n"
        "Select an option below:",
        reply_markup=panel_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# ROSE MENU
# ============================================================

def rose_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🛡 Moderation",
                callback_data="rose_moderation",
            )
        ],

        [
            InlineKeyboardButton(
                "🔒 Locks",
                callback_data="rose_locks",
            )
        ],

        [
            InlineKeyboardButton(
                "👋 Welcome",
                callback_data="rose_welcome",
            )
        ],

        [
            InlineKeyboardButton(
                "📜 Rules",
                callback_data="rose_rules",
            )
        ],

        [
            InlineKeyboardButton(
                "🌐 Federation",
                callback_data="rose_fed",
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="panel_back",
            )
        ],

    ])


async def rose_menu(
    query,
):

    await query.message.edit_text(
        "🌹 <b>ROSE COMMANDS</b>\n\n"
        "Select a category:",
        reply_markup=rose_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# ROSE CALLBACK
# ============================================================

async def rose_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    if query.from_user.id != OWNER_ID:

        await query.answer(
            "❌ Owner only.",
            show_alert=True,
        )

        return

    await query.answer()

    data = query.data

    if data == "rose_menu":

        await rose_menu(query)
        return

    if data == "rose_moderation":

        text = (
            "🛡 <b>MODERATION COMMANDS</b>\n\n"
            "/warn\n"
            "/unwarn\n"
            "/ban\n"
            "/unban USER_ID\n"
            "/mute\n"
            "/unmute\n"
            "/purge NUMBER"
        )

    elif data == "rose_locks":

        text = (
            "🔒 <b>LOCK COMMANDS</b>\n\n"
            "/lock messages\n"
            "/unlock messages\n\n"
            "You can extend lock types later."
        )

    elif data == "rose_welcome":

        text = (
            "👋 <b>WELCOME COMMANDS</b>\n\n"
            "/welcome on\n"
            "/welcome off\n"
            "/goodbye on\n"
            "/goodbye off"
        )

    elif data == "rose_rules":

        text = (
            "📜 <b>RULE COMMANDS</b>\n\n"
            "/rules\n"
            "/setrules Your rules here"
        )

    elif data == "rose_fed":

        text = (
            "🌐 <b>FEDERATION COMMANDS</b>\n\n"
            "/newfed\n"
            "/fedban\n"
            "/fedunban\n"
            "/fedmute\n"
            "/fedunmute"
        )

    else:
        return

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Rose Menu",
                    callback_data="rose_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Panel",
                    callback_data="panel_back",
                )
            ],
        ]),
        parse_mode="HTML",
    )


# ============================================================
# PANEL CALLBACK
# ============================================================

async def panel_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    if query.from_user.id != OWNER_ID:

        await query.answer(
            "❌ Owner only.",
            show_alert=True,
        )

        return

    await query.answer()

    data = query.data

    # --------------------------------------------------------
    # STATISTICS
    # --------------------------------------------------------

    if data == "panel_stats":

        text = (
            "📊 <b>BOT STATISTICS</b>\n\n"
            f"👥 Total Users: "
            f"<b>{database.get_user_count()}</b>\n\n"
            f"🔐 Verified: "
            f"<b>{database.get_verified_count()}</b>\n"
            f"⏳ Pending: "
            f"<b>{database.get_pending_count()}</b>\n"
            f"✅ Approved: "
            f"<b>{database.get_approved_count()}</b>\n"
            f"❌ Rejected: "
            f"<b>{database.get_rejected_count()}</b>\n"
            f"🚫 Revoked: "
            f"<b>{database.get_revoked_count()}</b>"
        )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="panel_back",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    if data == "panel_users":

        text = (
            "👥 <b>USER MANAGEMENT</b>\n\n"
            f"Total: {database.get_user_count()}\n"
            f"⏳ Pending: {database.get_pending_count()}\n"
            f"✅ Approved: {database.get_approved_count()}\n"
            f"❌ Rejected: {database.get_rejected_count()}\n"
            f"🚫 Revoked: {database.get_revoked_count()}\n\n"
            "Commands:\n"
            "/approve @username\n"
            "/reject @username\n"
            "/revoke @username\n"
            "/reapprove @username"
        )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="panel_back",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # CHANNELS
    # --------------------------------------------------------

    if data == "panel_channels":

        text = (
            "📢 <b>FORCE JOIN CHANNELS</b>\n\n"
            f"1️⃣ <code>-1003998560024</code>\n"
            f"2️⃣ <code>-1004077604887</code>\n\n"
            "Both channels are required."
        )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="panel_back",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # GROUP
    # --------------------------------------------------------

    if data == "panel_group":

        text = (
            "⚙️ <b>GROUP MANAGEMENT</b>\n\n"
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

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="panel_back",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # FEDERATION
    # --------------------------------------------------------

    if data == "panel_fed":

        text = (
            "🌐 <b>FEDERATION</b>\n\n"
            "/newfed\n"
            "/fedban\n"
            "/fedunban\n"
            "/fedmute\n"
            "/fedunmute"
        )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="panel_back",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # HELP
    # --------------------------------------------------------

    if data == "panel_help":

        text = (
            "📖 <b>COMMAND HELP</b>\n\n"
            "Use /help to see all available commands."
        )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="panel_back",
                    )
                ]
            ]),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # ROSE
    # --------------------------------------------------------

    if data == "rose_menu":

        await rose_menu(query)
        return

    # --------------------------------------------------------
    # PANEL BACK
    # --------------------------------------------------------

    if data == "panel_back":

        await query.message.edit_text(
            "👑 <b>OWNER CONTROL PANEL</b>\n\n"
            "🛡️ JoinGuard Bot\n\n"
            "Select an option below:",
            reply_markup=panel_keyboard(),
            parse_mode="HTML",
        )


# ============================================================
# ID
# ============================================================

async def id_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user:
        return

    await update.effective_message.reply_text(
        f"🆔 <b>Your User ID:</b> "
        f"<code>{user.id}</code>",
        parse_mode="HTML",
    )


# ============================================================
# INFO
# ============================================================

async def info_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user:
        return

    username = (
        f"@{user.username}"
        if user.username
        else "No username"
    )

    text = (
        "👤 <b>USER INFORMATION</b>\n\n"
        f"📝 Name: {user.first_name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: <code>{user.id}</code>"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# RULES
# ============================================================

async def rules_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat = update.effective_chat

    if not chat:
        return

    settings = database.get_group_settings(
        chat.id
    )

    rules = settings[4]

    await update.effective_message.reply_text(
        f"<b>📜 GROUP RULES</b>\n\n{rules}",
        parse_mode="HTML",
    )


# ============================================================
# WELCOME
# ============================================================

async def welcome_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    chat_id = update.effective_chat.id

    if not context.args:

        settings = database.get_group_settings(
            chat_id
        )

        enabled = bool(settings[0])

        await update.effective_message.reply_text(
            f"👋 Welcome system: "
            f"<b>{'ON' if enabled else 'OFF'}</b>",
            parse_mode="HTML",
        )

        return

    option = context.args[0].lower()

    if option == "on":

        database.set_welcome(
            chat_id,
            True,
        )

        await update.effective_message.reply_text(
            "✅ Welcome messages enabled."
        )

    elif option == "off":

        database.set_welcome(
            chat_id,
            False,
        )

        await update.effective_message.reply_text(
            "❌ Welcome messages disabled."
        )


# ============================================================
# GOODBYE
# ============================================================

async def goodbye_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    chat_id = update.effective_chat.id

    if not context.args:

        settings = database.get_group_settings(
            chat_id
        )

        enabled = bool(settings[2])

        await update.effective_message.reply_text(
            f"👋 Goodbye system: "
            f"<b>{'ON' if enabled else 'OFF'}</b>",
            parse_mode="HTML",
        )

        return

    option = context.args[0].lower()

    if option == "on":

        database.set_goodbye(
            chat_id,
            True,
        )

        await update.effective_message.reply_text(
            "✅ Goodbye messages enabled."
        )

    elif option == "off":

        database.set_goodbye(
            chat_id,
            False,
        )

        await update.effective_message.reply_text(
            "❌ Goodbye messages disabled."
        )


# ============================================================
# NEW MEMBER
# ============================================================

async def new_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.chat_member:
        return

    result = update.chat_member

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status

    if new_status not in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    ):
        return

    if old_status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    ):
        return

    user = result.new_chat_member.user
    chat = update.effective_chat

    database.ensure_group(
        chat.id
    )

    settings = database.get_group_settings(
        chat.id
    )

    if not bool(settings[0]):
        return

    text = settings[1].format(
        mention=mention_user(user),
        name=user.first_name or "User",
        username=(
            f"@{user.username}"
            if user.username
            else ""
        ),
        id=user.id,
        chatname=chat.title or "",
    )

    await context.bot.send_message(
        chat_id=chat.id,
        text=text,
        parse_mode="HTML",
    )


# ============================================================
# TARGET USER
# ============================================================

async def get_target_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if (
        update.message
        and update.message.reply_to_message
    ):

        return update.message.reply_to_message.from_user

    if context.args:

        try:

            user_id = int(
                context.args[0]
            )

            member = await context.bot.get_chat_member(
                update.effective_chat.id,
                user_id,
            )

            return member.user

        except Exception:

            return None

    return None


# ============================================================
# WARN
# ============================================================

async def warn_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
            "Reply to a user or use:\n"
            "/warn USER_ID"
        )

        return

    count = database.add_warn(
        update.effective_chat.id,
        target.id,
    )

    settings = database.get_group_settings(
        update.effective_chat.id
    )

    limit = settings[5]

    if count >= limit:

        try:

            await context.bot.ban_chat_member(
                update.effective_chat.id,
                target.id,
            )

            database.reset_warns(
                update.effective_chat.id,
                target.id,
            )

            await update.effective_message.reply_text(
                f"🔨 {mention_user(target)} "
                f"was banned after {limit} warnings.",
                parse_mode="HTML",
            )

        except Exception as e:

            await update.effective_message.reply_text(
                f"❌ Could not ban user.\n\n"
                f"<code>{e}</code>",
                parse_mode="HTML",
            )

        return

    await update.effective_message.reply_text(
        f"⚠️ {mention_user(target)} received a warning.\n\n"
        f"Warnings: <b>{count}/{limit}</b>",
        parse_mode="HTML",
    )


# ============================================================
# UNWARN
# ============================================================

async def unwarn_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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

    database.reset_warns(
        update.effective_chat.id,
        target.id,
    )

    await update.effective_message.reply_text(
        f"✅ Warnings reset for "
        f"{mention_user(target)}.",
        parse_mode="HTML",
    )


# ============================================================
# BAN
# ============================================================

async def ban_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
            f"🔨 {mention_user(target)} has been banned.",
            parse_mode="HTML",
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ Ban failed.\n\n"
            f"<code>{e}</code>",
            parse_mode="HTML",
        )


# ============================================================
# UNBAN
# ============================================================

async def unban_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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

        user_id = int(
            context.args[0]
        )

        await context.bot.unban_chat_member(
            update.effective_chat.id,
            user_id,
        )

        await update.effective_message.reply_text(
            f"✅ User <code>{user_id}</code> unbanned.",
            parse_mode="HTML",
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ Unban failed.\n\n"
            f"<code>{e}</code>",
            parse_mode="HTML",
        )


# ============================================================
# MUTE
# ============================================================

async def mute_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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

        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=ChatPermissions(
                can_send_messages=False
            ),
        )

        await update.effective_message.reply_text(
            f"🔇 {mention_user(target)} "
            "has been muted.",
            parse_mode="HTML",
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ Mute failed.\n\n"
            f"<code>{e}</code>",
            parse_mode="HTML",
        )


# ============================================================
# UNMUTE
# ============================================================

async def unmute_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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

        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=ChatPermissions(
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
            ),
        )

        await update.effective_message.reply_text(
            f"🔊 {mention_user(target)} "
            "has been unmuted.",
            parse_mode="HTML",
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ Unmute failed.\n\n"
            f"<code>{e}</code>",
            parse_mode="HTML",
        )


# ============================================================
# PURGE
# ============================================================

async def purge_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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

        amount = int(
            context.args[0]
        )

        if amount < 1 or amount > 100:

            await update.effective_message.reply_text(
                "Enter a number between 1 and 100."
            )

            return

        if not update.message:
            return

        message_id = update.message.message_id

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

        msg = await context.bot.send_message(
            update.effective_chat.id,
            f"🧹 Deleted {deleted} messages.",
        )

        if context.job_queue:

            context.job_queue.run_once(
                delete_message_job,
                5,
                data=(
                    update.effective_chat.id,
                    msg.message_id,
                ),
            )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ Purge failed.\n\n"
            f"<code>{e}</code>",
            parse_mode="HTML",
        )


async def delete_message_job(
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id, message_id = context.job.data

    try:

        await context.bot.delete_message(
            chat_id,
            message_id,
        )

    except Exception:
        pass


# ============================================================
# LOCK
# ============================================================

async def lock_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    lock_type = (
        context.args[0].lower()
        if context.args
        else "messages"
    )

    database.set_lock(
        update.effective_chat.id,
        lock_type,
        True,
    )

    await update.effective_message.reply_text(
        f"🔒 <b>{lock_type}</b> lock enabled.",
        parse_mode="HTML",
    )


# ============================================================
# UNLOCK
# ============================================================

async def unlock_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await is_admin(update):

        await update.effective_message.reply_text(
            "❌ Admins only."
        )

        return

    lock_type = (
        context.args[0].lower()
        if context.args
        else "messages"
    )

    database.set_lock(
        update.effective_chat.id,
        lock_type,
        False,
    )

    await update.effective_message.reply_text(
        f"🔓 <b>{lock_type}</b> lock disabled.",
        parse_mode="HTML",
    )


# ============================================================
# SET RULES
# ============================================================

async def setrules_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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

    rules = " ".join(
        context.args
    )

    database.set_rules(
        update.effective_chat.id,
        rules,
    )

    await update.effective_message.reply_text(
        "✅ Group rules updated."
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("🚀 Starting Force Join Bot...")
    print("✅ Initializing database...")

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
    # OWNER
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "panel",
            panel,
        )
    )

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
            "revoke",
            revoke_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "reapprove",
            reapprove_command,
        )
    )

    # --------------------------------------------------------
    # GROUP
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
    # FORCE JOIN CALLBACK
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            verify_join,
            pattern=r"^verify_join$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            request_approval,
            pattern=r"^request_approval$",
        )
    )

    # --------------------------------------------------------
    # APPROVAL CALLBACKS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            approval_callback,
            pattern=r"^(approve|reject|revoke|reapprove):\d+$",
        )
    )

    # --------------------------------------------------------
    # ROSE CALLBACKS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            rose_callback,
            pattern=r"^rose_",
        )
    )

    # --------------------------------------------------------
    # PANEL CALLBACKS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            panel_callback,
            pattern=r"^panel_",
        )
    )

    # --------------------------------------------------------
    # NEW MEMBERS
    # --------------------------------------------------------

    application.add_handler(
        ChatMemberHandler(
            new_member,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    print("✅ Bot is running...")
    print("🔐 Force Join: ENABLED")
    print("👑 Approval System: ENABLED")
    print("🌹 Rose Menu: ENABLED")

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
