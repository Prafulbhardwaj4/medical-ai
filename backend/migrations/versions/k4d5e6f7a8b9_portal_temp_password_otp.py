"""patient portal: temporary-password flag and forgot-password OTP columns"""
from alembic import op
import sqlalchemy as sa

revision = 'k4d5e6f7a8b9'
down_revision = 'j3c4d5e6f7a8'  # run `alembic heads` first; it must show exactly one head


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('patient_accounts')}
    if 'must_change_password' not in cols:
        op.add_column('patient_accounts', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'reset_otp_hash' not in cols:
        op.add_column('patient_accounts', sa.Column('reset_otp_hash', sa.String(), nullable=True))
    if 'reset_otp_expires_at' not in cols:
        op.add_column('patient_accounts', sa.Column('reset_otp_expires_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('patient_accounts', 'reset_otp_expires_at')
    op.drop_column('patient_accounts', 'reset_otp_hash')
    op.drop_column('patient_accounts', 'must_change_password')