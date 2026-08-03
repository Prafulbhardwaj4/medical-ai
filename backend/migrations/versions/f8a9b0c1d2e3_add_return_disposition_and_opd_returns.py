"""add disposition to admission_medication_returns + new medicine_order_returns (OPD) table

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-07-30 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'dc0af7f256d8'
down_revision = 'e7f8a9b0c1d2'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_cols = {c['name'] for c in insp.get_columns('admission_medication_returns')}
    if 'disposition' not in existing_cols:
        with op.batch_alter_table('admission_medication_returns') as batch_op:
            # Nullable: historical rows predate this field and aren't
            # backfilled. Enforced as required going forward at the API layer.
            batch_op.add_column(sa.Column('disposition', sa.String(), nullable=True))

    if 'medicine_order_returns' not in insp.get_table_names():
        op.create_table(
            'medicine_order_returns',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('medicine_orders.id'), nullable=False),
            sa.Column('quantity', sa.Integer(), nullable=False),
            sa.Column('disposition', sa.String(), nullable=False),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('refund_id', sa.Integer(), sa.ForeignKey('refunds.id'), nullable=True),
            sa.Column('returned_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('returned_at', sa.DateTime(), nullable=False),
        )


def downgrade():
    op.drop_table('medicine_order_returns')
    with op.batch_alter_table('admission_medication_returns') as batch_op:
        batch_op.drop_column('disposition')