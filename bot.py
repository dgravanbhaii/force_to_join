import logging
import re
import html

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from telegram.error import TelegramError, BadRequest

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

database.init_db()


# ============================================================
# BASIC HELPERS
# ============================================================

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


async def is_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:

    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return False

    if is_owner(user.id):
        return True

    if chat.type == ChatType.PRIVATE:
        return False

    try:
        member = await context.bot.get_chat_member(
            chat.id,
            user.id,
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception as exc:
        logger.error("Admin check failed: %s", exc)
        return False


async def bot_is_admin(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> bool:

    try:
        me = await context.bot.get_me()

        member = await context.bot.get_chat_member(
            chat_id,
            me.id,
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception:
        return False


async def require_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:

    if not await is_admin(update, context):

        if update.effective_message:
            await update.effective_message.reply_text(
                "❌ <b>Admins only.</b>",
                parse_mode="HTML",
            )

        return False

    return True


def get_target_user(update: Update):
    """
    Supports:
    /command 123456789
    /command @username
    Reply to a user's message
    """

    message = update.effective_message

    if not message:
        return None

    if message.reply_to_message:
        return message.reply_to_message.from_user

    if not message.text:
        return None

    parts = message.text.split()

    if len(parts) < 2:
        return None

    target = parts[1]

    return target


async def resolve_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.effective_message

    if message.reply_to_message:
        return message.reply_to_message.from_user

    if not message.text:
        return None

    parts = message.text.split()

    if len(parts) < 2:
        return None

    target = parts[1]

    try:
        user_id = int(target)

        return await context.bot.get_chat_member(
            update.effective_chat.id,
            user_id,
        )

    except Exception:
        pass

    if target.startswith("@"):
        try:
            chat = await context.bot.get_chat(target)

            return await context.bot.get_chat_member(
                update.effective_chat.id,
                chat.id,
            )

        except Exception:
            return None

    return None


# ============================================================
# FORCE JOIN MEMBERSHIP
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


async def get_channel_button(
    context: ContextTypes.DEFAULT_TYPE,
    channel_id,
    index: int,
):

    title = f"Channel {index}"
    invite_link = None

    try:

        chat = await context.bot.get_chat(channel_id)

        title = chat.title or title

        # If channel has username
        if chat.username:
            invite_link = f"https://t.me/{chat.username}"

        else:

            # Try creating an invite link.
            try:
                invite = await context.bot.create_chat_invite_link(
                    chat_id=channel_id
                )

                invite_link = invite.invite_link

            except Exception:
                pass

    except Exception as exc:

        logger.warning(
            "Could not get channel information: %s",
            exc,
        )

    return title, invite_link


def build_force_join_keyboard(channels):

    keyboard = []

    for index, (title, invite_link) in enumerate(
        channels,
        start=1,
    ):

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
                        callback_data=f"no_link_{index}",
                    )
                ]
            )

    keyboard.append(
        [
            InlineKeyboardButton(
                "🔄 I've Joined",
                callback_data="verify_join",
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)


async def send_force_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    channels = []

    for index, channel_id in enumerate(
        FORCE_JOIN_CHANNELS,
        start=1,
    ):

        joined = await is_user_joined(
            context,
            channel_id,
            user.id,
        )

        if not joined:

            title, invite_link = await get_channel_button(
                context,
                channel_id,
                index,
            )

            channels.append(
                (
                    title,
                    invite_link,
                )
            )

    if not channels:
        return True

    keyboard = build_force_join_keyboard(
        channels
    )

    text = (
        "🔐 <b>Force Join Required</b>\n\n"
        f"Welcome to <b>{BOT_NAME}</b>.\n\n"
        "You must join <b>ALL</b> required channels "
        "before using the bot.\n\n"
        "After joining them, press:\n"
        "<b>🔄 I've Joined</b>"
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

    # Owner
    if is_owner(user.id):

        await update.message.reply_text(
            f"👑 <b>Welcome Owner!</b>\n\n"
            f"🛡️ <b>{BOT_NAME}</b>\n\n"
            "Use /panel for the owner panel.\n"
            "Use /help to see commands.",
            parse_mode="HTML",
        )

        return

    # Revoked
    approval = database.get_approval_status(
        user.id
    )

    if approval == -1:

        await update.message.reply_text(
            "🚫 <b>Access Revoked</b>\n\n"
            "Your access to this bot has been revoked "
            "by the owner.",
            parse_mode="HTML",
        )

        return

    # Approval required
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
            "Click below to request access.",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML",
        )

        return

    # Force join
    joined = await check_all_channels(
        context,
        user.id,
    )

    if not joined:

        database.set_verified(
            user.id,
            False,
        )

        await send_force_join(
            update,
            context,
        )

        return

    database.set_verified(
        user.id,
        True,
    )

    await update.message.reply_text(
        f"🎉 <b>Welcome {html.escape(user.first_name or '')}!</b>\n\n"
        "✅ Access approved\n"
        "✅ Required channels joined\n"
        "🔓 Access unlocked\n\n"
        f"🚀 <b>{BOT_NAME}</b> is ready.",
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

    if database.get_approval_status(user.id) != 1:

        await query.answer(
            "❌ You are not approved yet.",
            show_alert=True,
        )

        return

    joined = await check_all_channels(
        context,
        user.id,
    )

    if not joined:

        database.set_verified(
            user.id,
            False,
        )

        await query.answer(
            "❌ You haven't joined all required channels.",
            show_alert=True,
        )

        # Rebuild keyboard instead of modifying tuples
        channels = []

        for index, channel_id in enumerate(
            FORCE_JOIN_CHANNELS,
            start=1,
        ):

            member_joined = await is_user_joined(
                context,
                channel_id,
                user.id,
            )

            if not member_joined:

                title, invite_link = await get_channel_button(
                    context,
                    channel_id,
                    index,
                )

                channels.append(
                    (
                        title,
                        invite_link,
                    )
                )

        keyboard = build_force_join_keyboard(
            channels
        )

        await query.edit_message_text(
            "❌ <b>Verification Failed</b>\n\n"
            "You still haven't joined all required "
            "channels.\n\n"
            "Join the remaining channel(s) and "
            "press <b>🔄 I've Joined</b> again.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        return

    database.set_verified(
        user.id,
        True,
    )

    await query.edit_message_text(
        "🎉 <b>Verification Successful!</b>\n\n"
        "✅ All required channels joined.\n"
        "🔓 <b>Access Unlocked!</b>\n\n"
        f"Welcome to <b>{BOT_NAME}</b>.",
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
    user = query.from_user

    await query.answer()

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
        "📩 <b>Request Sent</b>\n\n"
        "Your access request has been sent "
        "to the owner.\n\n"
        "⏳ Please wait for approval.",
        parse_mode="HTML",
    )

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

    try:

        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(
                "📩 <b>New Access Request</b>\n\n"
                f"👤 Name: {html.escape(user.first_name or '')}\n"
                f"🔗 Username: {username}\n"
                f"🆔 ID: <code>{user.id}</code>"
            ),
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML",
        )

    except Exception as exc:

        logger.error(
            "Failed to notify owner: %s",
            exc,
        )


# ============================================================
# APPROVAL
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

    if action == "approve":

        database.set_approval(
            user_id,
            1,
        )

        await query.answer(
            "✅ Approved",
            show_alert=True,
        )

        await query.edit_message_text(
            "✅ <b>User Approved</b>\n\n"
            f"🆔 <code>{user_id}</code>",
            parse_mode="HTML",
        )

        try:

            await context.bot.send_message(
                user_id,
                "🎉 <b>Access Approved!</b>\n\n"
                "You can now join all required "
                "channels and use /start.",
                parse_mode="HTML",
            )

        except Exception:
            pass

    elif action == "reject":

        database.set_approval(
            user_id,
            -1,
        )

        await query.answer(
            "❌ Rejected",
            show_alert=True,
        )

        await query.edit_message_text(
            "❌ <b>User Rejected</b>\n\n"
            f"🆔 <code>{user_id}</code>",
            parse_mode="HTML",
        )


# ============================================================
# REVOKE
# ============================================================

async def revoke_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_owner(update.effective_user.id):

        await update.message.reply_text(
            "❌ Owner only.",
        )

        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "<code>/revoke USER_ID</code>",
            parse_mode="HTML",
        )

        return

    try:

        user_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ Invalid user ID.",
        )

        return

    database.set_approval(
        user_id,
        -1,
    )

    database.set_verified(
        user_id,
        False,
    )

    await update.message.reply_text(
        "🚫 <b>Access Revoked</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>",
        parse_mode="HTML",
    )

    try:

        await context.bot.send_message(
            user_id,
            "🚫 <b>Your bot access has been revoked.</b>",
            parse_mode="HTML",
        )

    except Exception:
        pass


# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_chat.type == ChatType.PRIVATE:

        text = (
            f"🛡️ <b>{BOT_NAME}</b>\n\n"
            "👤 <b>User</b>\n"
            "/start\n"
            "/help\n\n"
        )

        if is_owner(update.effective_user.id):

            text += (
                "👑 <b>Owner</b>\n"
                "/panel\n"
                "/requests\n"
                "/stats\n"
                "/channels\n"
                "/revoke USER_ID\n"
            )

    else:

        text = (
            f"🛡️ <b>{BOT_NAME}</b>\n\n"
            "🛡️ <b>Moderation</b>\n"
            "/warn\n"
            "/unwarn\n"
            "/warnings\n"
            "/ban\n"
            "/unban\n"
            "/mute\n"
            "/unmute\n"
            "/kick\n"
            "/purge\n"
            "/promote\n"
            "/demote\n\n"
            "🔒 <b>Locks</b>\n"
            "/lock\n"
            "/unlock\n"
            "/locks\n\n"
            "📜 <b>Group</b>\n"
            "/rules\n"
            "/setrules\n"
            "/welcome\n"
            "/goodbye\n\n"
            "🌐 <b>Federation</b>\n"
            "/newfed NAME\n"
            "/joinfed FED_ID\n"
            "/fban\n"
            "/funban\n"
            "/fmute\n"
            "/funmute\n"
        )

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# WARN
# ============================================================

async def warn(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    target = await resolve_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "Reply to a user or use:\n"
            "/warn USER_ID",
        )

        return

    user = target.user

    if user.id == update.effective_user.id:

        await update.message.reply_text(
            "❌ You cannot warn yourself.",
        )

        return

    count = database.add_warn(
        update.effective_chat.id,
        user.id,
    )

    settings = database.get_group_settings(
        update.effective_chat.id
    )

    limit = settings[5] if settings else 3

    await update.message.reply_text(
        f"⚠️ <b>Warning</b>\n\n"
        f"👤 {html.escape(user.first_name)}\n"
        f"⚠️ Warnings: <b>{count}/{limit}</b>",
        parse_mode="HTML",
    )

    if count >= limit:

        try:

            await context.bot.ban_chat_member(
                update.effective_chat.id,
                user.id,
            )

            database.reset_warns(
                update.effective_chat.id,
                user.id,
            )

            await update.message.reply_text(
                f"🚫 <b>{html.escape(user.first_name)}</b> "
                f"has been banned after reaching "
                f"{limit} warnings.",
                parse_mode="HTML",
            )

        except Exception as exc:

            logger.error(
                "Auto-ban failed: %s",
                exc,
            )


# ============================================================
# UNWARN
# ============================================================

async def unwarn(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    target = await resolve_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "Reply to a user or provide USER_ID.",
        )

        return

    database.reset_warns(
        update.effective_chat.id,
        target.user.id,
    )

    await update.message.reply_text(
        f"✅ Warnings reset for "
        f"<b>{html.escape(target.user.first_name)}</b>.",
        parse_mode="HTML",
    )


# ============================================================
# WARNINGS
# ============================================================

async def warnings(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    target = await resolve_user(
        update,
        context,
    )

    if not target:

        if update.message.reply_to_message:
            user = update.message.reply_to_message.from_user
        else:
            user = update.effective_user

    else:
        user = target.user

    count = database.get_warns(
        update.effective_chat.id,
        user.id,
    )

    await update.message.reply_text(
        f"⚠️ <b>Warnings</b>\n\n"
        f"👤 {html.escape(user.first_name)}\n"
        f"🆔 <code>{user.id}</code>\n"
        f"⚠️ Warnings: <b>{count}</b>",
        parse_mode="HTML",
    )


# ============================================================
# BAN
# ============================================================

async def ban(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    target = await resolve_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "Reply to a user or use /ban USER_ID.",
        )

        return

    try:

        await context.bot.ban_chat_member(
            update.effective_chat.id,
            target.user.id,
        )

        await update.message.reply_text(
            f"🚫 <b>{html.escape(target.user.first_name)}</b> "
            "has been banned.",
            parse_mode="HTML",
        )

    except Exception as exc:

        await update.message.reply_text(
            f"❌ Ban failed:\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )


# ============================================================
# UNBAN
# ============================================================

async def unban(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /unban USER_ID",
        )

        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid user ID."
        )
        return

    try:

        await context.bot.unban_chat_member(
            update.effective_chat.id,
            user_id,
            only_if_banned=True,
        )

        await update.message.reply_text(
            f"✅ User <code>{user_id}</code> unbanned.",
            parse_mode="HTML",
        )

    except Exception as exc:

        await update.message.reply_text(
            f"❌ Unban failed:\n{html.escape(str(exc))}",
        )


# ============================================================
# MUTE
# ============================================================

async def mute(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    target = await resolve_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "Reply to a user or use /mute USER_ID.",
        )

        return

    try:

        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.user.id,
            permissions={
                "can_send_messages": False,
            },
        )

    except Exception:

        from telegram import ChatPermissions

        try:

            await context.bot.restrict_chat_member(
                update.effective_chat.id,
                target.user.id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                ),
            )

        except Exception as exc:

            await update.message.reply_text(
                f"❌ Mute failed:\n{html.escape(str(exc))}",
                parse_mode="HTML",
            )

            return

    await update.message.reply_text(
        f"🔇 <b>{html.escape(target.user.first_name)}</b> muted.",
        parse_mode="HTML",
    )


