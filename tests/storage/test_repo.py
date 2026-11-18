import datetime as dt

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from tgmate.storage import repo
from tgmate.storage.models import User, UserStatus


async def test_new_user_starts_pending(session: AsyncSession) -> None:
    user = await repo.upsert_user(session, 5, full_name="Alice", username="alice")
    await session.commit()

    stored = await repo.get_user(session, 5)
    assert (stored.status, stored.full_name, stored.username) == (UserStatus.PENDING, "Alice", "alice")
    assert stored is user


async def test_upsert_refreshes_names_and_keeps_status(session: AsyncSession) -> None:
    user = await repo.upsert_user(session, 5, full_name="Alice", username="alice")
    user.status = UserStatus.APPROVED
    await session.commit()

    await repo.upsert_user(session, 5, full_name="Alice B.", username=None)
    await session.commit()

    stored = await repo.get_user(session, 5)
    assert (stored.status, stored.full_name, stored.username) == (UserStatus.APPROVED, "Alice B.", None)


async def test_unknown_user_is_none(session: AsyncSession) -> None:
    assert await repo.get_user(session, 404) is None


async def test_list_users_filters_by_status_pending_first_then_by_name(session: AsyncSession) -> None:
    session.add_all(
        [
            User(id=1, full_name="Zed", status=UserStatus.APPROVED),
            User(id=2, full_name="Bob", status=UserStatus.PENDING),
            User(id=3, full_name="Amy", status=UserStatus.APPROVED),
            User(id=4, full_name="Ann", status=UserStatus.REVOKED),
            User(id=5, full_name="Cid", status=UserStatus.REJECTED),
        ]
    )
    await session.commit()

    users = await repo.list_users(session, frozenset({UserStatus.PENDING, UserStatus.APPROVED, UserStatus.REJECTED}))

    assert [user.full_name for user in users] == ["Bob", "Amy", "Cid", "Zed"]


async def test_timestamps_are_aware_utc_and_naive_ones_are_refused(session: AsyncSession) -> None:
    await repo.upsert_user(session, 5, full_name="Alice", username=None)
    await session.commit()
    session.expire_all()

    stored = await repo.get_user(session, 5)
    assert stored.created_at.tzinfo is dt.UTC

    stored.created_at = dt.datetime(2026, 1, 1)
    with pytest.raises(sa.exc.StatementError, match="naive datetimes"):
        await session.commit()
