import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetChat, SetMyCommands
from aiogram.types import BotCommandScopeAllPrivateChats, BotCommandScopeChat

from tests.telegram.fake_api import FakeTelegram
from tgmate.config import Settings
from tgmate.telegram.setup import OWNER_COMMANDS, USER_COMMANDS, prepare_bot


async def test_sets_command_menus_and_checks_the_owner(bot: Bot, telegram: FakeTelegram, settings: Settings) -> None:
    await prepare_bot(bot, settings)

    users, owner = telegram.calls(SetMyCommands)
    assert (users.commands, type(users.scope)) == (USER_COMMANDS, BotCommandScopeAllPrivateChats)
    assert (owner.commands, owner.scope) == (OWNER_COMMANDS, BotCommandScopeChat(chat_id=settings.owner_user_id))
    assert [call.chat_id for call in telegram.calls(GetChat)] == [settings.owner_user_id]


async def test_failures_are_logged_not_raised(
    bot: Bot, telegram: FakeTelegram, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    telegram.errors[SetMyCommands] = TelegramBadRequest(SetMyCommands(commands=[]), "bad")
    telegram.errors[GetChat] = TelegramBadRequest(GetChat(chat_id=1), "chat not found")

    await prepare_bot(bot, settings)

    assert "could not set the command menu" in caplog.text
    assert "send /start to the bot" in caplog.text
