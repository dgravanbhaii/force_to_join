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


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

database.init_db()


# --------------------------------------------------
# FORCE JOIN CHECK
# --------------------------------------------------

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
            print(
                f"Membership check failed for "
                f"{chat_id}: {error}"
            )

            # If Telegram cannot verify the channel,
            # keep it locked for safety.
            not_joined.append(
                (chat_id, title, invite_link)
            )

    return not_joined


# --------------------------------------------------
# FORCE JOIN MESSAGE
# --------------------------------------------------

async def send_force_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if query:
        user = query.from_user
    else:
        user = update.effective_user

    channels = database.get_channels()

    keyboard = []

    for chat_id, title, invite_link in channels:
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

    text = (
        "🔒 <b>Access Locked</b>\n\n"
        "To use this bot, you must join "
        "<b>all required channels</b> first.\n\n"
        "After joining, click "
        "<b>I've Joined</b> below."
    )

    if query:
        await query.edit_message_text(
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


# --------------------------------------------------
# START
# --------------------------------------------------

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

    not_joined = await check_membership(
        context,
        user.id,
    )

    if not_joined:
        await send_force_join(
            update,
            context,
        )
        return

    database.set_verified(user.id, True)

    await update.message.reply_text(
        f"👋 Welcome <b>{user.first_name}</b>!\n\n"
        "✅ You have joined all required channels.\n\n"
        "🔓 <b>Bot unlocked!</b>",
        parse_mode="HTML",
    )


# --------------------------------------------------
# VERIFY BUTTON
# --------------------------------------------------

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

    if not_joined:
        names = "\n".join(
            f"• {title}"
            for _, title, _ in not_joined
        )

        keyboard = []

        for _, title, invite_link in not_joined:
            keyboard.append([
                InlineKeyboardButton(
                    f"📢 Join {title}",
                    url=invite_link,
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                "🔄 Check Again",
                callback_data="verify_join",
            )
        ])

        await query.edit_message_text(
            text=(
                "❌ <b>Verification Failed</b>\n\n"
                "You still need to join:\n\n"
                f"{names}\n\n"
                "Join the required channel(s) and "
                "press <b>Check Again</b>."
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

        return

    database.set_verified(
        user.id,
        True,
    )

    await query.edit_message_text(
        text=(
            "✅ <b>Verification Successful!</b>\n\n"
            "You have joined all required channels.\n\n"
            "🔓 <b>Access unlocked.</b>\n\n"
            "You can now use the bot."
        ),
        parse_mode="HTML",
    )


# --------------------------------------------------
# ADMIN COMMAND
# --------------------------------------------------

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user

    if user.id != OWNER_ID:
        await update.message.reply_text(
            "❌ You are not authorized."
        )
        return

    users = database.get_user_count()
    verified = database.get_verified_count()
    channels = len(database.get_channels())

    await update.message.reply_text(
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Users: <b>{users}</b>\n"
        f"✅ Verified: <b>{verified}</b>\n"
        f"📢 Force-Join Channels: <b>{channels}</b>",
        parse_mode="HTML",
    )


# --------------------------------------------------
# LIST CHANNELS
# --------------------------------------------------

async def channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user

    if user.id != OWNER_ID:
        await update.message.reply_text(
            "❌ You are not authorized."
        )
        return

    channel_list = database.get_channels()

    if not channel_list:
        await update.message.reply_text(
            "📢 No force-join channels configured."
        )
        return

    text = "📢 <b>Force-Join Channels</b>\n\n"

    for index, (_, title, invite_link) in enumerate(
        channel_list,
        start=1,
    ):
        text += (
            f"{index}. <b>{title}</b>\n"
            f"🔗 {invite_link}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# --------------------------------------------------
# ERROR HANDLER
# --------------------------------------------------

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    print(
        f"Bot error: {context.error}"
    )


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print("🚀 Starting Force Join Bot...")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("stats", stats)
    )

    app.add_handler(
        CommandHandler("channels", channels)
    )

    app.add_handler(
        CallbackQueryHandler(
            verify_join,
            pattern="^verify_join$",
        )
    )

    app.add_error_handler(
        error_handler
    )

    print("✅ Bot is running...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
