"""add nppa_ceiling_price to hospital_medicines

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-07-30 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '27dac3076779'
down_revision = 'd6e7f8a9b0c1'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('hospital_medicines')}
    if 'nppa_ceiling_price' not in existing_cols:
        with op.batch_alter_table('hospital_medicines') as batch_op:
            batch_op.add_column(sa.Column('nppa_ceiling_price', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('hospital_medicines') as batch_op:
        batch_op.drop_column('nppa_ceiling_price')