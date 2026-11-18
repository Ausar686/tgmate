"""Who may use the bot: the gate in front of the tools, owner approval of new users by DM, and leaving groups."""

import collections.abc as cabc
import html
import logging
import typing as t

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import JOIN_TRANSITION, ChatMemberUpdatedFilter, Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, Message, TelegramObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tgmate.config import Settings
from tgmate.storage import repo
from tgmate.storage.models import User, UserStatus
from tgmate.telegram.cooldown import Cooldown

log = logging.getLogger(__name__)

# Someone who keeps writing before the owner answers would otherwise DM the owner every time.
APPROVAL_REQUEST_INTERVAL_SECONDS = 24 * 60 * 60
# How often a user who isn't approved hears why the bot doesn't answer.
ACCESS_NOTICE_INTERVAL_SECONDS = 60 * 60

REQUESTED = "Access requested. I'll message you here once the bot owner approves it."
WAITING = "Your access request is waiting for the bot owner's approval."
DENIED = "This bot is private."
WRITE_TO_ASK = "Send me a message to ask the bot owner for access."
APPROVED = "✅ The bot owner approved your access. Send /help to see what I can do."


def source_notice(source_url: str) -> str:
    """The AGPL's offer of the source code to everyone who uses the bot over the network."""
    url = html.escape(source_url, quote=True)
    return f'tgmate is free software under the AGPL-3.0-or-later: <a href="{url}">source code</a>.'

# Revoked users aren't listed: they ask again by writing to the bot.
_LISTED = {UserStatus.PENDING: "⏳", UserStatus.APPROVED: "✅", UserStatus.REJECTED: "🚫"}
_OUTCOME = {UserStatus.APPROVED: "approved", UserStatus.REJECTED: "rejected", UserStatus.REVOKED: "revoked"}


class UserAction(CallbackData, prefix="user"):
    action: str
    user_id: int


def is_owner(event: Message | CallbackQuery, settings: Settings) -> bool:
    return event.from_user is not None and event.from_user.id == settings.owner_user_id


def build_access_router() -> Router:
    router = Router(name="access")
    router.message.register(list_users, F.chat.type == "private", Command("users"), is_owner)
    router.callback_query.register(on_user_action, UserAction.filter(), is_owner)
    router.my_chat_member.register(leave_chat, F.chat.type != "private", ChatMemberUpdatedFilter(JOIN_TRANSITION))
    return router


Handler = cabc.Callable[[TelegramObject, dict[str, t.Any]], cabc.Awaitable[object]]


async def require_access(handler: Handler, event: TelegramObject, data: dict[str, t.Any]) -> object:
    """Let the owner and approved users through; register anyone else who writes and ask the owner about them."""
    settings: Settings = data["settings"]
    sender = getattr(event, "from_user", None)
    if sender is None:
        return None
    if sender.id == settings.owner_user_id:
        return await handler(event, data)
    if isinstance(event, CallbackQuery):
        return await _button_access(handler, event, data)
    async with data["sessionmaker"]() as session:
        user = await repo.upsert_user(session, sender.id, full_name=sender.full_name, username=sender.username)
        if user.status is UserStatus.REVOKED:
            user.status = UserStatus.PENDING
        await session.commit()
    if user.status is UserStatus.APPROVED:
        return await handler(event, data)
    if user.status is UserStatus.PENDING and data["approval_requests"].ready(user.id):
        await notify_owner(data["bot"], settings, f"{describe_user(user)} asks to use the bot.", _keyboard(user))
        await event.answer(f"{REQUESTED}\n\n{source_notice(settings.source_url)}")
        return None
    notices: Cooldown = data["access_notices"]
    if notices.ready(user.id):
        await event.answer(DENIED if user.status is UserStatus.REJECTED else WAITING)
    return None


async def _button_access(handler: Handler, query: CallbackQuery, data: dict[str, t.Any]) -> object:
    """Let approved users' button presses through; anyone else gets an alert, and nothing is stored or asked."""
    async with data["sessionmaker"]() as session:
        user = await repo.get_user(session, query.from_user.id)
    status = None if user is None else user.status
    if status is UserStatus.APPROVED:
        return await handler(query, data)
    alerts = {UserStatus.PENDING: WAITING, UserStatus.REJECTED: DENIED}
    await query.answer(alerts.get(status, WRITE_TO_ASK), show_alert=True)
    return None


def describe_user(user: User) -> str:
    name = html.escape(user.full_name)
    username = f" @{html.escape(user.username)}" if user.username else ""
    return f"<b>{name}</b>{username} (<code>{user.id}</code>)"


def _keyboard(*users: User) -> InlineKeyboardMarkup:
    """Approve/reject for pending users, revoke for approved ones, approve for rejected ones."""
    keyboard = InlineKeyboardBuilder()
    for user in users:
        actions = {
            UserStatus.PENDING: ["approve", "reject"],
            UserStatus.APPROVED: ["revoke"],
            UserStatus.REJECTED: ["approve"],
        }[user.status]
        label = user.full_name[:24] if len(users) > 1 else ""
        for action in actions:
            text = f"{action.capitalize()} {label}".strip()
            keyboard.button(text=text, callback_data=UserAction(action=action, user_id=user.id))
    keyboard.adjust(2 if len(users) == 1 else 1)
    return keyboard.as_markup()


async def notify_owner(bot: Bot, settings: Settings, text: str, markup: InlineKeyboardMarkup | None = None) -> bool:
    """DM the owner; False when they haven't started the bot (Telegram forbids bots from messaging first)."""
    return await _send_quietly(bot.send_message(settings.owner_user_id, text, reply_markup=markup))


async def list_users(message: Message, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        users = await repo.list_users(session, frozenset(_LISTED))
    if not users:
        await message.answer("No pending, approved or rejected users.")
        return
    lines = [f"{_LISTED[user.status]} {describe_user(user)}" for user in users]
    await message.answer("\n".join(lines), reply_markup=_keyboard(*users))


async def on_user_action(
    query: CallbackQuery, callback_data: UserAction, bot: Bot, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    status = {"approve": UserStatus.APPROVED, "reject": UserStatus.REJECTED, "revoke": UserStatus.REVOKED}.get(
        callback_data.action
    )
    if status is None:
        await query.answer("Unknown action.", show_alert=True)
        return
    async with sessionmaker() as session:
        user = await repo.get_user(session, callback_data.user_id)
        if user is None:
            await query.answer("Unknown user.", show_alert=True)
            return
        user.status = status
        await session.commit()
    summary = f"{describe_user(user)}: {_OUTCOME[status]}."
    if status is UserStatus.APPROVED and not await _send_quietly(bot.send_message(user.id, APPROVED)):
        summary += " Couldn't tell them; they'll find out the next time they write."
    await query.answer(f"User {_OUTCOME[status]}.")
    if isinstance(query.message, Message):
        await _send_quietly(query.message.edit_text(summary))


async def leave_chat(event: ChatMemberUpdated, bot: Bot) -> None:
    """The bot works in private chats only; adding it to a group or channel just makes it leave."""
    log.info("added to %s %d by user %d; leaving", event.chat.type, event.chat.id, event.from_user.id)
    await _send_quietly(bot.leave_chat(event.chat.id))


async def _send_quietly(call: cabc.Awaitable[object]) -> bool:
    """The chat or DM may be gone already; what's stored is what matters. False on failure."""
    try:
        await call
    except TelegramAPIError as exc:
        log.warning("telegram call failed: %s", exc)
        return False
    return True
