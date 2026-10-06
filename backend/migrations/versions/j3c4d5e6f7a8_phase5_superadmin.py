"""phase 5: lead/upgrade follow-up fields, super admin alert-seen table, TOTP 2FA columns"""
from alembic import op
import sqlalchemy as sa

revision = 'j3c4d5e6f7a8'
down_revision = 'i2b3c4d5e6f7'  # run `alembic heads` first; it must show exactly one head


def _cols(insp, table):
    return {c['name'] for c in insp.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table in ('hospital_leads', 'upgrade_requests'):
        c = _cols(insp, table)
        if 'follow_up_notes' not in c:
            op.add_column(table, sa.Column('follow_up_notes', sa.Text(), nullable=True))
        if 'owner' not in c:
            op.add_column(table, sa.Column('owner', sa.String(), nullable=True))
        if 'next_follow_up_at' not in c:
            op.add_column(table, sa.Column('next_follow_up_at', sa.DateTime(), nullable=True))
        if 'contacted_at' not in c:
            op.add_column(table, sa.Column('contacted_at', sa.DateTime(), nullable=True))

    if 'converted_hospital_id' not in _cols(insp, 'hospital_leads'):
        op.add_column('hospital_leads', sa.Column('converted_hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=True))

    d = _cols(insp, 'doctors')
    if 'totp_secret_enc' not in d:
        op.add_column('doctors', sa.Column('totp_secret_enc', sa.String(), nullable=True))
    if 'totp_enabled' not in d:
        op.add_column('doctors', sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'totp_backup_codes' not in d:
        op.add_column('doctors', sa.Column('totp_backup_codes', sa.Text(), nullable=True))
    if 'totp_last_step' not in d:
        op.add_column('doctors', sa.Column('totp_last_step', sa.Integer(), nullable=True))

    if 'superadmin_alert_seen' not in insp.get_table_names():
        op.create_table(
            'superadmin_alert_seen',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('alert_key', sa.String(), nullable=False),
            sa.Column('marker', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_superadmin_alert_seen_alert_key', 'superadmin_alert_seen', ['alert_key'])


def downgrade():
    op.drop_table('superadmin_alert_seen')
    for col in ('totp_last_step', 'totp_backup_codes', 'totp_enabled', 'totp_secret_enc'):
        op.drop_column('doctors', col)
    op.drop_column('hospital_leads', 'converted_hospital_id')
    for table in ('hospital_leads', 'upgrade_requests'):
        for col in ('contacted_at', 'next_follow_up_at', 'owner', 'follow_up_notes'):
            op.drop_column(table, col)