# ============================================================
# UNMUTE
# ============================================================

async def unmute(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    target = await resolve_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "Reply to a user or use /unmute USER_ID.",
        )

        return

    from telegram import ChatPermissions

    try:

        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.user.id,
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

        await update.message.reply_text(
            f"🔊 <b>{html.escape(target.user.first_name)}</b> unmuted.",
            parse_mode="HTML",
        )

    except Exception as exc:

        await update.message.reply_text(
            f"❌ Unmute failed:\n{html.escape(str(exc))}",
            parse_mode="HTML",
        )


# ============================================================
# KICK
# ============================================================

async def kick(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    target = await resolve_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "Reply to a user or use /kick USER_ID.",
        )

        return

    try:

        await context.bot.ban_chat_member(
            update.effective_chat.id,
            target.user.id,
        )

        await context.bot.unban_chat_member(
            update.effective_chat.id,
            target.user.id,
        )

        await update.message.reply_text(
            f"👢 <b>{html.escape(target.user.first_name)}</b> kicked.",
            parse_mode="HTML",
        )

    except Exception as exc:

        await update.message.reply_text(
            f"❌ Kick failed:\n{html.escape(str(exc))}",
            parse_mode="HTML",
        )


# ============================================================
# PURGE
# ============================================================

async def purge(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    message = update.effective_message

    if not message.reply_to_message:

        await message.reply_text(
            "Reply to the first message and use /purge.",
        )

        return

    start_id = message.reply_to_message.message_id
    end_id = message.message_id

    deleted = 0

    for message_id in range(
        start_id,
        end_id + 1,
    ):

        try:

            await context.bot.delete_message(
                update.effective_chat.id,
                message_id,
            )

            deleted += 1

        except Exception:
            pass

    try:

        await context.bot.send_message(
            update.effective_chat.id,
            f"🧹 Purged <b>{deleted}</b> messages.",
            parse_mode="HTML",
        )

    except Exception:
        pass


# ============================================================
# PROMOTE
# ============================================================

async def promote(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    target = await resolve_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "Reply to a user or use /promote USER_ID.",
        )

        return

    try:

        await context.bot.promote_chat_member(
            update.effective_chat.id,
            target.user.id,
            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=True,
        )

        await update.message.reply_text(
            f"👑 <b>{html.escape(target.user.first_name)}</b> promoted.",
            parse_mode="HTML",
        )

    except Exception as exc:

        await update.message.reply_text(
            f"❌ Promote failed:\n{html.escape(str(exc))}",
            parse_mode="HTML",
        )


# ============================================================
# DEMOTE
# ============================================================

async def demote(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    target = await resolve_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "Reply to a user or use /demote USER_ID.",
        )

        return

    try:

        await context.bot.promote_chat_member(
            update.effective_chat.id,
            target.user.id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
        )

        await update.message.reply_text(
            f"⬇️ <b>{html.escape(target.user.first_name)}</b> demoted.",
            parse_mode="HTML",
        )

    except Exception as exc:

        await update.message.reply_text(
            f"❌ Demote failed:\n{html.escape(str(exc))}",
            parse_mode="HTML",
        )


# ============================================================
# RULES
# ============================================================

async def rules(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    settings = database.get_group_settings(
        update.effective_chat.id
    )

    text = settings[4] if settings else None

    if not text:
        text = database.DEFAULT_RULES

    await update.effective_message.reply_text(
        f"📜 <b>Group Rules</b>\n\n{html.escape(text)}",
        parse_mode="HTML",
    )


async def setrules(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "<code>/setrules Your rules here</code>",
            parse_mode="HTML",
        )

        return

    text = " ".join(context.args)

    database.set_rules(
        update.effective_chat.id,
        text,
    )

    await update.message.reply_text(
        "✅ Group rules updated.",
    )


# ============================================================
# WELCOME / GOODBYE
# ============================================================

async def welcome(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    settings = database.get_group_settings(
        update.effective_chat.id
    )

    enabled = bool(settings[0])

    database.set_welcome(
        update.effective_chat.id,
        not enabled,
    )

    status = "enabled" if not enabled else "disabled"

    await update.message.reply_text(
        f"👋 Welcome messages <b>{status}</b>.",
        parse_mode="HTML",
    )


async def goodbye(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    settings = database.get_group_settings(
        update.effective_chat.id
    )

    enabled = bool(settings[2])

    database.set_goodbye(
        update.effective_chat.id,
        not enabled,
    )

    status = "enabled" if not enabled else "disabled"

    await update.message.reply_text(
        f"👋 Goodbye messages <b>{status}</b>.",
        parse_mode="HTML",
    )


# ============================================================
# LOCKS
# ============================================================

LOCK_TYPES = {
    "links": "links",
    "link": "links",
    "url": "links",
    "username": "username",
    "usernames": "username",
    "bio": "bio",
    "bots": "bots",
    "forward": "forward",
}


async def lock(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "/lock links\n"
            "/lock username\n"
            "/lock bio\n"
            "/lock bots\n"
            "/lock forward",
        )

        return

    lock_type = LOCK_TYPES.get(
        context.args[0].lower()
    )

    if not lock_type:

        await update.message.reply_text(
            "❌ Unknown lock type.",
        )

        return

    database.set_lock(
        update.effective_chat.id,
        lock_type,
        True,
    )

    await update.message.reply_text(
        f"🔒 <b>{lock_type}</b> lock enabled.",
        parse_mode="HTML",
    )


async def unlock(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /unlock links",
        )

        return

    lock_type = LOCK_TYPES.get(
        context.args[0].lower()
    )

    if not lock_type:

        await update.message.reply_text(
            "❌ Unknown lock type.",
        )

        return

    database.set_lock(
        update.effective_chat.id,
        lock_type,
        False,
    )

    await update.message.reply_text(
        f"🔓 <b>{lock_type}</b> lock disabled.",
        parse_mode="HTML",
    )


async def locks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    active = database.get_locks(
        update.effective_chat.id
    )

    if not active:

        await update.message.reply_text(
            "🔓 No locks are enabled.",
        )

        return

    text = "\n".join(
        f"🔒 {item}"
        for item in active
    )

    await update.message.reply_text(
        f"🔐 <b>Active Locks</b>\n\n{text}",
        parse_mode="HTML",
    )


# ============================================================
# NEW FEDERATION
# ============================================================

async def newfed(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not is_owner(user.id) and not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ Admins only.",
        )
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "<code>/newfed Federation Name</code>",
            parse_mode="HTML",
        )

        return

    name = " ".join(context.args)

    fed_id = f"{user.id}_{update.effective_chat.id}"

    database.create_federation(
        fed_id,
        name,
        user.id,
    )

    database.add_fed_chat(
        fed_id,
        update.effective_chat.id,
    )

    await update.message.reply_text(
        "🌐 <b>Federation Created</b>\n\n"
        f"📛 Name: {html.escape(name)}\n"
        f"🆔 ID: <code>{fed_id}</code>\n\n"
        "Use this ID with /joinfed.",
        parse_mode="HTML",
    )


# ============================================================
# JOIN FEDERATION
# ============================================================

async def joinfed(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "<code>/joinfed FED_ID</code>",
            parse_mode="HTML",
        )

        return

    fed_id = context.args[0]

    fed = database.get_federation(
        fed_id
    )

    if not fed:

        await update.message.reply_text(
            "❌ Federation not found.",
        )

        return

    database.add_fed_chat(
        fed_id,
        update.effective_chat.id,
    )

    await update.message.reply_text(
        "🌐 <b>Federation Joined</b>\n\n"
        f"📛 {html.escape(fed[1])}\n"
        f"🆔 <code>{fed_id}</code>",
        parse_mode="HTML",
    )


# ============================================================
# FED BAN
# ============================================================

async def fban(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "/fban USER_ID FED_ID",
        )

        return

    try:

        user_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ Invalid user ID.",
        )

        return

    fed_id = (
        context.args[1]
        if len(context.args) > 1
        else None
    )

    if not fed_id:

        await update.message.reply_text(
            "❌ Provide FED_ID.",
        )

        return

    if not database.get_federation(fed_id):

        await update.message.reply_text(
            "❌ Federation not found.",
        )

        return

    database.fed_ban(
        fed_id,
        user_id,
    )

    try:

        await context.bot.ban_chat_member(
            update.effective_chat.id,
            user_id,
        )

    except Exception:
        pass

    await update.message.reply_text(
        f"🌐🚫 User <code>{user_id}</code> "
        f"federation-banned.",
        parse_mode="HTML",
    )


# ============================================================
# FED UNBAN
# ============================================================

async def funban(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "/funban USER_ID FED_ID",
        )

        return

    try:

        user_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ Invalid user ID.",
        )

        return

    fed_id = context.args[1]

    database.fed_unban(
        fed_id,
        user_id,
    )

    try:

        await context.bot.unban_chat_member(
            update.effective_chat.id,
            user_id,
            only_if_banned=True,
        )

    except Exception:
        pass

    await update.message.reply_text(
        f"✅ User <code>{user_id}</code> "
        "removed from federation ban.",
        parse_mode="HTML",
    )


# ============================================================
# FED MUTE
# ============================================================

async def fmute(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "/fmute USER_ID FED_ID",
        )

        return

    try:

        user_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ Invalid user ID.",
        )

        return

    fed_id = context.args[1]

    database.fed_mute(
        fed_id,
        user_id,
    )

    try:

        from telegram import ChatPermissions

        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            user_id,
            permissions=ChatPermissions(
                can_send_messages=False,
            ),
        )

    except Exception:
        pass

    await update.message.reply_text(
        f"🌐🔇 User <code>{user_id}</code> "
        "federation-muted.",
        parse_mode="HTML",
    )


