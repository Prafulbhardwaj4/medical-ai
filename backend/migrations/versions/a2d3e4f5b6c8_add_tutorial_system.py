"""add tutorial_steps and tutorial_progress tables

Backend for the in-app guided-tutorial feature — role-based, per-page
step content plus per-account completion tracking. First rollout target
is the patient portal, then staff roles one at a time.

Revision ID: a2d3e4f5b6c8
Revises: a1b2c3d4e5f9
Create Date: 2026-08-28 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2d3e4f5b6c8'
down_revision = 'a1b2c3d4e5f9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = insp.get_table_names()

    if 'tutorial_steps' not in existing:
        op.create_table(
            'tutorial_steps',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('role', sa.String(), nullable=False, index=True),
            sa.Column('page', sa.String(), nullable=False),
            sa.Column('step_order', sa.Integer(), nullable=False),
            sa.Column('target_selector', sa.String(), nullable=False),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('placement', sa.String(), nullable=False, server_default='bottom'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        )

    if 'tutorial_progress' not in existing:
        op.create_table(
            'tutorial_progress',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('subject_type', sa.String(), nullable=False),
            sa.Column('subject_id', sa.Integer(), nullable=False),
            sa.Column('role', sa.String(), nullable=False),
            sa.Column('completed_at', sa.DateTime(), nullable=False),
        )
        op.create_index(
            'ix_tutorial_progress_subject_role',
            'tutorial_progress', ['subject_type', 'subject_id', 'role'],
            unique=True,
        )


def downgrade():
    op.drop_index('ix_tutorial_progress_subject_role', table_name='tutorial_progress')
    op.drop_table('tutorial_progress')
    op.drop_table('tutorial_steps')