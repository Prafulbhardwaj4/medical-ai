"""fix tutorial_progress unique index to include page

The original index (ix_tutorial_progress_subject_role) only covered
(subject_type, subject_id, role) — from before the page column existed
(added later in n6o7p8q9r0s1). That meant only the FIRST tab's
completion row could ever be inserted per role; every other tab's
completion insert silently failed on the unique constraint (the
frontend's .catch(()=>{}) swallowed it), which is why non-Home tabs
kept re-showing their tutorial on every visit while whichever tab
happened to complete first appeared fine.

Revision ID: p8q9r0s1t2u3
Revises: o7p8q9r0s1t2
Create Date: 2026-09-12
"""
from alembic import op

revision = 'p8q9r0s1t2u3'
down_revision = 'o7p8q9r0s1t2'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index('ix_tutorial_progress_subject_role', table_name='tutorial_progress')
    op.create_index(
        'ix_tutorial_progress_subject_role_page',
        'tutorial_progress', ['subject_type', 'subject_id', 'role', 'page'],
        unique=True,
    )


def downgrade():
    op.drop_index('ix_tutorial_progress_subject_role_page', table_name='tutorial_progress')
    op.create_index(
        'ix_tutorial_progress_subject_role',
        'tutorial_progress', ['subject_type', 'subject_id', 'role'],
        unique=True,
    )