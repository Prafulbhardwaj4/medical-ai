"""add schedule X repeat-dispense authorization fields to medicine_orders

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-07-30 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '70ac349e07ae'
down_revision = 'c5d6e7f8a9b0'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('medicine_orders')}

    if bind.dialect.name == 'sqlite':
        # Batch mode chokes on this table's pre-existing unnamed constraints
        # (see c5d6e7f8a9b0) — plain ALTER TABLE ADD COLUMN works fine on
        # SQLite directly and avoids the table-recreate dance entirely.
        if 'repeat_authorized' not in existing_cols:
            op.execute("ALTER TABLE medicine_orders ADD COLUMN repeat_authorized BOOLEAN NOT NULL DEFAULT 0")
        if 'repeat_authorized_by' not in existing_cols:
            op.execute("ALTER TABLE medicine_orders ADD COLUMN repeat_authorized_by INTEGER REFERENCES doctors(id)")
        if 'repeat_authorized_at' not in existing_cols:
            op.execute("ALTER TABLE medicine_orders ADD COLUMN repeat_authorized_at DATETIME")
    else:
        cols_to_add = []
        if 'repeat_authorized' not in existing_cols:
            cols_to_add.append(sa.Column('repeat_authorized', sa.Boolean(), nullable=False, server_default=sa.false()))
        if 'repeat_authorized_by' not in existing_cols:
            cols_to_add.append(sa.Column('repeat_authorized_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True))
        if 'repeat_authorized_at' not in existing_cols:
            cols_to_add.append(sa.Column('repeat_authorized_at', sa.DateTime(), nullable=True))
        if cols_to_add:
            with op.batch_alter_table('medicine_orders') as batch_op:
                for col in cols_to_add:
                    batch_op.add_column(col)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        op.execute("ALTER TABLE medicine_orders DROP COLUMN repeat_authorized_at")
        op.execute("ALTER TABLE medicine_orders DROP COLUMN repeat_authorized_by")
        op.execute("ALTER TABLE medicine_orders DROP COLUMN repeat_authorized")
    else:
        with op.batch_alter_table('medicine_orders') as batch_op:
            batch_op.drop_column('repeat_authorized_at')
            batch_op.drop_column('repeat_authorized_by')
            batch_op.drop_column('repeat_authorized')