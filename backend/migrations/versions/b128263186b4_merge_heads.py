"""merge heads — unifies the 23 branches that were falsely sharing revision
IDs across independent sessions (see accompanying rename fixes) back into
one single history. No schema changes; this is purely a graph merge.

Revision ID: b128263186b4
Revises: 07b5bcd756e9, 27dac3076779, 2b9b79bb37d4, 31fb003c8af6, 3cd6611fc018,
         46a48b1b6e2d, 626a6c608e4b, 70ac349e07ae, 75d1626a5fd7, 7c2d0042d434,
         801b4d923931, 84a7a8931b0b, 87df4bd15204, 953c74719cb5, 992110a8d25b,
         9afe2b904daa, a813d4e7fd7b, adf570d83e19, cf1068f09aaa, d9bfb9f357dd,
         dc0af7f256d8, f19b18719567, f7c96b82813c
Create Date: 2026-08-02 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'b128263186b4'
down_revision = (
    '07b5bcd756e9', '27dac3076779', '2b9b79bb37d4', '31fb003c8af6', '3cd6611fc018',
    '46a48b1b6e2d', '626a6c608e4b', '70ac349e07ae', '75d1626a5fd7', '7c2d0042d434',
    '801b4d923931', '84a7a8931b0b', '87df4bd15204', '953c74719cb5', '992110a8d25b',
    '9afe2b904daa', 'a813d4e7fd7b', 'adf570d83e19', 'cf1068f09aaa', 'd9bfb9f357dd',
    'dc0af7f256d8', 'f19b18719567', 'f7c96b82813c', '0957a2f94adb',
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass