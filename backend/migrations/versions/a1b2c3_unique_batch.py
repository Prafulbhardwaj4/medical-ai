"""add_unique_batch_number

Revision ID: a1b2c3d4e5f7
Revises: c7d8e9f0a1b2
Create Date: 2026-07-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f7'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Normalize blank batch numbers to NULL first — a unique constraint on
    # (medicine_id, batch_number) would otherwise reject the 2nd, 3rd, etc.
    # stock addition for any medicine where no lot number was entered, since
    # SQL treats multiple '' as duplicates but multiple NULLs as not duplicates.
    op.execute("UPDATE medicine_batches SET batch_number = NULL WHERE batch_number = ''")

    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('medicine_batches') as batch_op:
            batch_op.create_index('ix_medicine_batches_batch_number', ['batch_number'], unique=False)
            batch_op.create_unique_constraint('uq_medicine_batch', ['medicine_id', 'batch_number'])
    else:
        op.create_index('ix_medicine_batches_batch_number', 'medicine_batches', ['batch_number'], unique=False)
        op.create_unique_constraint('uq_medicine_batch', 'medicine_batches', ['medicine_id', 'batch_number'])

def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('medicine_batches') as batch_op:
            batch_op.drop_constraint('uq_medicine_batch', type_='unique')
            batch_op.drop_index('ix_medicine_batches_batch_number')
    else:
        op.drop_constraint('uq_medicine_batch', 'medicine_batches', type_='unique')
        op.drop_index('ix_medicine_batches_batch_number', table_name='medicine_batches')