"""add cross_booking_requests table and appointment requested_by_account_id"""
from alembic import op
import sqlalchemy as sa

revision = 'c7d8e9f0a1b2'
down_revision = 'b1c2d3e4f5a6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'cross_booking_requests' not in existing_tables:
        op.create_table(
            'cross_booking_requests',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('requesting_account_id', sa.Integer(), sa.ForeignKey('patient_accounts.id'), nullable=False),
            sa.Column('target_account_id', sa.Integer(), sa.ForeignKey('patient_accounts.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
            sa.Column('slot_id', sa.Integer(), sa.ForeignKey('doctor_slots.id'), nullable=True),
            sa.Column('type', sa.String(), nullable=False),
            sa.Column('notes', sa.String(), nullable=True),
            sa.Column('address', sa.String(), nullable=True),
            sa.Column('status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    appt_cols = {c['name'] for c in insp.get_columns('portal_appointments')}
    if 'requested_by_account_id' not in appt_cols:
        with op.batch_alter_table('portal_appointments') as batch_op:
            batch_op.add_column(sa.Column('requested_by_account_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_portal_appointments_requested_by_account_id', 'patient_accounts', ['requested_by_account_id'], ['id'])


def downgrade():
    with op.batch_alter_table('portal_appointments') as batch_op:
        batch_op.drop_constraint('fk_portal_appointments_requested_by_account_id', type_='foreignkey')
        batch_op.drop_column('requested_by_account_id')
    op.drop_table('cross_booking_requests')