"""patient suggestions: hospital optional, link to patient account, phone snapshot"""
from alembic import op
import sqlalchemy as sa

revision = 'm6f7a8b9c0d1'
down_revision = 'l5e6f7a8b9c0'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('suggestions')}
    with op.batch_alter_table('suggestions') as batch_op:
        batch_op.alter_column('hospital_id', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('hospital_name', existing_type=sa.String(), nullable=True)
        if 'patient_account_id' not in cols:
            batch_op.add_column(sa.Column('patient_account_id', sa.Integer(), sa.ForeignKey('patient_accounts.id'), nullable=True))
        if 'submitted_by_phone' not in cols:
            batch_op.add_column(sa.Column('submitted_by_phone', sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table('suggestions') as batch_op:
        batch_op.drop_column('submitted_by_phone')
        batch_op.drop_column('patient_account_id')