"""merge heads: visit_group_id/multi-doctor-visit branch + emergency-fields/custom-windows branch

These two branches were built on top of different "current heads" and never
merged, leaving `alembic upgrade head` ambiguous (2 heads) — almost certainly
why production has been missing whichever branch's columns didn't get
applied, causing 500s on any endpoint touching Checkin or
DoctorAvailabilityTemplate (checkin.visit_group_id, checkin.emergency_reason,
checkin.emergency_destination, doctor_availability_templates.custom_windows).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b797251c9c71'
down_revision = ('f2a3b4c5d6e7', 'z0f1a2b3c4d5')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass