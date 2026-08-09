import logging
from typing import List, Tuple

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

from config import BOT_TOKEN, OWNER_ID, FORCE_JOIN_CHANNELS

try:
    from config import FORCE_JOIN_LINKS
except ImportError:
    FORCE_JOIN_LINKS = []

from database import (
    init_db,
    add_user,
    set_verified,
    set_approval,
    get_approval_status,
    get_pending_users,
    get_pending_count,
    get_approved_count,
    get_user_count,
    get_verified_count,
)


# ============================================================
# CONFIG
# ============================================================

BOT_NAME = "𝐉𝐨𝐢𝐧𝐆𝐮𝐚𝐫𝐝 𝐁𝐨𝐭"


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

init_db()


# ============================================================
# HELPERS
# ============================================================

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def normalize_chat_id(chat_id) -> str:
    return str(chat_id).strip()


def get_configured_channels() -> List[str]:
    return [
        normalize_chat_id(channel)
        for channel in FORCE_JOIN_CHANNELS
    ]


def get_configured_link(index: int) -> str:
    if index < len(FORCE_JOIN_LINKS):
        link = FORCE_JOIN_LINKS[index]

        if link:
            return str(link).strip()

    return ""


# ============================================================
# CHANNEL INFORMATION
# ============================================================

async def get_channel_info(
    context: ContextTypes.DEFAULT_TYPE,
    channel_id: str,
    index: int,
) -> Tuple[str, str]:

    try:
        chat = await context.bot.get_chat(channel_id)

        title = (
            chat.title
            or chat.username
            or f"Channel {index + 1}"
        )

        configured_link = get_configured_link(index)

        if configured_link:
            return title, configured_link

        if getattr(chat, "username", None):
            return title, f"https://t.me/{chat.username}"

        if getattr(chat, "invite_link", None):
            return title, chat.invite_link

        return title, ""

    except Exception as error:

        logger.error(
            "Unable to get channel info for %s: %s",
            channel_id,
            error,
        )

        return (
            f"Channel {index + 1}",
            get_configured_link(index),
        )


# ============================================================
# MEMBERSHIP CHECK
# ============================================================

async def check_channel_membership(
    context: ContextTypes.DEFAULT_TYPE,
    channel_id: str,
    user_id: int,
) -> bool:

    try:

        member = await context.bot.get_chat_member(
            chat_id=channel_id,
            user_id=user_id,
        )

        logger.info(
            "Membership check: user=%s channel=%s status=%s",
            user_id,
            channel_id,
            member.status,
        )

        # Normal member
        if member.status == ChatMemberStatus.MEMBER:
            return True

        # Channel administrator
        if member.status == ChatMemberStatus.ADMINISTRATOR:
            return True

        # Channel owner
        if member.status == ChatMemberStatus.OWNER:
            return True

        # Restricted member
        if member.status == ChatMemberStatus.RESTRICTED:
            return getattr(member, "is_member", True)

        # LEFT / BANNED / unknown status
        return False

    except Exception as error:

        logger.error(
            "Membership check failed for %s: %s",
            channel_id,
            error,
        )

        return False


# ============================================================
# CHECK ALL CHANNELS
# ============================================================

