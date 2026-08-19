"""add admission_medication_dispenses table"""
from alembic import op
import sqlalchemy as sa

revision = 'f9b2d6e4c8a1'
down_revision = 'c7e3a9f2d1b4'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'admission_medication_dispenses' not in insp.get_table_names():
        op.create_table(
            'admission_medication_dispenses',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('admission_medication_orders.id'), nullable=False),
            sa.Column('quantity', sa.Integer(), nullable=False),
            sa.Column('unit_price', sa.Float(), nullable=False, server_default='0'),
            sa.Column('total_amount', sa.Float(), nullable=False, server_default='0'),
            sa.Column('dispensed_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('dispensed_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_admission_medication_dispenses_order_id', 'admission_medication_dispenses', ['order_id'])


def downgrade():
    op.drop_index('ix_admission_medication_dispenses_order_id', table_name='admission_medication_dispenses')
    op.drop_table('admission_medication_dispenses')