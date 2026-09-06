"""fix patient tutorial step ordering, placement, and wording

f4d5e6f7a8b9 already ran against the DB by the time these corrections were
written, so editing that file's STEPS list no longer has any effect —
Alembic doesn't re-diff or re-run a migration once it's recorded as
applied. This migration UPDATEs the rows it already inserted instead.

Revision ID: g1h2i3j4k5l6
Revises: f4d5e6f7a8b9
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'g1h2i3j4k5l6'
down_revision = 'f4d5e6f7a8b9'  # <-- confirm this matches `alembic heads` in
                                #     your environment before running; this
                                #     repo has had multiple unmerged heads
                                #     elsewhere, so double-check rather than
                                #     assume.
branch_labels = None
depends_on = None

tutorial_steps = sa.table(
    'tutorial_steps',
    sa.column('page', sa.String),
    sa.column('device', sa.String),
    sa.column('target_selector', sa.String),
    sa.column('step_order', sa.Integer),
    sa.column('title', sa.String),
    sa.column('description', sa.String),
    sa.column('placement', sa.String),
)

# Each row identified by (page, device, target_selector) — stable even
# though step_order/title/placement are exactly what's changing here.
UPDATES = [
    {"page": "my-health", "device": "desktop", "target_selector": "#section-stats",
     "step_order": 1, "title": "Health Overview",
     "description": "A quick summary of your recent visits and health info lives here.",
     "placement": "bottom"},
    {"page": "my-health", "device": "desktop", "target_selector": "#section-admissions",
     "step_order": 2, "title": "Admitted",
     "description": "If you're currently admitted at a hospital, your stay details show up here.",
     "placement": "top"},
    {"page": "my-health", "device": "desktop", "target_selector": "#section-records",
     "step_order": 3, "title": "Reports & Records",
     "description": "Your test reports and medical records land here as soon as they're ready.",
     "placement": "top"},
    {"page": "my-health", "device": "desktop", "target_selector": "a.nav-item[href='my-appointments.html']",
     "step_order": 4, "title": "Book an Appointment",
     "description": "Head here anytime to book a new appointment or check your upcoming ones.",
     "placement": "right"},
    {"page": "my-health", "device": "desktop", "target_selector": "[data-tutorial-id='my-health-profile-btn']",
     "step_order": 5, "title": "Your Profile",
     "description": "Update your password, saved address, or manage family profiles here. You can replay this tour anytime from this menu too.",
     "placement": "bottom"},

    {"page": "my-health", "device": "mobile", "target_selector": "#bn-stats",
     "step_order": 1, "title": "Home",
     "description": "Your health overview — recent visits and health info at a glance.",
     "placement": "top"},
    {"page": "my-health", "device": "mobile", "target_selector": "#bn-admissions",
     "step_order": 2, "title": "Admitted",
     "description": "If you're currently admitted at a hospital, your stay details show up here.",
     "placement": "top"},
    {"page": "my-health", "device": "mobile", "target_selector": "#bn-records",
     "step_order": 3, "title": "Records",
     "description": "Your test reports and medical records land here as soon as they're ready.",
     "placement": "top"},
    {"page": "my-health", "device": "mobile", "target_selector": "#bn-appointments",
     "step_order": 4, "title": "Appointments",
     "description": "Head here anytime to book a new appointment or check your upcoming ones.",
     "placement": "top"},
    {"page": "my-health", "device": "mobile", "target_selector": "[data-tutorial-id='my-health-profile-btn']",
     "step_order": 5, "title": "Your Profile",
     "description": "Update your password, saved address, or manage family profiles here. You can replay this tour anytime from this menu too.",
     "placement": "bottom"},

    {"page": "my-appointments", "device": "both", "target_selector": "[data-tutorial-id='my-appointments-wizard-card']",
     "step_order": 1, "title": "Book a New Appointment",
     "description": "Follow these steps — pick your state and city, choose a hospital and doctor, then a time that works for you.",
     "placement": "bottom"},
    {"page": "my-appointments", "device": "both", "target_selector": "[data-tutorial-id='my-appointments-list-btn']",
     "step_order": 2, "title": "My Appointments",
     "description": "See all your booked appointments, past and upcoming, here.",
     "placement": "left"},
]

# This page previously had a 3rd step (the profile button) that's been
# removed from scope entirely — deactivate it rather than deleting the row,
# consistent with is_active already being how this table soft-disables rows.
REMOVE = [
    {"page": "my-appointments", "device": "both", "target_selector": "[data-tutorial-id='my-appointments-profile-btn']"},
]


def upgrade() -> None:
    for row in UPDATES:
        op.execute(
            tutorial_steps.update()
            .where(
                (tutorial_steps.c.page == row["page"]) &
                (tutorial_steps.c.device == row["device"]) &
                (tutorial_steps.c.target_selector == row["target_selector"])
            )
            .values(
                step_order=row["step_order"],
                title=row["title"],
                description=row["description"],
                placement=row["placement"],
            )
        )
    for row in REMOVE:
        op.execute(
            sa.text(
                "UPDATE tutorial_steps SET is_active = false "
                "WHERE page = :page AND device = :device AND target_selector = :target_selector"
            ).bindparams(page=row["page"], device=row["device"], target_selector=row["target_selector"])
        )


def downgrade() -> None:
    pass  # one-way content fix — not worth reconstructing the pre-fix wording/order