async def check_all_channels(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> Tuple[bool, List[Tuple[str, str]]]:

    channels = get_configured_channels()

    missing_channels = []

    for index, channel_id in enumerate(channels):

        joined = await check_channel_membership(
            context,
            channel_id,
            user_id,
        )

        if not joined:

            title, invite_link = await get_channel_info(
                context,
                channel_id,
                index,
            )

            missing_channels.append(
                (
                    title,
                    invite_link,
                )
            )

    return (
        len(missing_channels) == 0,
        missing_channels,
    )


# ============================================================
# FORCE JOIN KEYBOARD
# ============================================================

def build_force_join_keyboard(
    missing_channels: List[Tuple[str, str]],
) -> InlineKeyboardMarkup:

    keyboard = []

    for title, invite_link in missing_channels:

        if invite_link:

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📢 Join {title}",
                        url=invite_link,
                    )
                ]
            )

        else:

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📢 {title}",
                        callback_data="no_link",
                    )
                ]
            )

    # IMPORTANT:
    # Create a new row instead of modifying
    # InlineKeyboardMarkup tuples.

    keyboard.append(
        [
            InlineKeyboardButton(
                "🔄 I've Joined",
                callback_data="verify_join",
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# FORCE JOIN MESSAGE
# ============================================================

async def send_force_join_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    all_joined, missing_channels = await check_all_channels(
        context,
        user.id,
    )

    if all_joined:
        return True

    keyboard = build_force_join_keyboard(
        missing_channels
    )

    text = (
        f"🔐 <b>{BOT_NAME}</b>\n\n"
        "To use the bot, you must join "
        "<b>ALL required channels</b> below.\n\n"
        "📢 Join every channel.\n"
        "🔄 Then press <b>I've Joined</b>.\n\n"
        "⚡ Your membership will be checked automatically."
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    else:

        await update.effective_message.reply_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    return False


# ============================================================
# PENDING MESSAGE
# ============================================================

async def send_pending_message(
    update: Update,
):

    text = (
        "⏳ <b>Approval Pending</b>\n\n"
        "Your request to use "
        f"<b>{BOT_NAME}</b> has been submitted.\n\n"
        "👤 The owner must approve your access.\n\n"
        "Please wait for approval."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔄 Check Approval",
                    callback_data="check_approval",
                )
            ]
        ]
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    else:

        await update.effective_message.reply_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )


# ============================================================
# REJECTED MESSAGE
# ============================================================

async def send_rejected_message(
    update: Update,
):

    text = (
        "❌ <b>Access Rejected</b>\n\n"
        "Your request to use "
        f"<b>{BOT_NAME}</b> was rejected.\n\n"
        "You may request access again."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📨 Request Again",
                    callback_data="request_again",
                )
            ]
        ]
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    else:

        await update.effective_message.reply_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )


# ============================================================
# NOTIFY OWNER
# ============================================================

