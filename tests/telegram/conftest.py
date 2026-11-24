import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.telegram.fake_api import FakeTelegram
from tgmate.config import Settings
from tgmate.storage import db
from tgmate.storage.models import User, UserStatus
from tgmate.telegram.app import build_dispatcher


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return db.create_sessionmaker(engine)


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def bot(telegram: FakeTelegram) -> Bot:
    return Bot("42:TEST", session=telegram, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


@pytest.fixture
def dispatcher(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> Dispatcher:
    return build_dispatcher(settings, sessionmaker=sessionmaker)


async def seed_user(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: int,
    status: UserStatus,
    full_name: str = "Alice",
    username: str | None = "alice",
) -> None:
    async with sessionmaker() as session:
        session.add(User(id=user_id, full_name=full_name, username=username, status=status))
        await session.commit()


async def user_status(sessionmaker: async_sessionmaker[AsyncSession], user_id: int) -> UserStatus | None:
    async with sessionmaker() as session:
        user = await session.get(User, user_id)
        return None if user is None else user.status
