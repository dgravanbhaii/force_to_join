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

from config import BOT_TOKEN, OWNER_ID
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
# DATABASE
# ============================================================

database.init_db()


# ============================================================
# OWNER CHECK
# ============================================================

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


# ============================================================
# CHECK USER MEMBERSHIP
# ============================================================

async def check_membership(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
):
    channels = database.get_channels()

    not_joined = []

    for chat_id, title, invite_link in channels:

        try:
            member = await context.bot.get_chat_member(
                chat_id=chat_id,
                user_id=user_id,
            )

            if member.status in (
                ChatMemberStatus.LEFT,
                ChatMemberStatus.KICKED,
            ):
                not_joined.append(
                    (chat_id, title, invite_link)
                )

        except Exception as error:

            logger.error(
                f"Membership check failed for "
                f"{chat_id}: {error}"
            )

            not_joined.append(
                (chat_id, title, invite_link)
            )

    return not_joined


# ============================================================
# FORCE JOIN KEYBOARD
# ============================================================

def force_join_keyboard(channels):

    keyboard = []

    for _, title, invite_link in channels:

        keyboard.append([
            InlineKeyboardButton(
                f"📢 Join {title}",
                url=invite_link,
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "✅ I've Joined",
            callback_data="verify_join",
        )
    ])

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SEND FORCE JOIN MESSAGE
# ============================================================

async def send_force_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    channels = database.get_channels()

    keyboard = force_join_keyboard(channels)

    text = (
        "🔐 <b>Join Required</b>\n\n"
        "To use <b>JoinGuard Bot</b>, you must "
        "join all the required channels below.\n\n"
        "📢 Join every channel and then press "
        "<b>I've Joined</b>.\n\n"
        "⚡ Your access will be unlocked automatically "
        "after successful verification."
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    elif update.message:

        await update.message.reply_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )


# ============================================================
# START COMMAND
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    database.add_user(
        user.id,
        user.first_name or "",
        user.username or "",
    )

    channels = database.get_channels()

    # --------------------------------------------------------
    # No force join channels configured
    # --------------------------------------------------------

    if not channels:

        database.set_verified(
            user.id,
            True,
        )

        await update.message.reply_text(
            f"👋 <b>Welcome {user.first_name}!</b>\n\n"
            "🤖 Welcome to <b>JoinGuard Bot</b>.\n\n"
            "⚠️ No force-join channels are currently "
            "configured.",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Check membership
    # --------------------------------------------------------

    not_joined = await check_membership(
        context,
        user.id,
    )

    if not_joined:

        database.set_verified(
            user.id,
            False,
        )

        await send_force_join(
            update,
            context,
        )

        return

    # --------------------------------------------------------
    # Verified
    # --------------------------------------------------------

    database.set_verified(
        user.id,
        True,
    )

    await update.message.reply_text(
        f"👋 <b>Welcome {user.first_name}!</b>\n\n"
        "✅ Channel verification successful.\n\n"
        "🔓 <b>Your access has been unlocked.</b>\n\n"
        "🚀 You can now use the bot.",
        parse_mode="HTML",
    )


# ============================================================
# VERIFY JOIN BUTTON
# ============================================================

async def verify_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    user = query.from_user

    await query.answer(
        "🔍 Checking your membership..."
    )

    not_joined = await check_membership(
        context,
        user.id,
    )

    # --------------------------------------------------------
    # Still not joined
    # --------------------------------------------------------

    if not_joined:

        database.set_verified(
            user.id,
            False,
        )

        keyboard = force_join_keyboard(
            not_joined
        )

        names = "\n".join(
            f"• {title}"
            for _, title, _ in not_joined
        )

        text = (
            "❌ <b>Verification Failed</b>\n\n"
            "You haven't joined all required channels.\n\n"
            f"{names}\n\n"
            "📢 Join the remaining channel(s) "
            "and press <b>Check Again</b>."
        )

        # Change button text for retry
        keyboard.inline_keyboard[-1][0] = (
            InlineKeyboardButton(
                "🔄 Check Again",
                callback_data="verify_join",
            )
        )

        await query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Successfully verified
    # --------------------------------------------------------

    database.set_verified(
        user.id,
        True,
    )

    await query.edit_message_text(
        text=(
            "🎉 <b>Verification Successful!</b>\n\n"
            "✅ You have joined all required channels.\n\n"
            "🔓 <b>Access Unlocked</b>\n\n"
            "🚀 You can now use <b>JoinGuard Bot</b>."
        ),
        parse_mode="HTML",
    )


# ============================================================
# ADD CHANNEL
# ============================================================

async def add_channel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id):

        await update.message.reply_text(
            "❌ <b>Access Denied</b>\n\n"
            "Only the bot owner can use this command.",
            parse_mode="HTML",
        )

        return

    if not context.args:

        await update.message.reply_text(
            "📢 <b>Add Force-Join Channel</b>\n\n"
            "Usage:\n"
            "<code>/addchannel CHAT_ID | TITLE | INVITE_LINK</code>\n\n"
            "Example:\n"
            "<code>/addchannel -1001234567890 | My Channel | "
            "https://t.me/mychannel</code>\n\n"
            "⚠️ Make sure the bot is an administrator "
            "in the channel.",
            parse_mode="HTML",
        )

        return

    data = " ".join(context.args)

    parts = [
        part.strip()
        for part in data.split("|")
    ]

    if len(parts) != 3:

        await update.message.reply_text(
            "❌ <b>Invalid Format</b>\n\n"
            "Use:\n"
            "<code>/addchannel CHAT_ID | TITLE | INVITE_LINK</code>",
            parse_mode="HTML",
        )

        return

    chat_id, title, invite_link = parts

    try:

        chat = await context.bot.get_chat(
            chat_id
        )

        database.add_channel(
            str(chat.id),
            title,
            invite_link,
        )

        await update.message.reply_text(
            "✅ <b>Channel Added Successfully</b>\n\n"
            f"📢 <b>Title:</b> {title}\n"
            f"🆔 <b>Chat ID:</b> <code>{chat.id}</code>\n"
            f"🔗 <b>Invite:</b> {invite_link}\n\n"
            "🔒 Force join is now active for this channel.",
            parse_mode="HTML",
        )

    except Exception as error:

        logger.error(
            f"Failed to add channel: {error}"
        )

        await update.message.reply_text(
            "❌ <b>Failed to Add Channel</b>\n\n"
            f"<code>{error}</code>\n\n"
            "Make sure:\n"
            "• The Chat ID is correct\n"
            "• The bot is an administrator\n"
            "• The channel exists",
            parse_mode="HTML",
        )