# ============================================================
# FED UNMUTE
# ============================================================

async def funmute(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_admin(update, context):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "/funmute USER_ID FED_ID",
        )

        return

    try:

        user_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ Invalid user ID.",
        )

        return

    fed_id = context.args[1]

    database.fed_unmute(
        fed_id,
        user_id,
    )

    try:

        from telegram import ChatPermissions

        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
            ),
        )

    except Exception:
        pass

    await update.message.reply_text(
        f"✅ User <code>{user_id}</code> "
        "removed from federation mute.",
        parse_mode="HTML",
    )


# ============================================================
# MESSAGE RESTRICTIONS
# ============================================================

URL_REGEX = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/)",
    re.IGNORECASE,
)


async def moderation_filter(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    if chat.type == ChatType.PRIVATE:
        return

    # Never moderate admins
    if await is_admin(update, context):
        return

    text = message.text or message.caption or ""

    # --------------------------------------------------------
    # LINKS
    # --------------------------------------------------------

    if database.is_locked(
        chat.id,
        "links",
    ):

        if URL_REGEX.search(text):

            try:
                await message.delete()
            except Exception:
                pass

            return

    # --------------------------------------------------------
    # FORWARDED MESSAGES
    # --------------------------------------------------------

    if database.is_locked(
        chat.id,
        "forward",
    ):

        if message.forward_origin:

            try:
                await message.delete()
            except Exception:
                pass

            return

    # --------------------------------------------------------
    # BOTS
    # --------------------------------------------------------

    if database.is_locked(
        chat.id,
        "bots",
    ):

        if user.is_bot:

            try:
                await message.delete()
            except Exception:
                pass

            return


# ============================================================
# NEW MEMBER WELCOME
# ============================================================

async def new_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.effective_message

    if not message:
        return

    settings = database.get_group_settings(
        update.effective_chat.id
    )

    if not settings:
        return

    if not settings[0]:
        return

    for user in message.new_chat_members:

        mention = (
            f'<a href="tg://user?id={user.id}">'
            f'{html.escape(user.first_name)}'
            f'</a>'
        )

        text = settings[1] or database.DEFAULT_WELCOME

        text = text.replace(
            "{mention}",
            mention,
        )

        text = text.replace(
            "{name}",
            html.escape(user.first_name),
        )

        text = text.replace(
            "{chatname}",
            html.escape(
                update.effective_chat.title or ""
            ),
        )

        await message.reply_text(
            text,
            parse_mode="HTML",
        )


# ============================================================
# GOODBYE
# ============================================================

async def left_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.effective_message

    if not message:
        return

    member = message.left_chat_member

    if not member:
        return

    settings = database.get_group_settings(
        update.effective_chat.id
    )

    if not settings or not settings[2]:
        return

    text = settings[3] or database.DEFAULT_GOODBYE

    text = text.replace(
        "{name}",
        html.escape(member.first_name),
    )

    await message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# CHANNELS
# ============================================================

async def channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_owner(update.effective_user.id):

        await update.message.reply_text(
            "❌ Owner only.",
        )

        return

    text = "📢 <b>Force Join Channels</b>\n\n"

    for index, channel_id in enumerate(
        FORCE_JOIN_CHANNELS,
        start=1,
    ):

        title, invite = await get_channel_button(
            context,
            channel_id,
            index,
        )

        text += (
            f"{index}. <b>{html.escape(title)}</b>\n"
            f"ID: <code>{channel_id}</code>\n"
        )

        if invite:
            text += f"{invite}\n"

        text += "\n"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# STATS
# ============================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_owner(update.effective_user.id):

        await update.message.reply_text(
            "❌ Owner only.",
        )

        return

    await update.message.reply_text(
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Users: <b>{database.get_user_count()}</b>\n"
        f"✅ Verified: <b>{database.get_verified_count()}</b>\n"
        f"🟢 Approved: <b>{database.get_approved_count()}</b>\n"
        f"⏳ Pending: <b>{database.get_pending_count()}</b>",
        parse_mode="HTML",
    )


# ============================================================
# REQUESTS
# ============================================================

async def requests(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_owner(update.effective_user.id):

        await update.message.reply_text(
            "❌ Owner only.",
        )

        return

    pending = database.get_pending_users()

    if not pending:

        await update.message.reply_text(
            "✅ No pending requests.",
        )

        return

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
            "📩 <b>Pending Request</b>\n\n"
            f"👤 {html.escape(first_name)}\n"
            f"🔗 {username_text}\n"
            f"🆔 <code>{user_id}</code>",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML",
        )


# ============================================================
# NO LINK CALLBACK
# ============================================================

async def no_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.callback_query.answer(
        "Please use the channel link provided by the bot.",
        show_alert=True,
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

    # --------------------------------------------------------
    # OWNER
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "revoke",
            revoke_user,
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
            "requests",
            requests,
        )
    )

    application.add_handler(
        CommandHandler(
            "channels",
            channels,
        )
    )

    # --------------------------------------------------------
    # MODERATION
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler("warn", warn)
    )

    application.add_handler(
        CommandHandler("unwarn", unwarn)
    )

    application.add_handler(
        CommandHandler("warnings", warnings)
    )

    application.add_handler(
        CommandHandler("ban", ban)
    )

    application.add_handler(
        CommandHandler("unban", unban)
    )

    application.add_handler(
        CommandHandler("mute", mute)
    )

    application.add_handler(
        CommandHandler("unmute", unmute)
    )

    application.add_handler(
        CommandHandler("kick", kick)
    )

    application.add_handler(
        CommandHandler("purge", purge)
    )

    application.add_handler(
        CommandHandler("promote", promote)
    )

    application.add_handler(
        CommandHandler("demote", demote)
    )

    # --------------------------------------------------------
    # GROUP
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler("rules", rules)
    )

    application.add_handler(
        CommandHandler("setrules", setrules)
    )

    application.add_handler(
        CommandHandler("welcome", welcome)
    )

    application.add_handler(
        CommandHandler("goodbye", goodbye)
    )

    # --------------------------------------------------------
    # LOCKS
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler("lock", lock)
    )

    application.add_handler(
        CommandHandler("unlock", unlock)
    )

    application.add_handler(
        CommandHandler("locks", locks)
    )

    # --------------------------------------------------------
    # FEDERATION
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler("newfed", newfed)
    )

    application.add_handler(
        CommandHandler("joinfed", joinfed)
    )

    application.add_handler(
        CommandHandler("fban", fban)
    )

    application.add_handler(
        CommandHandler("funban", funban)
    )

    application.add_handler(
        CommandHandler("fmute", fmute)
    )

    application.add_handler(
        CommandHandler("funmute", funmute)
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
    # NEW MEMBERS
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            new_member,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            left_member,
        )
    )

    # --------------------------------------------------------
    # MESSAGE MODERATION
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            moderation_filter,
        )
    )

    # --------------------------------------------------------
    # ERRORS
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
