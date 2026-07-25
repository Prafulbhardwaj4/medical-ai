"""add patient_addresses table"""
from alembic import op
import sqlalchemy as sa

revision = 'p5q6r7s8t9u0'
down_revision = 'o4p5q6r7s8t9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'patient_addresses' not in insp.get_table_names():
        op.create_table(
            'patient_addresses',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('patient_accounts.id'), nullable=False),
            sa.Column('label', sa.String(), nullable=False, server_default='Address'),
            sa.Column('address', sa.String(), nullable=False),
            sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table('patient_addresses')