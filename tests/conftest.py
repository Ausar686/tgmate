import collections.abc as cabc
import pathlib

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tgmate.config import Settings
from tgmate.storage import db

OWNER = 1


@pytest.fixture
def database_url(tmp_path: pathlib.Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
async def engine(database_url: str) -> cabc.AsyncIterator[AsyncEngine]:
    engine = db.create_engine(database_url)
    await db.upgrade(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> cabc.AsyncIterator[AsyncSession]:
    async with db.create_sessionmaker(engine)() as session:
        yield session


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(_env_file=None, telegram_bot_token="42:TEST", owner_user_id=OWNER, database_url=database_url)
