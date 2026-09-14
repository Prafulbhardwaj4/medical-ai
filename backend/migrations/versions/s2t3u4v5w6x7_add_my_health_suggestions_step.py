"""add Suggestions step to my-health.html tutorial

The Suggestions button (openSuggestionModal()) existed on the page but
was never covered by the tutorial. Inserted as step 5 (before "Your
Profile", matching the Suggest-before-Profile order used on every staff
page's header steps), pushing Profile to step 6, on both devices.

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = 's2t3u4v5w6x7'
down_revision = 'r1s2t3u4v5w6'
branch_labels = None
depends_on = None

tutorial_steps_table = sa.table(
    'tutorial_steps',
    sa.column('id', sa.Integer),
    sa.column('page', sa.String),
    sa.column('device', sa.String),
    sa.column('step_order', sa.Integer),
    sa.column('target_selector', sa.String),
    sa.column('title', sa.String),
    sa.column('description', sa.Text),
    sa.column('placement', sa.String),
    sa.column('role', sa.String),
    sa.column('is_active', sa.Boolean),
)

NEW_STEPS = [
    {"page": "my-health", "device": "desktop", "step_order": 5,
     "target_selector": "#my-health-suggestions-btn", "title": "Suggestions",
     "description": "Have an idea to improve MedScribe? Send it here.",
     "placement": "bottom"},
    {"page": "my-health", "device": "mobile", "step_order": 5,
     "target_selector": "#my-health-suggestions-btn", "title": "Suggestions",
     "description": "Have an idea to improve MedScribe? Send it here.",
     "placement": "bottom"},
]


def upgrade():
    conn = op.get_bind()
    conn.execute(
        sa.update(tutorial_steps_table)
        .where(tutorial_steps_table.c.page == "my-health")
        .where(tutorial_steps_table.c.step_order == 5)
        .values(step_order=6)
    )
    op.bulk_insert(tutorial_steps_table, [{**s, "role": "patient", "is_active": True} for s in NEW_STEPS])


def downgrade():
    conn = op.get_bind()
    conn.execute(
        sa.delete(tutorial_steps_table)
        .where(tutorial_steps_table.c.page == "my-health")
        .where(tutorial_steps_table.c.target_selector == "#my-health-suggestions-btn")
    )
    conn.execute(
        sa.update(tutorial_steps_table)
        .where(tutorial_steps_table.c.page == "my-health")
        .where(tutorial_steps_table.c.step_order == 6)
        .values(step_order=5)
    )