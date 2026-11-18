import collections.abc as cabc
import pathlib

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tgmate.config import Settings
from tgmate.storage import db
from tgmate.tools import sandbox, worker

OWNER = 1


@pytest.fixture(autouse=True)
def in_process_sandbox(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run sandboxed tool operations through the worker's request handling, but in the test's own process.

    Starting a process per conversion would slow the suite and hide the operations from coverage; the process itself
    is tested in `tests/tools/test_sandbox.py`, marked `real_sandbox`.
    """
    if request.node.get_closest_marker("real_sandbox") is None:
        monkeypatch.setattr(sandbox, "_execute", worker.handle)


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
