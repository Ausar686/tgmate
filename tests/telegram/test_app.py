import asyncio

import pytest
import sqlalchemy as sa
from aiogram import Dispatcher

from tgmate.config import Settings
from tgmate.telegram import app


async def test_run_migrates_prepares_the_bot_and_polls_for_the_updates_it_handles(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    polling: dict[str, object] = {}
    prepared: list[Settings] = []

    async def fake_polling(self: Dispatcher, bot: object, **kwargs: object) -> None:
        polling.update(kwargs)

    async def fake_prepare(bot: object, settings: Settings) -> None:
        prepared.append(settings)

    monkeypatch.setattr(Dispatcher, "start_polling", fake_polling)
    monkeypatch.setattr(app, "prepare_bot", fake_prepare)

    await asyncio.wait_for(app.run(settings), timeout=5)

    assert prepared == [settings]
    assert set(polling["allowed_updates"]) == {"message", "callback_query", "my_chat_member"}
    engine = sa.create_engine(settings.database_url.get_secret_value().replace("+aiosqlite", ""))
    with engine.connect() as connection:
        assert "users" in sa.inspect(connection).get_table_names()
    engine.dispose()


def test_main_loads_settings_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[Settings] = []

    async def fake_run(settings: Settings) -> None:
        ran.append(settings)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("OWNER_USER_ID", "7")
    monkeypatch.setattr(app, "run", fake_run)

    app.main()

    [settings] = ran
    assert settings.owner_user_id == 7
