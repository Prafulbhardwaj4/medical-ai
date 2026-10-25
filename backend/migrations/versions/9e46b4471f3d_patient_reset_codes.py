"""patient_reset_codes: forgot-password codes for patient portal accounts (new table only)"""
from alembic import op
import sqlalchemy as sa

revision = '9e46b4471f3d'
down_revision = '504a0c891593'  # temp_password_expiry (the single current head)


def upgrade():
    insp = sa.inspect(op.get_bind())
    if 'patient_reset_codes' in set(insp.get_table_names()):
        return
    op.create_table(
        'patient_reset_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('patient_accounts.id'), nullable=False),
        sa.Column('code_hash', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_patient_reset_codes_id', 'patient_reset_codes', ['id'])
    op.create_index('ix_patient_reset_codes_account_created', 'patient_reset_codes', ['account_id', 'created_at'])


def downgrade():
    insp = sa.inspect(op.get_bind())
    if 'patient_reset_codes' in set(insp.get_table_names()):
        op.drop_table('patient_reset_codes')