# ============================================================
# REMOVE CHANNEL
# ============================================================

async def remove_channel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id):

        await update.message.reply_text(
            "❌ <b>Access Denied</b>",
            parse_mode="HTML",
        )

        return

    if not context.args:

        await update.message.reply_text(
            "📢 <b>Remove Channel</b>\n\n"
            "Usage:\n"
            "<code>/removechannel CHAT_ID</code>\n\n"
            "Example:\n"
            "<code>/removechannel -1001234567890</code>",
            parse_mode="HTML",
        )

        return

    chat_id = context.args[0]

    database.remove_channel(
        chat_id
    )

    await update.message.reply_text(
        "✅ <b>Channel Removed</b>\n\n"
        f"🆔 Chat ID: <code>{chat_id}</code>\n\n"
        "🔓 Force-join requirement has been removed.",
        parse_mode="HTML",
    )


# ============================================================
# LIST CHANNELS
# ============================================================

async def channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id):

        await update.message.reply_text(
            "❌ <b>Access Denied</b>",
            parse_mode="HTML",
        )

        return

    channel_list = database.get_channels()

    if not channel_list:

        await update.message.reply_text(
            "📢 <b>No Force-Join Channels</b>\n\n"
            "There are currently no channels configured.",
            parse_mode="HTML",
        )

        return

    text = (
        "📢 <b>Force-Join Channels</b>\n\n"
    )

    for index, (_, title, invite_link) in enumerate(
        channel_list,
        start=1,
    ):

        text += (
            f"<b>{index}. {title}</b>\n"
            f"🔗 {invite_link}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# STATISTICS
# ============================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id):

        await update.message.reply_text(
            "❌ <b>Access Denied</b>",
            parse_mode="HTML",
        )

        return

    users = database.get_user_count()

    verified = database.get_verified_count()

    channels_count = len(
        database.get_channels()
    )

    await update.message.reply_text(
        "📊 <b>JoinGuard Statistics</b>\n\n"
        f"👥 Total Users: <b>{users}</b>\n"
        f"✅ Verified Users: <b>{verified}</b>\n"
        f"🔒 Force-Join Channels: <b>{channels_count}</b>\n\n"
        "🛡️ <b>JoinGuard Bot</b>",
        parse_mode="HTML",
    )


# ============================================================
# HELP COMMAND
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if is_owner(user.id):

        text = (
            "🛡️ <b>JoinGuard Owner Panel</b>\n\n"
            "📢 <b>Channel Management</b>\n\n"
            "/addchannel - Add force-join channel\n"
            "/removechannel - Remove channel\n"
            "/channels - List channels\n\n"
            "📊 <b>Statistics</b>\n\n"
            "/stats - View bot statistics\n\n"
            "👤 <b>User</b>\n\n"
            "/start - Start the bot\n"
            "/help - Show this menu"
        )

    else:

        text = (
            "🛡️ <b>JoinGuard Bot</b>\n\n"
            "/start - Start the bot\n"
            "/help - Show help"
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
            "addchannel",
            add_channel_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "removechannel",
            remove_channel_command,
        )
    )

    # --------------------------------------------------------
    # Callback buttons
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            verify_join,
            pattern=r"^verify_join$",
        )
    )

    # --------------------------------------------------------
    # Error handler
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    print("✅ Bot is running...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
