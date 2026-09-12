"""add page column to tutorial_progress — completion is now tracked
per (subject, role, page) instead of per (subject, role), so each tab
gets its own "seen it" flag instead of one flag for the whole role.

Revision ID: n6o7p8q9r0s1
Revises: m5n6o7p8q9r0
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'n6o7p8q9r0s1'
down_revision = 'm5n6o7p8q9r0'
branch_labels = None
depends_on = None


def upgrade():
    # nullable=True, no backfill: existing rows (lab/pharmacy/nurse/assistant
    # completions, all whole-role, pre-dating this change) just keep
    # page=NULL. They stop being read once the router below always filters
    # by a real page value — harmless leftover rows, not touched.
    op.add_column('tutorial_progress', sa.Column('page', sa.String(), nullable=True))


def downgrade():
    op.drop_column('tutorial_progress', 'page')