async def notify_owner_new_request(
    context: ContextTypes.DEFAULT_TYPE,
    user,
):

    username = (
        f"@{user.username}"
        if user.username
        else "No username"
    )

    text = (
        "🔔 <b>New Access Request</b>\n\n"
        f"👤 <b>Name:</b> {user.first_name}\n"
        f"🔗 <b>Username:</b> {username}\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n\n"
        "Choose an action:"
    )

    keyboard = InlineKeyboardMarkup(
        [
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
    )

    try:

        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    except Exception as error:

        logger.error(
            "Could not notify owner: %s",
            error,
        )


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user:
        return

    add_user(
        user.id,
        user.first_name or "",
        user.username or "",
    )

    # Owner automatically approved
    if is_owner(user.id):

        set_approval(
            user.id,
            1,
        )

    approval_status = get_approval_status(
        user.id
    )

    # --------------------------------------------------------
    # REJECTED
    # --------------------------------------------------------

    if approval_status == -1:

        await send_rejected_message(
            update
        )

        return

    # --------------------------------------------------------
    # PENDING
    # --------------------------------------------------------

    if approval_status != 1:

        set_approval(
            user.id,
            0,
        )

        await notify_owner_new_request(
            context,
            user,
        )

        await send_pending_message(
            update
        )

        return

    # --------------------------------------------------------
    # APPROVED
    # --------------------------------------------------------

    all_joined, missing_channels = await check_all_channels(
        context,
        user.id,
    )

    if not all_joined:

        await send_force_join_message(
            update,
            context,
        )

        return

    # --------------------------------------------------------
    # FULL ACCESS
    # --------------------------------------------------------

    set_verified(
        user.id,
        True,
    )

    await update.effective_message.reply_text(
        (
            "🎉 <b>Access Granted!</b>\n\n"
            f"Welcome, <b>{user.first_name}</b>! 👋\n\n"
            "✅ Account approved\n"
            "✅ All required channels joined\n"
            "✅ Membership verified\n\n"
            f"🚀 <b>{BOT_NAME} is ready.</b>"
        ),
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

    await query.answer(
        "🔍 Checking membership..."
    )

    user = query.from_user

    # --------------------------------------------------------
    # CHECK APPROVAL
    # --------------------------------------------------------

    approval_status = get_approval_status(
        user.id
    )

    if user.id == OWNER_ID:

        set_approval(
            user.id,
            1,
        )

        approval_status = 1

    if approval_status == -1:

        await send_rejected_message(
            update
        )

        return

    if approval_status != 1:

        set_approval(
            user.id,
            0,
        )

        await send_pending_message(
            update
        )

        return

    # --------------------------------------------------------
    # CHECK CHANNELS
    # --------------------------------------------------------

    all_joined, missing_channels = await check_all_channels(
        context,
        user.id,
    )

    if not all_joined:

        keyboard = build_force_join_keyboard(
            missing_channels
        )

        names = "\n".join(
            f"• {title}"
            for title, _ in missing_channels
        )

        await query.edit_message_text(
            (
                "❌ <b>Verification Failed</b>\n\n"
                "You have not joined all required channels.\n\n"
                "<b>Still required:</b>\n"
                f"{names}\n\n"
                "Join the remaining channel(s), "
                "then press <b>🔄 I've Joined</b> again."
            ),
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    set_verified(
        user.id,
        True,
    )

    await query.edit_message_text(
        (
            "🎉 <b>Verification Successful!</b>\n\n"
            "✅ All required channels joined.\n"
            "✅ Membership verified.\n"
            "✅ Access approved.\n\n"
            f"🚀 <b>Welcome to {BOT_NAME}!</b>"
        ),
        parse_mode="HTML",
    )


# ============================================================
# CHECK APPROVAL
# ============================================================

async def check_approval(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer(
        "🔍 Checking approval..."
    )

    user = query.from_user

    status = get_approval_status(
        user.id
    )

    if user.id == OWNER_ID:

        set_approval(
            user.id,
            1,
        )

        status = 1

    if status == 1:

        all_joined, missing_channels = await check_all_channels(
            context,
            user.id,
        )

        if not all_joined:

            keyboard = build_force_join_keyboard(
                missing_channels
            )

            await query.edit_message_text(
                (
                    "✅ <b>Approved!</b>\n\n"
                    "Your account has been approved.\n\n"
                    "🔐 Now join all required channels."
                ),
                reply_markup=keyboard,
                parse_mode="HTML",
            )

            return

        set_verified(
            user.id,
            True,
        )

        await query.edit_message_text(
            (
                "🎉 <b>Access Granted!</b>\n\n"
                "Your account is approved and "
                "all required channels are joined."
            ),
            parse_mode="HTML",
        )

        return

    if status == -1:

        await send_rejected_message(
            update
        )

        return

    await send_pending_message(
        update
    )


# ============================================================
# REQUEST AGAIN
# ============================================================

async def request_again(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer(
        "📨 Request submitted."
    )

    user = query.from_user

    add_user(
        user.id,
        user.first_name or "",
        user.username or "",
    )

    set_approval(
        user.id,
        0,
    )

    await notify_owner_new_request(
        context,
        user,
    )

    await send_pending_message(
        update
    )


# ============================================================
# APPROVE / REJECT
# ============================================================

async def process_approval(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not is_owner(query.from_user.id):

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

        user_id = int(
            user_id_text
        )

    except Exception:

        await query.answer(
            "❌ Invalid request.",
            show_alert=True,
        )

        return

    await query.answer()

    # --------------------------------------------------------
    # APPROVE
    # --------------------------------------------------------

    if action == "approve":

        set_approval(
            user_id,
            1,
        )

        await query.edit_message_text(
            (
                "✅ <b>User Approved</b>\n\n"
                f"🆔 User ID: <code>{user_id}</code>"
            ),
            parse_mode="HTML",
        )

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 <b>Access Approved!</b>\n\n"
                    f"Your request to use <b>{BOT_NAME}</b> "
                    "has been approved.\n\n"
                    "Now join all required channels and "
                    "press <b>I've Joined</b>."
                ),
                parse_mode="HTML",
            )

        except Exception as error:

            logger.error(
                "Could not notify approved user %s: %s",
                user_id,
                error,
            )

        return

    # --------------------------------------------------------
    # REJECT
    # --------------------------------------------------------

    if action == "reject":

        set_approval(
            user_id,
            -1,
        )

        await query.edit_message_text(
            (
                "❌ <b>User Rejected</b>\n\n"
                f"🆔 User ID: <code>{user_id}</code>"
            ),
            parse_mode="HTML",
        )

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ <b>Access Rejected</b>\n\n"
                    f"Your request to use <b>{BOT_NAME}</b> "
                    "was rejected.\n\n"
                    "You may request approval again later."
                ),
                parse_mode="HTML",
            )

        except Exception as error:

            logger.error(
                "Could not notify rejected user %s: %s",
                user_id,
                error,
            )


# ============================================================
# /REQUESTS
# ============================================================

async def requests(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id):

        await update.effective_message.reply_text(
            "❌ <b>Owner only.</b>",
            parse_mode="HTML",
        )

        return

    pending = get_pending_users()

    if not pending:

        await update.effective_message.reply_text(
            (
                "📭 <b>No Pending Requests</b>\n\n"
                "There are no users waiting for approval."
            ),
            parse_mode="HTML",
        )

        return

    await update.effective_message.reply_text(
        (
            "📋 <b>Pending Requests</b>\n\n"
            f"⏳ Pending: <b>{len(pending)}</b>"
        ),
        parse_mode="HTML",
    )

    for user_id, first_name, username in pending:

        username_text = (
            f"@{username}"
            if username
            else "No username"
        )

        text = (
            "👤 <b>Pending User</b>\n\n"
            f"Name: <b>{first_name}</b>\n"
            f"Username: <b>{username_text}</b>\n"
            f"User ID: <code>{user_id}</code>"
        )

        keyboard = InlineKeyboardMarkup(
            [
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
        )

        await update.effective_message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )


# ============================================================
# /STATS
# ============================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_owner(update.effective_user.id):

        await update.effective_message.reply_text(
            "❌ <b>Owner only.</b>",
            parse_mode="HTML",
        )

        return

    total = get_user_count()
    pending = get_pending_count()
    approved = get_approved_count()
    verified = get_verified_count()

    await update.effective_message.reply_text(
        (
            f"📊 <b>{BOT_NAME} Statistics</b>\n\n"
            f"👥 Total Users: <b>{total}</b>\n"
            f"⏳ Pending: <b>{pending}</b>\n"
            f"✅ Approved: <b>{approved}</b>\n"
            f"🔐 Verified: <b>{verified}</b>\n"
            f"📢 Required Channels: "
            f"<b>{len(FORCE_JOIN_CHANNELS)}</b>"
        ),
        parse_mode="HTML",
    )


# ============================================================
# /CHANNELS
# ============================================================

async def channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_owner(update.effective_user.id):

        await update.effective_message.reply_text(
            "❌ <b>Owner only.</b>",
            parse_mode="HTML",
        )

        return

    configured = get_configured_channels()

    if not configured:

        await update.effective_message.reply_text(
            "⚠️ No force-join channels configured."
        )

        return

    text = (
        f"📢 <b>{BOT_NAME} Channels</b>\n\n"
    )

    for index, channel_id in enumerate(
        configured,
        start=1,
    ):

        link = get_configured_link(index - 1)

        text += (
            f"<b>{index}.</b> "
            f"<code>{channel_id}</code>\n"
        )

        if link:
            text += f"🔗 {link}\n"

        text += "\n"

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# NO LINK
# ============================================================

async def no_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.callback_query.answer(
        "⚠️ Invite link is not configured.",
        show_alert=True,
    )


# ============================================================
# /HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if is_owner(update.effective_user.id):

        text = (
            f"🛡️ <b>{BOT_NAME}</b>\n\n"
            "👑 <b>Owner Commands</b>\n\n"
            "/requests — Pending approvals\n"
            "/stats — Bot statistics\n"
            "/channels — Required channels\n"
            "/help — Help\n\n"
            "👤 <b>User</b>\n\n"
            "/start — Start bot"
        )

    else:

        text = (
            f"🛡️ <b>{BOT_NAME}</b>\n\n"
            "/start — Start bot\n"
            "/help — Help\n\n"
            "You must be approved and join all "
            "required channels."
        )

    await update.effective_message.reply_text(
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

    print()
    print("🚀 Starting Force Join Bot...")
    print()

    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN is missing in .env"
        )

    if not OWNER_ID:
        raise ValueError(
            "OWNER_ID is missing in .env"
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start,
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
            "help",
            help_command,
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
            check_approval,
            pattern=r"^check_approval$",
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
            pattern=r"^no_link$",
        )
    )

    application.add_error_handler(
        error_handler
    )

    print("✅ Bot is running...")
    print()

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
