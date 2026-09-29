"""add hospital.contact_numbers and hospital.emails — structured multi-value
contact info (typed mobile/landline numbers, multiple emails), replacing the
old single `phone` string field for admin-editable purposes. `phone` column
is kept as-is for backward compatibility but is no longer edited from the UI."""
from alembic import op
import sqlalchemy as sa

revision = 'ce77303f5000'
down_revision = 'z9a1b2c3d4e5'  # add_checkin_doctor_room — adjust to your real current head (`alembic heads`) before running
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('hospitals')}
    if 'contact_numbers' not in cols:
        op.add_column('hospitals', sa.Column('contact_numbers', sa.Text(), nullable=True))
    if 'emails' not in cols:
        op.add_column('hospitals', sa.Column('emails', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('hospitals', 'emails')
    op.drop_column('hospitals', 'contact_numbers')