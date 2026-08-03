"""add appointment no-show detection and reschedule-request fields"""
from alembic import op
import sqlalchemy as sa

revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('portal_appointments')}

    if 'no_show_detected_at' not in existing_cols:
        op.add_column('portal_appointments', sa.Column('no_show_detected_at', sa.DateTime(), nullable=True))
    if 'no_show_reason' not in existing_cols:
        op.add_column('portal_appointments', sa.Column('no_show_reason', sa.String(), nullable=True))
    if 'no_show_reschedule_deadline' not in existing_cols:
        op.add_column('portal_appointments', sa.Column('no_show_reschedule_deadline', sa.DateTime(), nullable=True))
    if 'reschedule_kind' not in existing_cols:
        op.add_column('portal_appointments', sa.Column('reschedule_kind', sa.String(), nullable=True))
    if 'requested_reschedule_slot_id' not in existing_cols:
        with op.batch_alter_table('portal_appointments') as batch_op:
            batch_op.add_column(sa.Column('requested_reschedule_slot_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_portal_appointments_requested_reschedule_slot_id', 'doctor_slots', ['requested_reschedule_slot_id'], ['id'])


def downgrade():
    with op.batch_alter_table('portal_appointments') as batch_op:
        batch_op.drop_constraint('fk_portal_appointments_requested_reschedule_slot_id', type_='foreignkey')
        batch_op.drop_column('requested_reschedule_slot_id')
    op.drop_column('portal_appointments', 'reschedule_kind')
    op.drop_column('portal_appointments', 'no_show_reschedule_deadline')
    op.drop_column('portal_appointments', 'no_show_reason')
    op.drop_column('portal_appointments', 'no_show_detected_at')