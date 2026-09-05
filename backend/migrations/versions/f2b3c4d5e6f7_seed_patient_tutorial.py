"""seed initial patient portal tutorial content

Real, testable step content for my-health.html — the first page in the
first role's tutorial. Pure data migration, no schema change. Adding a
new role/page later is just another migration like this one (or an
admin-authored insert, once/if a content-editing UI exists) — never a
code change to tutorial.py or tutorial.js.

Revision ID: f2b3c4d5e6f7
Revises: a2d3e4f5b6c8
Create Date: 2026-08-28 00:00:01
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

revision = 'f2b3c4d5e6f7'
down_revision = 'a2d3e4f5b6c8'

tutorial_steps_table = sa.table(
    'tutorial_steps',
    sa.column('role', sa.String),
    sa.column('page', sa.String),
    sa.column('step_order', sa.Integer),
    sa.column('target_selector', sa.String),
    sa.column('title', sa.String),
    sa.column('description', sa.Text),
    sa.column('placement', sa.String),
    sa.column('is_active', sa.Boolean),
)

STEPS = [
    {
        "role": "patient", "page": "my-health", "step_order": 1,
        "target_selector": "[data-tutorial-id='my-health-appointments-nav']",
        "title": "Your Appointments",
        "description": "Book a new appointment or check your upcoming ones here.",
        "placement": "right",
    },
    {
        "role": "patient", "page": "my-health", "step_order": 2,
        "target_selector": "[data-tutorial-id='my-health-records-nav']",
        "title": "Records",
        "description": "Your admission history and past visit records live here.",
        "placement": "top",
    },
    {
        "role": "patient", "page": "my-health", "step_order": 3,
        "target_selector": "[data-tutorial-id='my-health-profile-btn']",
        "title": "Your Profile",
        "description": "Update your address, change your password, or manage linked family profiles from here. You can replay this tutorial anytime from this menu too.",
        "placement": "bottom",
    },
]


def upgrade():
    conn = op.get_bind()
    existing = conn.execute(sa.text("SELECT COUNT(*) FROM tutorial_steps WHERE role='patient' AND page='my-health'")).scalar()
    if existing:
        return  # already seeded — don't duplicate on a re-run
    op.bulk_insert(tutorial_steps_table, [{**s, "is_active": True} for s in STEPS])


def downgrade():
    op.execute("DELETE FROM tutorial_steps WHERE role='patient' AND page='my-health'")