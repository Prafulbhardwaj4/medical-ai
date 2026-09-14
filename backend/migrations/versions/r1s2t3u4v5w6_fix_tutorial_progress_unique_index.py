"""fix tutorial_progress unique index to include page

The original index (ix_tutorial_progress_subject_role) only covered
(subject_type, subject_id, role) — from before the page column existed
(added in n6o7p8q9r0s1). That meant only the FIRST tab/page's completion
row could ever be inserted per role; every other page's completion
insert silently failed on the unique constraint (the frontend's
.catch(()=>{}) swallows it), which is why any role with more than one
tutorial page (nurse: nurse-home + nurse-admissions, doctor: dashboard +
doctor-admissions, etc.) can only ever fully complete one of them.

This migration existed before under revision id p8q9r0s1t2u3, but that
id got reused by a later, unrelated migration (add_tutorial_guard_message)
during a duplicate-ID cleanup, and this one was deleted instead of the
other one being renamed. Re-adding it here, chained after the current
head, with a fresh id.

Revision ID: r1s2t3u4v5w6
Revises: p8q9r0s1t2u3
Create Date: 2026-09-14
"""
from alembic import op

revision = 'r1s2t3u4v5w6'
down_revision = 'p8q9r0s1t2u3'
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