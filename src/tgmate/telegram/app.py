"""Wires settings, storage and the Telegram dispatcher together; run with `python -m tgmate.telegram`."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode

from tgmate.config import Settings
from tgmate.storage import db
from tgmate.telegram.access import (
    ACCESS_NOTICE_INTERVAL_SECONDS,
    APPROVAL_REQUEST_INTERVAL_SECONDS,
    build_access_router,
)
from tgmate.telegram.cooldown import Cooldown
from tgmate.telegram.files import Albums, Limits
from tgmate.telegram.setup import prepare_bot
from tgmate.telegram.tools import build_tools_router

# A local Bot API server sits next to the bot, so a slow request is a large file on its way, not a lost connection.
LOCAL_REQUEST_TIMEOUT_SECONDS = 10 * 60


def build_dispatcher(settings: Settings, **context: object) -> Dispatcher:
    dispatcher = Dispatcher(
        settings=settings,
        limits=Limits.of(settings),
        approval_requests=Cooldown(APPROVAL_REQUEST_INTERVAL_SECONDS),
        access_notices=Cooldown(ACCESS_NOTICE_INTERVAL_SECONDS),
        albums=Albums(),
    )
    # Access first: the owner's /users and approval buttons must not reach the tools' catch-all handler.
    dispatcher.include_routers(build_access_router(), build_tools_router())
    for key, value in context.items():
        dispatcher[key] = value
    return dispatcher


def api_session(settings: Settings) -> AiohttpSession:
    """A session with Telegram's hosted Bot API, or with the bot's own server in local mode when it has one."""
    if settings.telegram_api_url is None:
        return AiohttpSession()
    # In local mode, the server answers `getFile` with a path on the volume the bot shares with it, read from there.
    server = TelegramAPIServer.from_base(str(settings.telegram_api_url), is_local=True)
    return AiohttpSession(api=server, timeout=LOCAL_REQUEST_TIMEOUT_SECONDS)


async def run(settings: Settings) -> None:
    engine = db.create_engine(settings.database_url.get_secret_value())
    await db.upgrade(engine)
    bot = Bot(
        settings.telegram_bot_token.get_secret_value(),
        session=api_session(settings),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(settings, sessionmaker=db.create_sessionmaker(engine))
    await prepare_bot(bot, settings)
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await engine.dispose()
    return None


def main() -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run(settings))
