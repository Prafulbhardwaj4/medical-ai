"""add address to patients, patient_accounts, portal_appointments"""
from alembic import op
import sqlalchemy as sa

revision = 'g6h7i8j9k0l1'
down_revision = 'f5g6h7i8j9k0'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    patient_cols = {c['name'] for c in insp.get_columns('patients')}
    if 'address' not in patient_cols:
        op.add_column('patients', sa.Column('address', sa.String(), nullable=True))

    account_cols = {c['name'] for c in insp.get_columns('patient_accounts')}
    if 'address' not in account_cols:
        op.add_column('patient_accounts', sa.Column('address', sa.String(), nullable=True))

    appt_cols = {c['name'] for c in insp.get_columns('portal_appointments')}
    if 'address' not in appt_cols:
        op.add_column('portal_appointments', sa.Column('address', sa.String(), nullable=True))


def downgrade():
    op.drop_column('portal_appointments', 'address')
    op.drop_column('patient_accounts', 'address')
    op.drop_column('patients', 'address')