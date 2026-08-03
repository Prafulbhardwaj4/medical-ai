"""add_blacklisted_tokens_table

Revision ID: 415ec200f5c0
Revises: c3d4e5f6a7b8
Create Date: 2026-06-29 16:47:27.654229

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '415ec200f5c0'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    """Raw catalog query — bypasses SQLAlchemy's Inspector reflection
    cache, which can report a table as missing mid-run even after it was
    already committed (e.g. by Base.metadata.create_all() on a prior
    deploy, before migrations were ever run against this database)."""
    if bind.dialect.name == 'postgresql':
        row = bind.execute(sa.text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = :t"
        ), {"t": table_name}).first()
    else:
        row = bind.execute(sa.text(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :t"
        ), {"t": table_name}).first()
    return row is not None


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    if bind.dialect.name == 'postgresql':
        row = bind.execute(sa.text(
            "SELECT 1 FROM pg_indexes WHERE tablename = :t AND indexname = :i"
        ), {"t": table_name, "i": index_name}).first()
    else:
        row = bind.execute(sa.text(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :i"
        ), {"i": index_name}).first()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, 'blacklisted_tokens'):
        op.create_table('blacklisted_tokens',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('token', sa.String(), nullable=False),
            sa.Column('blacklisted_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )

    if not _index_exists(bind, 'blacklisted_tokens', op.f('ix_blacklisted_tokens_id')):
        op.create_index(op.f('ix_blacklisted_tokens_id'), 'blacklisted_tokens', ['id'], unique=False)
    if not _index_exists(bind, 'blacklisted_tokens', op.f('ix_blacklisted_tokens_token')):
        op.create_index(op.f('ix_blacklisted_tokens_token'), 'blacklisted_tokens', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_blacklisted_tokens_token'), table_name='blacklisted_tokens')
    op.drop_index(op.f('ix_blacklisted_tokens_id'), table_name='blacklisted_tokens')
    op.drop_table('blacklisted_tokens')