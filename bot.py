import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import (
    BOT_TOKEN,
    OWNER_ID,
    FORCE_JOIN_CHANNELS,
)

import database


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# BOT SETTINGS
# ============================================================

BOT_NAME = "JoinGuard Bot"


# ============================================================
# DATABASE
# ============================================================

database.init_db()


# ============================================================
# OWNER CHECK
# ============================================================

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


# ============================================================
# MEMBERSHIP CHECK
# ============================================================

async def is_user_joined(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id,
    user_id: int,
) -> bool:

    try:
        member = await context.bot.get_chat_member(
            chat_id=chat_id,
            user_id=user_id,
        )

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            ChatMemberStatus.RESTRICTED,
        )

    except Exception as exc:
        logger.error(
            "Membership check failed for %s: %s",
            chat_id,
            exc,
        )

        return False


# ============================================================
# CHECK ALL FORCE JOIN CHANNELS
# ============================================================

async def check_all_channels(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> bool:

    for channel_id in FORCE_JOIN_CHANNELS:

        joined = await is_user_joined(
            context,
            channel_id,
            user_id,
        )

        if not joined:
            return False

    return True


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

    # --------------------------------------------------------
    # OWNER
    # --------------------------------------------------------

    if is_owner(user.id):

        await update.message.reply_text(
            f"👑 <b>Welcome, Owner!</b>\n\n"
            f"🛡️ <b>{BOT_NAME}</b>\n\n"
            "Use /panel to open the owner panel.",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # CHECK APPROVAL
    # --------------------------------------------------------

    approval = database.get_approval_status(
        user.id
    )

    # Rejected / revoked
    if approval == -1:

        await update.message.reply_text(
            "🚫 <b>Access Revoked</b>\n\n"
            "Your access to this bot has been revoked "
            "by the owner.\n\n"
            "You cannot use the bot at this time.",
            parse_mode="HTML",
        )

        return

    # Not approved yet
    if approval != 1:

        keyboard = [
            [
                InlineKeyboardButton(
                    "📩 Request Access",
                    callback_data="request_again",
                )
            ]
        ]

        await update.message.reply_text(
            "🔐 <b>Access Required</b>\n\n"
            "You need owner approval before using "
            "this bot.\n\n"
            "Click the button below to request access.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # CHECK FORCE JOIN
    # --------------------------------------------------------

    joined = await check_all_channels(
        context,
        user.id,
    )

    if not joined:

        keyboard = []

        for index, channel_id in enumerate(
            FORCE_JOIN_CHANNELS,
            start=1,
        ):

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📢 Join Channel {index}",
                        callback_data=f"no_link_{index}",
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "✅ I've Joined — Verify",
                    callback_data="verify_join",
                )
            ]
        )

        await update.message.reply_text(
            "🔒 <b>Force Join Required</b>\n\n"
            "Please join all required channels "
            "below and then click "
            "<b>I've Joined — Verify</b>.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # ACCESS GRANTED
    # --------------------------------------------------------

    database.set_verified(
        user.id,
        True,
    )

    await update.message.reply_text(
        f"🎉 <b>Welcome to {BOT_NAME}</b>\n\n"
        "✅ Access approved\n"
        "✅ All required channels joined\n\n"
        "🚀 You can now use the bot.",
        parse_mode="HTML",
    )


# ============================================================
# REQUEST ACCESS
# ============================================================

async def request_again(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    database.add_user(
        user.id,
        user.first_name or "",
        user.username or "",
    )

    database.set_approval(
        user.id,
        0,
    )

    await query.edit_message_text(
        "📩 <b>Access Request Sent</b>\n\n"
        "Your request has been sent to the owner.\n\n"
        "⏳ Please wait for approval.",
        parse_mode="HTML",
    )

    # --------------------------------------------------------
    # Notify owner
    # --------------------------------------------------------

    try:

        username = (
            f"@{user.username}"
            if user.username
            else "No username"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"approve:{user.id}",
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=f"reject:{user.id}",
                ),
            ]
        ]

        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(
                "📩 <b>New Access Request</b>\n\n"
                f"👤 Name: {user.first_name}\n"
                f"🔗 Username: {username}\n"
                f"🆔 User ID: <code>{user.id}</code>"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    except Exception as exc:

        logger.error(
            "Failed to notify owner: %s",
            exc,
        )


# ============================================================
# VERIFY JOIN
# ============================================================

async def verify_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    # --------------------------------------------------------
    # Approval check
    # --------------------------------------------------------

    if not database.is_approved(user.id):

        await query.answer(
            "❌ You are not approved yet.",
            show_alert=True,
        )

        return

    # --------------------------------------------------------
    # Membership check
    # --------------------------------------------------------

    joined = await check_all_channels(
        context,
        user.id,
    )

    if not joined:

        await query.answer(
            "❌ You haven't joined all required channels.",
            show_alert=True,
        )

        return

    # --------------------------------------------------------
    # Verified
    # --------------------------------------------------------

    database.set_verified(
        user.id,
        True,
    )

    await query.edit_message_text(
        "✅ <b>Verification Successful!</b>\n\n"
        "You have joined all required channels.\n\n"
        "🎉 <b>Access Granted</b>",
        parse_mode="HTML",
    )


# ============================================================
# APPROVAL CALLBACK
# ============================================================

async def process_approval(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not is_owner(query.from_user.id):

        await query.answer(
            "❌ Owner only!",
            show_alert=True,
        )

        return

    action, user_id_text = query.data.split(":")

    user_id = int(user_id_text)

    # --------------------------------------------------------
    # APPROVE
    # --------------------------------------------------------

    if action == "approve":

        database.set_approval(
            user_id,
            1,
        )

        await query.answer(
            "✅ User approved!",
            show_alert=True,
        )

        await query.edit_message_text(
            f"✅ <b>User Approved</b>\n\n"
            f"🆔 User ID: <code>{user_id}</code>",
            parse_mode="HTML",
        )

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 <b>Access Approved!</b>\n\n"
                    "The owner has approved your access.\n\n"
                    "Now join all required channels "
                    "and use /start."
                ),
                parse_mode="HTML",
            )

        except Exception as exc:

            logger.warning(
                "Could not notify user: %s",
                exc,
            )

        return

    # --------------------------------------------------------
    # REJECT
    # --------------------------------------------------------

    if action == "reject":

        database.set_approval(
            user_id,
            -1,
        )

        await query.answer(
            "❌ User rejected!",
            show_alert=True,
        )

        await query.edit_message_text(
            f"❌ <b>User Rejected</b>\n\n"
            f"🆔 User ID: <code>{user_id}</code>",
            parse_mode="HTML",
        )

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ <b>Access Request Rejected</b>\n\n"
                    "Your request to use the bot "
                    "has been rejected by the owner."
                ),
                parse_mode="HTML",
            )

        except Exception as exc:

            logger.warning(
                "Could not notify user: %s",
                exc,
            )


