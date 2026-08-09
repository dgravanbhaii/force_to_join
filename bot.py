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
# CONFIG
# ============================================================

BOT_NAME = "𝐉𝐨𝐢𝐧𝐆𝐮𝐚𝐫𝐝 𝐁𝐨𝐭"

# Placeholder only.
# This is NOT automatically added to the database.
PLACEHOLDER_CHANNEL = {
    "chat_id": "@PLACEHOLDER_CHANNEL",
    "title": "Placeholder Channel",
    "invite_link": "https://t.me/PLACEHOLDER_CHANNEL",
}


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
# FORCE JOIN CHECK
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
                    (
                        chat_id,
                        title,
                        invite_link,
                    )
                )

        except Exception as error:

            logger.error(
                f"Membership check failed for "
                f"{chat_id}: {error}"
            )

            not_joined.append(
                (
                    chat_id,
                    title,
                    invite_link,
                )
            )

    return not_joined


# ============================================================
# FORCE JOIN KEYBOARD
# ============================================================

def force_join_keyboard(channels):

    keyboard = []

    for _, title, invite_link in channels:

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📢 Join {title}",
                    url=invite_link,
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "✅ I've Joined",
                callback_data="verify_join",
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# FORCE JOIN MESSAGE
# ============================================================

async def send_force_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    channels = database.get_channels()

    if not channels:

        if update.callback_query:

            await update.callback_query.edit_message_text(
                "✅ <b>No force-join channels configured.</b>",
                parse_mode="HTML",
            )

        else:

            await update.message.reply_text(
                "✅ <b>No force-join channels configured.</b>",
                parse_mode="HTML",
            )

        return

    keyboard = force_join_keyboard(channels)

    text = (
        f"🔐 <b>{BOT_NAME}</b>\n\n"
        "Welcome! 👋\n\n"
        "To continue using the bot, you must "
        "join <b>ALL</b> required channels below.\n\n"
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
# START
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
    # No channels
    # --------------------------------------------------------

    if not channels:

        database.set_verified(
            user.id,
            True,
        )

        await update.message.reply_text(
            f"👋 <b>Welcome {user.first_name}!</b>\n\n"
            f"🛡️ <b>{BOT_NAME}</b>\n\n"
            "No force-join channels are currently "
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
        "✅ All required channels verified.\n\n"
        "🔓 <b>Access Unlocked!</b>\n\n"
        f"🚀 You can now use {BOT_NAME}.",
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

    user = query.from_user

    await query.answer(
        "🔍 Checking membership..."
    )

    not_joined = await check_membership(
        context,
        user.id,
    )

    # --------------------------------------------------------
    # Not fully joined
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
            f"<b>Still required:</b>\n"
            f"{names}\n\n"
            "Join the remaining channel(s) and "
            "press <b>Check Again</b>."
        )

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
    # Successfully joined
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
            f"🚀 Welcome to {BOT_NAME}!"
        ),
        parse_mode="HTML",
    )


# ============================================================
# OWNER PANEL
# ============================================================

async def panel(
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

    await send_owner_panel(
        update,
        context,
    )


async def send_owner_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    keyboard = [
        [
            InlineKeyboardButton(
                "➕ Add Channel",
                callback_data="panel_add",
            ),
            InlineKeyboardButton(
                "➖ Remove Channel",
                callback_data="panel_remove",
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 Channel List",
                callback_data="panel_channels",
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="panel_stats",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="panel_refresh",
            ),
        ],
    ]

    text = (
        f"🛡️ <b>{BOT_NAME}</b>\n\n"
        "👑 <b>Owner Control Panel</b>\n\n"
        "Manage your force-join channels and "
        "view bot statistics using the buttons below."
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    else:

        await update.message.reply_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )


# ============================================================
# ADD CHANNEL COMMAND
# ============================================================

async def add_channel_command(
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
            "📢 <b>Add Force-Join Channel</b>\n\n"
            "Usage:\n\n"
            "<code>/addchannel CHAT_ID | TITLE | INVITE_LINK</code>\n\n"
            "Example:\n\n"
            "<code>/addchannel @DevLogzs | DevLogzs | "
            "https://t.me/DevLogzs</code>\n\n"
            "⚠️ The bot must be an administrator "
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
            "✅ <b>Channel Added!</b>\n\n"
            f"📢 <b>{title}</b>\n"
            f"🆔 <code>{chat.id}</code>\n"
            f"🔗 {invite_link}\n\n"
            "🔒 This channel is now required "
            "for all users.",
            parse_mode="HTML",
        )

    except Exception as error:

        logger.error(
            f"Add channel error: {error}"
        )

        await update.message.reply_text(
            "❌ <b>Could Not Add Channel</b>\n\n"
            f"<code>{error}</code>\n\n"
            "Check the channel ID and make sure "
            "the bot is an administrator.",
            parse_mode="HTML",
        )


# ============================================================
# REMOVE CHANNEL COMMAND
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
        f"🆔 <code>{chat_id}</code>\n\n"
        "🔓 Force-join requirement removed.",
        parse_mode="HTML",
    )


