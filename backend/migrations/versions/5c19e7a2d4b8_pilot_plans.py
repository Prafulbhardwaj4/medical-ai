"""pilot_plans: Pilot 1 / Pilot 2 columns on hospitals (additive, nullable). hospitals.tier is a plain string, so no enum change is needed."""
from alembic import op
import sqlalchemy as sa

revision = '5c19e7a2d4b8'
down_revision = 'b8d3a51c7e20'  # staff_reset_codes (the single current head)


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('hospitals')}
    if 'pilot_start_date' not in cols:
        op.add_column('hospitals', sa.Column('pilot_start_date', sa.Date(), nullable=True))
    if 'pilot_end_date' not in cols:
        op.add_column('hospitals', sa.Column('pilot_end_date', sa.Date(), nullable=True))
    if 'pilot_weekly_cap' not in cols:
        op.add_column('hospitals', sa.Column('pilot_weekly_cap', sa.Integer(), nullable=True))
    if 'pilot_result_note' not in cols:
        op.add_column('hospitals', sa.Column('pilot_result_note', sa.String(length=300), nullable=True))


def downgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('hospitals')}
    for name in ('pilot_result_note', 'pilot_weekly_cap', 'pilot_end_date', 'pilot_start_date'):
        if name in cols:
            op.drop_column('hospitals', name)