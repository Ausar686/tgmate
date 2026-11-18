"""One-time bot preparation at startup: command menus and a check that the owner can be reached."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from tgmate.config import Settings

log = logging.getLogger(__name__)

USER_COMMANDS = [
    BotCommand(command="help", description="What I can do"),
    BotCommand(command="qr", description="<link>: QR code for a link"),
]
OWNER_COMMANDS = [*USER_COMMANDS, BotCommand(command="users", description="Approve or revoke users")]


async def prepare_bot(bot: Bot, settings: Settings) -> None:
    """Best effort: a failure here shouldn't keep the bot from working."""
    try:
        await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=settings.owner_user_id))
    except TelegramAPIError as exc:
        log.warning("could not set the command menu: %s", exc)
    try:
        await bot.get_chat(settings.owner_user_id)
    except TelegramAPIError as exc:
        log.warning(
            "the owner %d can't be reached; send /start to the bot from that account: %s", settings.owner_user_id, exc
        )
    return None
