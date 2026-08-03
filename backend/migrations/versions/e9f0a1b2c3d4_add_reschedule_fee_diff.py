"""add reschedule fee difference tracking"""
from alembic import op
import sqlalchemy as sa

revision = '7c2d0042d434'
down_revision = 'b1c2d3e4f5a6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'portal_appointments' not in insp.get_table_names():
        op.create_table(
            'portal_appointments',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('patient_accounts.id'), nullable=False),
            sa.Column('profile_link_id', sa.Integer(), sa.ForeignKey('patient_profile_links.id'), nullable=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
            sa.Column('slot_id', sa.Integer(), sa.ForeignKey('doctor_slots.id'), nullable=True),
            sa.Column('type', sa.Enum('scheduled', 'queue_home', name='appointmenttype'), nullable=False),
            sa.Column('requested_time', sa.DateTime(), nullable=False),
            sa.Column('status', sa.Enum('booked', 'confirmed', 'completed', 'cancelled', 'no_show', name='appointmentstatus'), server_default='booked'),
            sa.Column('payment_status', sa.String(), nullable=False, server_default='unpaid'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        insp = sa.inspect(bind)

    appt_cols = {c['name'] for c in insp.get_columns('portal_appointments')}
    if 'reschedule_balance_due' not in appt_cols:
        op.add_column('portal_appointments', sa.Column('reschedule_balance_due', sa.Float(), nullable=True))

    with op.batch_alter_table('opd_charges') as batch_op:
        batch_op.alter_column('added_by', existing_type=sa.Integer(), nullable=True)


def downgrade():
    with op.batch_alter_table('opd_charges') as batch_op:
        batch_op.alter_column('added_by', existing_type=sa.Integer(), nullable=False)
    op.drop_column('portal_appointments', 'reschedule_balance_due')