"""ORM schema; the table contracts are documented in this package's README."""

import datetime as dt
import enum
import typing as t

import sqlalchemy as sa
from sqlalchemy import orm


class UserStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class UTCDateTime(sa.TypeDecorator[dt.datetime]):
    """Stores naive UTC and returns aware UTC, since SQLite drops tzinfo."""

    impl = sa.DateTime
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect: sa.Dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are ambiguous; pass an aware datetime")
        return value.astimezone(dt.UTC).replace(tzinfo=None)

    def process_result_value(self, value: dt.datetime | None, dialect: sa.Dialect) -> dt.datetime | None:
        return None if value is None else value.replace(tzinfo=dt.UTC)


def _str_enum(cls: type[enum.StrEnum]) -> sa.Enum:
    return sa.Enum(cls, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e])


class Base(orm.DeclarativeBase):
    metadata = sa.MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map: t.ClassVar = {
        dt.datetime: UTCDateTime(),
        UserStatus: _str_enum(UserStatus),
    }


class Timestamped:
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(default=utcnow)
    updated_at: orm.Mapped[dt.datetime] = orm.mapped_column(default=utcnow, onupdate=utcnow)


class User(Timestamped, Base):
    __tablename__ = "users"

    id: orm.Mapped[int] = orm.mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    full_name: orm.Mapped[str]
    username: orm.Mapped[str | None]
    status: orm.Mapped[UserStatus] = orm.mapped_column(default=UserStatus.PENDING)
