"""Query helpers over the ORM schema; callers own the session and commit."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from tgmate.storage.models import User, UserStatus


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def upsert_user(session: AsyncSession, user_id: int, *, full_name: str, username: str | None) -> User:
    """Refresh the user's names; a new user starts PENDING, an existing one keeps their status."""
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, status=UserStatus.PENDING)
        session.add(user)
    user.full_name = full_name
    user.username = username
    await session.flush()
    return user


async def list_users(session: AsyncSession, statuses: frozenset[UserStatus]) -> list[User]:
    """Users with one of `statuses`, pending first, then by name."""
    order = sa.case({UserStatus.PENDING: 0}, value=User.status, else_=1)
    query = sa.select(User).where(User.status.in_(statuses)).order_by(order, User.full_name, User.id)
    return list(await session.scalars(query))
