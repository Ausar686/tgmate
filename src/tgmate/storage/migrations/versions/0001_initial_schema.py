"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-18 23:49:28.046498
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import tgmate.storage.models

revision: str = '0001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('full_name', sa.String(), nullable=False),
    sa.Column('username', sa.String(), nullable=True),
    sa.Column('status', sa.Enum('pending', 'approved', 'rejected', 'revoked', name='userstatus', native_enum=False, length=32), nullable=False),
    sa.Column('created_at', tgmate.storage.models.UTCDateTime(), nullable=False),
    sa.Column('updated_at', tgmate.storage.models.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )


def downgrade() -> None:
    op.drop_table('users')
