import pytest
from aiogram import Bot
from aiogram.client.telegram import PRODUCTION
from aiogram.methods import LogOut

from tests.telegram.fake_api import FakeTelegram
from tgmate.telegram import logout


async def test_log_out_logs_the_bot_out_and_closes_its_session(
    bot: Bot, telegram: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[bool] = []

    async def close() -> None:
        closed.append(True)

    monkeypatch.setattr(telegram, "close", close)

    await logout.log_out(bot)

    assert len(telegram.calls(LogOut)) == 1
    assert closed == [True]


def test_main_logs_out_of_the_hosted_api_even_when_the_bot_has_its_own(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bots: list[Bot] = []

    async def fake_log_out(bot: Bot) -> None:
        bots.append(bot)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("OWNER_USER_ID", "7")
    monkeypatch.setenv("TELEGRAM_API_URL", "http://bot-api:8081")
    monkeypatch.setattr(logout, "log_out", fake_log_out)

    logout.main()

    [bot] = bots
    assert (bot.token, bot.session.api) == ("123:abc", PRODUCTION)
    assert capsys.readouterr().out.strip() == logout.DONE