# ============================================================
# REVOKE USER
# ============================================================

async def revoke_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id):

        await update.message.reply_text(
            "❌ <b>Access Denied</b>\n\n"
            "Only the bot owner can revoke access.",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Check argument
    # --------------------------------------------------------

    if not context.args:

        await update.message.reply_text(
            "🚫 <b>Revoke Access</b>\n\n"
            "Usage:\n"
            "<code>/revoke USER_ID</code>\n\n"
            "Example:\n"
            "<code>/revoke 8420696977</code>",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Validate ID
    # --------------------------------------------------------

    try:

        target_user_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Invalid User ID.\n\n"
            "User ID must contain numbers only.",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Protect owner
    # --------------------------------------------------------

    if target_user_id == OWNER_ID:

        await update.message.reply_text(
            "⚠️ You cannot revoke the bot owner's access.",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Make sure user exists
    # --------------------------------------------------------

    database.add_user(
        target_user_id,
        "",
        "",
    )

    # --------------------------------------------------------
    # Revoke
    # --------------------------------------------------------

    database.set_approval(
        target_user_id,
        -1,
    )

    database.set_verified(
        target_user_id,
        False,
    )

    # --------------------------------------------------------
    # Owner response
    # --------------------------------------------------------

    await update.message.reply_text(
        "🚫 <b>Access Revoked</b>\n\n"
        f"👤 User ID: <code>{target_user_id}</code>\n"
        "📌 Status: <b>Revoked</b>\n"
        "🔒 Bot access: <b>Disabled</b>",
        parse_mode="HTML",
    )

    # --------------------------------------------------------
    # Notify user
    # --------------------------------------------------------

    try:

        await context.bot.send_message(
            chat_id=target_user_id,
            text=(
                "🚫 <b>Access Revoked</b>\n\n"
                "Your access to <b>JoinGuard Bot</b> "
                "has been revoked by the owner.\n\n"
                "🔒 You can no longer use the bot."
            ),
            parse_mode="HTML",
        )

    except Exception as exc:

        logger.warning(
            "Could not notify revoked user %s: %s",
            target_user_id,
            exc,
        )


# ============================================================
# REQUESTS
# ============================================================

async def requests(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id):

        await update.message.reply_text(
            "❌ Owner only!",
        )

        return

    pending = database.get_pending_users()

    if not pending:

        await update.message.reply_text(
            "📭 <b>No Pending Requests</b>\n\n"
            "There are currently no pending users.",
            parse_mode="HTML",
        )

        return

    await update.message.reply_text(
        f"📩 <b>Pending Requests</b>\n\n"
        f"👥 Pending: <b>{len(pending)}</b>",
        parse_mode="HTML",
    )

    for user_id, first_name, username in pending:

        username_text = (
            f"@{username}"
            if username
            else "No username"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"approve:{user_id}",
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=f"reject:{user_id}",
                ),
            ]
        ]

        await update.message.reply_text(
            "👤 <b>User Request</b>\n\n"
            f"Name: {first_name or 'Unknown'}\n"
            f"Username: {username_text}\n"
            f"ID: <code>{user_id}</code>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )


# ============================================================
# STATS
# ============================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id):

        await update.message.reply_text(
            "❌ Owner only!",
        )

        return

    users = database.get_user_count()
    verified = database.get_verified_count()
    approved = database.get_approved_count()
    pending = database.get_pending_count()
    channels = len(
        database.get_channels()
    )

    await update.message.reply_text(
        f"📊 <b>{BOT_NAME} Statistics</b>\n\n"
        f"👥 Users: <b>{users}</b>\n"
        f"✅ Approved: <b>{approved}</b>\n"
        f"⏳ Pending: <b>{pending}</b>\n"
        f"🔐 Verified: <b>{verified}</b>\n"
        f"📢 Channels: <b>{channels}</b>",
        parse_mode="HTML",
    )


# ============================================================
# CHANNELS
# ============================================================

async def channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id):

        await update.message.reply_text(
            "❌ Owner only!",
        )

        return

    if not FORCE_JOIN_CHANNELS:

        await update.message.reply_text(
            "📭 No force-join channels configured.",
        )

        return

    text = (
        "📢 <b>Force Join Channels</b>\n\n"
    )

    for index, channel_id in enumerate(
        FORCE_JOIN_CHANNELS,
        start=1,
    ):

        text += (
            f"{index}. "
            f"<code>{channel_id}</code>\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# PANEL
# ============================================================

async def panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id):

        await update.message.reply_text(
            "❌ Owner only!",
        )

        return

    keyboard = [
        [
            InlineKeyboardButton(
                "📩 Requests",
                callback_data="panel_requests",
            ),
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="panel_stats",
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 Channels",
                callback_data="panel_channels",
            ),
        ],
    ]

    await update.message.reply_text(
        f"🛡️ <b>{BOT_NAME}</b>\n\n"
        "👑 <b>Owner Control Panel</b>\n\n"
        "Choose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


# ============================================================
# NO LINK CALLBACK
# ============================================================

async def no_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer(
        "Please use the channel link provided by the bot.",
        show_alert=True,
    )


# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if is_owner(user.id):

        text = (
            f"🛡️ <b>{BOT_NAME}</b>\n\n"
            "👑 <b>Owner Commands</b>\n\n"
            "/panel — Owner Panel\n"
            "/requests — Pending approvals\n"
            "/stats — Statistics\n"
            "/channels — Force-join channels\n"
            "/revoke USER_ID — Revoke access\n"
            "/help — Help\n\n"
            "👤 <b>User</b>\n\n"
            "/start — Start bot"
        )

    else:

        text = (
            f"🛡️ <b>{BOT_NAME}</b>\n\n"
            "/start — Start bot\n"
            "/help — Help"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
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
    print()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Commands
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
            "panel",
            panel,
        )
    )

    application.add_handler(
        CommandHandler(
            "requests",
            requests,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats,
        )
    )

    application.add_handler(
        CommandHandler(
            "channels",
            channels,
        )
    )

    application.add_handler(
        CommandHandler(
            "revoke",
            revoke_user,
        )
    )

    # --------------------------------------------------------
    # Callbacks
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            verify_join,
            pattern=r"^verify_join$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            request_again,
            pattern=r"^request_again$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            process_approval,
            pattern=r"^(approve|reject):\d+$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            no_link,
            pattern=r"^no_link_\d+$",
        )
    )

    # --------------------------------------------------------
    # Error handler
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    print("✅ Bot is running...")
    print()

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
