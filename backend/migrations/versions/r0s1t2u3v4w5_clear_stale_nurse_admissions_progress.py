"""clear stale nurse-admissions tutorial progress

This is a one-off data fix, not a schema change: an earlier bug marked
role=nurse, page=nurse-admissions as "completed" in tutorial_progress
before any real steps existed for it, so it never auto-shows. Deleting
that row lets it show again on next login, same as if it had never run.

Revision ID: r0s1t2u3v4w5
Revises: q9r0s1t2u3v4
Create Date: 2026-09-22 00:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'r0s1t2u3v4w5'
down_revision: Union[str, Sequence[str], None] = 'q9r0s1t2u3v4'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("DELETE FROM tutorial_progress WHERE role = 'nurse' AND page = 'nurse-admissions'")

def downgrade() -> None:
    # Nothing meaningful to restore — this only ever deletes stale rows.
    pass