# ============================================================
# CHANNEL LIST
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
            "📢 <b>No Channels Configured</b>",
            parse_mode="HTML",
        )

        return

    text = (
        f"📢 <b>{BOT_NAME} Channels</b>\n\n"
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

    channel_count = len(
        database.get_channels()
    )

    await update.message.reply_text(
        f"📊 <b>{BOT_NAME} Statistics</b>\n\n"
        f"👥 Total Users: <b>{users}</b>\n"
        f"✅ Verified Users: <b>{verified}</b>\n"
        f"📢 Required Channels: <b>{channel_count}</b>",
        parse_mode="HTML",
    )


# ============================================================
# PANEL CALLBACKS
# ============================================================

async def panel_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    user = query.from_user

    if not is_owner(user.id):

        await query.answer(
            "❌ Owner only!",
            show_alert=True,
        )

        return

    data = query.data

    await query.answer()

    # --------------------------------------------------------
    # Refresh
    # --------------------------------------------------------

    if data == "panel_refresh":

        await send_owner_panel(
            update,
            context,
        )

        return

    # --------------------------------------------------------
    # Add channel
    # --------------------------------------------------------

    if data == "panel_add":

        await query.edit_message_text(
            "➕ <b>Add Force-Join Channel</b>\n\n"
            "Send this command:\n\n"
            "<code>/addchannel CHAT_ID | TITLE | INVITE_LINK</code>\n\n"
            "Example:\n"
            "<code>/addchannel @DevLogzs | DevLogzs | "
            "https://t.me/DevLogzs</code>\n\n"
            "⚠️ Make sure the bot is an administrator "
            "in the channel.",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Remove channel
    # --------------------------------------------------------

    if data == "panel_remove":

        channel_list = database.get_channels()

        if not channel_list:

            await query.edit_message_text(
                "📢 <b>No Channels</b>\n\n"
                "There are no force-join channels to remove.",
                parse_mode="HTML",
            )

            return

        keyboard = []

        for chat_id, title, _ in channel_list:

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"❌ {title}",
                        callback_data=f"remove:{chat_id}",
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="panel_refresh",
                )
            ]
        )

        await query.edit_message_text(
            "➖ <b>Remove Force-Join Channel</b>\n\n"
            "Select a channel:",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Channel list
    # --------------------------------------------------------

    if data == "panel_channels":

        channel_list = database.get_channels()

        if not channel_list:

            text = (
                "📢 <b>Channel List</b>\n\n"
                "No channels configured."
            )

        else:

            text = (
                f"📢 <b>Channel List</b>\n\n"
            )

            for index, (_, title, invite_link) in enumerate(
                channel_list,
                start=1,
            ):

                text += (
                    f"<b>{index}. {title}</b>\n"
                    f"🔗 {invite_link}\n\n"
                )

        keyboard = [
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="panel_refresh",
                )
            ]
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    if data == "panel_stats":

        users = database.get_user_count()

        verified = database.get_verified_count()

        channel_count = len(
            database.get_channels()
        )

        text = (
            f"📊 <b>{BOT_NAME} Statistics</b>\n\n"
            f"👥 Users: <b>{users}</b>\n"
            f"✅ Verified: <b>{verified}</b>\n"
            f"📢 Channels: <b>{channel_count}</b>"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="panel_refresh",
                )
            ]
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML",
        )

        return


# ============================================================
# REMOVE CHANNEL CALLBACK
# ============================================================

async def remove_channel_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    user = query.from_user

    if not is_owner(user.id):

        await query.answer(
            "❌ Owner only!",
            show_alert=True,
        )

        return

    chat_id = query.data.split(
        "remove:",
        1,
    )[1]

    database.remove_channel(
        chat_id
    )

    await query.answer(
        "✅ Channel removed!",
        show_alert=True,
    )

    await send_owner_panel(
        update,
        context,
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
            "/addchannel — Add channel\n"
            "/removechannel — Remove channel\n"
            "/channels — List channels\n"
            "/stats — Statistics\n\n"
            "👤 <b>User Commands</b>\n\n"
            "/start — Start bot\n"
            "/help — Help"
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

    application.add_handler(
        CommandHandler(
            "channels",
            channels,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats,
        )
    )

    # --------------------------------------------------------
    # Verification callback
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            verify_join,
            pattern=r"^verify_join$",
        )
    )

    # --------------------------------------------------------
    # Owner panel callbacks
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            panel_callback,
            pattern=r"^panel_",
        )
    )

    # --------------------------------------------------------
    # Remove channel callback
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            remove_channel_callback,
            pattern=r"^remove:",
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
# START BOT
# ============================================================

if __name__ == "__main__":
    main()
