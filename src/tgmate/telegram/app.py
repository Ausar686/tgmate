"""Wires settings, storage and the Telegram dispatcher together; run with `python -m tgmate.telegram`."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from tgmate.config import Settings
from tgmate.storage import db
from tgmate.telegram.access import (
    ACCESS_NOTICE_INTERVAL_SECONDS,
    APPROVAL_REQUEST_INTERVAL_SECONDS,
    build_access_router,
)
from tgmate.telegram.cooldown import Cooldown
from tgmate.telegram.setup import prepare_bot
from tgmate.telegram.tools import build_tools_router


def build_dispatcher(**context: object) -> Dispatcher:
    dispatcher = Dispatcher(
        approval_requests=Cooldown(APPROVAL_REQUEST_INTERVAL_SECONDS),
        access_notices=Cooldown(ACCESS_NOTICE_INTERVAL_SECONDS),
    )
    # Access first: the owner's /users and approval buttons must not reach the tools' catch-all handler.
    dispatcher.include_routers(build_access_router(), build_tools_router())
    for key, value in context.items():
        dispatcher[key] = value
    return dispatcher


async def run(settings: Settings) -> None:
    engine = db.create_engine(settings.database_url.get_secret_value())
    await db.upgrade(engine)
    bot = Bot(settings.telegram_bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = build_dispatcher(sessionmaker=db.create_sessionmaker(engine), settings=settings)
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
