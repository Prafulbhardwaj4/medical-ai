"""add dispensed_by to medicine_orders — Schedule H1/X register needs the dispensing pharmacist

Revision ID: c5d6e7f8a9b0
Revises: a3b4c5d6e7f8
Create Date: 2026-07-30 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'c5d6e7f8a9b0'
down_revision = 'a3b4c5d6e7f8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('medicine_orders')}
    if 'dispensed_by' not in existing_cols:
        if bind.dialect.name == 'sqlite':
            # SQLite supports ADD COLUMN with an inline FK reference directly via
            # raw SQL — it's only Alembic's batch-mode table-recreate that trips
            # on unnamed pre-existing constraints on this table, not SQLite itself.
            op.execute('ALTER TABLE medicine_orders ADD COLUMN dispensed_by INTEGER REFERENCES doctors(id)')
        else:
            op.add_column('medicine_orders', sa.Column('dispensed_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        # Requires SQLite 3.35.0+ (2021). If your SQLite is older than that,
        # downgrading this specific migration isn't supported — drop the
        # column manually or restore from a backup instead.
        op.execute('ALTER TABLE medicine_orders DROP COLUMN dispensed_by')
    else:
        op.drop_column('medicine_orders', 'dispensed_by')