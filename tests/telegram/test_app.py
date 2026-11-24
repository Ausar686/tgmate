import asyncio
import pathlib

import pydantic
import pytest
import sqlalchemy as sa
from aiogram import Dispatcher
from aiogram.client.session.base import DEFAULT_TIMEOUT
from aiogram.client.telegram import PRODUCTION

from tgmate.config import Settings
from tgmate.telegram import app
from tgmate.telegram.files import MB, Limits


async def test_run_migrates_prepares_the_bot_and_polls_for_the_updates_it_handles(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, jobs_dir: pathlib.Path
) -> None:
    # Left by a download a shutdown interrupted.
    (jobs_dir / "tmp1234").mkdir()
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
    assert list(jobs_dir.iterdir()) == []
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


def test_without_a_server_of_its_own_the_bot_uses_telegrams(settings: Settings) -> None:
    session = app.api_session(settings)

    assert session.api is PRODUCTION
    assert session.timeout == DEFAULT_TIMEOUT


def test_a_local_server_is_used_in_local_mode_with_room_for_large_files(settings: Settings) -> None:
    local = settings.model_copy(update={"telegram_api_url": pydantic.HttpUrl("http://bot-api:8081")})

    session = app.api_session(local)

    assert session.api.is_local
    assert session.api.api_url("42:T", "getMe") == "http://bot-api:8081/bot42:T/getMe"
    assert session.timeout == app.LOCAL_REQUEST_TIMEOUT_SECONDS


def test_the_dispatcher_gets_the_file_limits_of_the_settings(settings: Settings) -> None:
    local = settings.model_copy(update={"telegram_api_url": pydantic.HttpUrl("http://bot-api:8081")})

    assert app.build_dispatcher(settings)["limits"] == Limits(20 * MB, 50 * MB)
    assert app.build_dispatcher(local)["limits"] == Limits(20 * MB, 2000 * MB)
