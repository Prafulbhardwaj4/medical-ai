"""add device column to tutorial_steps

Desktop and mobile layouts differ enough (sidebar vs bottom-nav, stacked
sections vs tabbed sections) that a step's target element often only
exists or is only visible on one of the two — this lets each step declare
which device(s) it applies to, filtered client-side in tutorial.js against
window.innerWidth (same 900px breakpoint already used everywhere else in
the app's CSS).

Revision ID: f3c4d5e6f7a8
Revises: f2b3c4d5e6f7
Create Date: 2026-08-29 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3c4d5e6f7a8'
down_revision = 'f2b3c4d5e6f7'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('tutorial_steps')}
    if 'device' not in cols:
        with op.batch_alter_table('tutorial_steps') as batch_op:
            batch_op.add_column(sa.Column('device', sa.String(), nullable=False, server_default='both'))


def downgrade():
    with op.batch_alter_table('tutorial_steps') as batch_op:
        batch_op.drop_column('device')