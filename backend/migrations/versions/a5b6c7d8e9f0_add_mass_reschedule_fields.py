"""add mass-reschedule trigger tracking and per-appointment notice flag"""
from alembic import op
import sqlalchemy as sa

revision = 'f19b18719567'
down_revision = 'f4a5b6c7d8e9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    unavail_cols = {c['name'] for c in insp.get_columns('doctor_unavailability')}
    if 'mass_reschedule_triggered_at' not in unavail_cols:
        op.add_column('doctor_unavailability', sa.Column('mass_reschedule_triggered_at', sa.DateTime(), nullable=True))
    if 'mass_reschedule_triggered_by' not in unavail_cols:
        with op.batch_alter_table('doctor_unavailability') as batch_op:
            batch_op.add_column(sa.Column('mass_reschedule_triggered_by', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_doctor_unavailability_triggered_by', 'doctors', ['mass_reschedule_triggered_by'], ['id'])

    appt_cols = {c['name'] for c in insp.get_columns('portal_appointments')}
    if 'mass_reschedule_notice' not in appt_cols:
        op.add_column('portal_appointments', sa.Column('mass_reschedule_notice', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('portal_appointments', 'mass_reschedule_notice')
    with op.batch_alter_table('doctor_unavailability') as batch_op:
        batch_op.drop_constraint('fk_doctor_unavailability_triggered_by', type_='foreignkey')
        batch_op.drop_column('mass_reschedule_triggered_by')
    op.drop_column('doctor_unavailability', 'mass_reschedule_triggered_at')