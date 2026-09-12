"""merge heads — must_change_password branch + plan_inquiries branch + tutorial branch

Three heads existed before this: a1c2d3e4f5g6 (must_change_password,
branched off a1b2c3d4e5f6) and k4l5m6n7o8p9 (plan_inquiries, branched
off z5e6f7a8b9c0) both branched off older ancestors instead of the
actual current head at the time (g1h2i3j4k5l6) — confirmed via
`alembic heads` returning all three. This merges them back into one.

Revision ID: m5n6o7p8q9r0
Revises: a1c2d3e4f5g6, g1h2i3j4k5l6, k4l5m6n7o8p9
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'm5n6o7p8q9r0'
down_revision: Union[str, Sequence[str], None] = ('a1c2d3e4f5g6', 'g1h2i3j4k5l6', 'k4l5m6n7o8p9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass