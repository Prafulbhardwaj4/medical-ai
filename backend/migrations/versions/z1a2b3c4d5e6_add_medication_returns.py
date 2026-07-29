"""add admission medication returns table"""
from alembic import op
import sqlalchemy as sa

revision = 'z1a2b3c4d5e6'
down_revision = 'y6z7a8b9c0d1'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'admission_medication_returns' not in insp.get_table_names():
        op.create_table(
            'admission_medication_returns',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=False),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('admission_medication_orders.id'), nullable=False),
            sa.Column('quantity', sa.Integer(), nullable=False),
            sa.Column('restocked', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('credit_charge_id', sa.Integer(), sa.ForeignKey('admission_charges.id'), nullable=True),
            sa.Column('returned_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('returned_at', sa.DateTime(), nullable=False),
        )


def downgrade():
    op.drop_table('admission_medication_returns')