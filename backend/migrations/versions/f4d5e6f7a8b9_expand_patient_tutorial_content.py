"""expand patient portal tutorial with device-aware, fuller content

Replaces the original 3-step my-health.html-only seed with a real tour:
5 steps for my-health.html (desktop and mobile variants — sidebar/stacked
sections vs bottom-nav/hamburger, since those genuinely differ in what's
reachable without a click) plus 2 steps for my-appointments.html (same
on both devices — this page has no such split).

Revision ID: f4d5e6f7a8b9
Revises: f3c4d5e6f7a8
Create Date: 2026-08-29 00:00:01
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4d5e6f7a8b9'
down_revision = 'f3c4d5e6f7a8'

tutorial_steps_table = sa.table(
    'tutorial_steps',
    sa.column('role', sa.String),
    sa.column('page', sa.String),
    sa.column('step_order', sa.Integer),
    sa.column('target_selector', sa.String),
    sa.column('title', sa.String),
    sa.column('description', sa.Text),
    sa.column('placement', sa.String),
    sa.column('device', sa.String),
    sa.column('is_active', sa.Boolean),
)

STEPS = [
    # my-health.html — desktop
    {"page": "my-health", "device": "desktop", "step_order": 1,
     "target_selector": "#section-stats",
     "title": "Health Overview", "description": "A quick summary of your recent visits and health info lives here.",
     "placement": "top"},
    {"page": "my-health", "device": "desktop", "step_order": 2,
     "target_selector": "#section-admissions",
     "title": "Admission History", "description": "If you've ever been admitted at a hospital, your stay details show up here.",
     "placement": "top"},
    {"page": "my-health", "device": "desktop", "step_order": 3,
     "target_selector": "#section-records",
     "title": "Reports & Records", "description": "Your test reports and medical records land here as soon as they're ready.",
     "placement": "top"},
    {"page": "my-health", "device": "desktop", "step_order": 4,
     "target_selector": "a.nav-item[href='my-appointments.html']",
     "title": "Book an Appointment", "description": "Head here anytime to book a new appointment or check your upcoming ones.",
     "placement": "right"},
    {"page": "my-health", "device": "desktop", "step_order": 5,
     "target_selector": "[data-tutorial-id='my-health-profile-btn']",
     "title": "Your Profile", "description": "Update your password, saved address, or manage family profiles here. You can replay this tour anytime from this menu too.",
     "placement": "bottom"},

    # my-health.html — mobile
    {"page": "my-health", "device": "mobile", "step_order": 1,
     "target_selector": "#bn-stats",
     "title": "Home", "description": "Your health overview — recent visits and health info at a glance.",
     "placement": "top"},
    {"page": "my-health", "device": "mobile", "step_order": 2,
     "target_selector": "#bn-admissions",
     "title": "Admissions", "description": "If you've ever been admitted at a hospital, your stay details show up here.",
     "placement": "top"},
    {"page": "my-health", "device": "mobile", "step_order": 3,
     "target_selector": "#bn-records",
     "title": "Records", "description": "Your test reports and medical records land here as soon as they're ready.",
     "placement": "top"},
    {"page": "my-health", "device": "mobile", "step_order": 4,
     "target_selector": "#hamburger-btn",
     "title": "Menu", "description": "Tap here to open the menu — this is where you'll find Book Appointment.",
     "placement": "bottom"},
    {"page": "my-health", "device": "mobile", "step_order": 5,
     "target_selector": "[data-tutorial-id='my-health-profile-btn']",
     "title": "Your Profile", "description": "Update your password, saved address, or manage family profiles here. You can replay this tour anytime from this menu too.",
     "placement": "bottom"},

    # my-appointments.html — both devices, identical (no layout split on this page)
    {"page": "my-appointments", "device": "both", "step_order": 1,
     "target_selector": "[data-tutorial-id='my-appointments-wizard-card']",
     "title": "Book a New Appointment", "description": "Follow these steps — pick your state and city, choose a hospital and doctor, then a time that works for you.",
     "placement": "bottom"},
    {"page": "my-appointments", "device": "both", "step_order": 2,
     "target_selector": "[data-tutorial-id='my-appointments-list-btn']",
     "title": "My Appointments", "description": "See all your booked appointments, past and upcoming, here.",
     "placement": "left"},
]

def upgrade():
    conn = op.get_bind()
    # Clean slate for patient tutorial content — the original 3-row seed
    # (from the earlier migration) didn't account for mobile/desktop at
    # all and is being fully superseded by this set, not appended to.
    conn.execute(sa.text("DELETE FROM tutorial_steps WHERE role='patient'"))
    op.bulk_insert(tutorial_steps_table, [{**s, "role": "patient", "is_active": True} for s in STEPS])


def downgrade():
    op.execute("DELETE FROM tutorial_steps WHERE role='patient'")