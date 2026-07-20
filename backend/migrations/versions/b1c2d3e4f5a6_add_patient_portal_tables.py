"""add patient portal tables (accounts, profile links, invites, otp, doctor slots, appointments)"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a6'
down_revision = 'a9b8c7d6e5f4'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'patient_accounts' not in existing_tables:
        op.create_table(
            'patient_accounts',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('phone', sa.String(), nullable=False),
            sa.Column('email', sa.String(), nullable=True),
            sa.Column('password_hash', sa.String(), nullable=False),
            sa.Column('is_active', sa.Boolean(), server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_patient_accounts_phone', 'patient_accounts', ['phone'], unique=True)
        op.create_index('ix_patient_accounts_email', 'patient_accounts', ['email'], unique=True)

    if 'patient_profile_links' not in existing_tables:
        op.create_table(
            'patient_profile_links',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('patient_accounts.id'), nullable=False),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
            sa.Column('relation', sa.String(), nullable=False, server_default='self'),
            sa.Column('linked_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('patient_id', name='uq_profile_link_patient'),
        )

    if 'portal_invite_status' not in existing_tables:
        op.create_table(
            'portal_invite_status',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('phone', sa.String(), nullable=False),
            sa.Column('invited', sa.Boolean(), server_default=sa.false()),
            sa.Column('invited_at', sa.DateTime(), nullable=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=True),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=True),
        )
        op.create_index('ix_portal_invite_status_phone', 'portal_invite_status', ['phone'], unique=True)

    if 'portal_otp_codes' not in existing_tables:
        op.create_table(
            'portal_otp_codes',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('phone', sa.String(), nullable=False),
            sa.Column('code_hash', sa.String(), nullable=False),
            sa.Column('purpose', sa.String(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('consumed', sa.Boolean(), server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_portal_otp_codes_phone', 'portal_otp_codes', ['phone'])

    if 'doctor_slots' not in existing_tables:
        op.create_table(
            'doctor_slots',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('slot_date', sa.Date(), nullable=False),
            sa.Column('slot_time', sa.String(), nullable=False),
            sa.Column('period', sa.String(), nullable=False),
            sa.Column('capacity', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('booked_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('doctor_id', 'slot_date', 'slot_time', name='uq_doctor_slot'),
        )
        op.create_index('ix_doctor_slots_slot_date', 'doctor_slots', ['slot_date'])

    if 'portal_appointments' not in existing_tables:
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
    else:
        # Table exists from a partial earlier deploy — make sure the newer columns are there.
        existing_cols = {c['name'] for c in insp.get_columns('portal_appointments')}
        if 'slot_id' not in existing_cols:
            op.add_column('portal_appointments', sa.Column('slot_id', sa.Integer(), sa.ForeignKey('doctor_slots.id'), nullable=True))
        if 'payment_status' not in existing_cols:
            op.add_column('portal_appointments', sa.Column('payment_status', sa.String(), nullable=False, server_default='unpaid'))


def downgrade():
    op.drop_table('portal_appointments')
    op.drop_table('doctor_slots')
    op.drop_table('portal_otp_codes')
    op.drop_table('portal_invite_status')
    op.drop_table('patient_profile_links')
    op.drop_table('patient_accounts')