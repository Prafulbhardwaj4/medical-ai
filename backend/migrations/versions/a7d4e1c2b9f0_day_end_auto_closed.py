"""day-end: auto_closed flag, counted_* nullable (auto-closed days have no variance)"""
from alembic import op
import sqlalchemy as sa

revision = 'a7d4e1c2b9f0'
down_revision = 'c7d3f2b9e4a1'  # <-- set to the single head shown by `alembic heads` before running
# NOTE: in the zip, `alembic heads` shows 5 heads, and revision ids a9b8c7d6e5f4 and
# f1a2b3c4d5e6 are each used by two different files. Fix that before merging.


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('day_end_closes')}
    if 'auto_closed' not in cols:
        op.add_column('day_end_closes', sa.Column('auto_closed', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('day_end_closes') as batch:
        batch.alter_column('counted_cash', existing_type=sa.Float(), nullable=True)
        batch.alter_column('counted_card', existing_type=sa.Float(), nullable=True)
        batch.alter_column('counted_upi', existing_type=sa.Float(), nullable=True)
    # Old auto-closed rows: flag them and drop the fake "counted = system" numbers.
    op.execute(
        "UPDATE day_end_closes SET auto_closed = TRUE, counted_cash = NULL, counted_card = NULL, counted_upi = NULL "
        "WHERE notes LIKE '[AUTO-CLOSED%' OR notes LIKE 'Auto-closed by%'"
    )


def downgrade():
    op.execute("UPDATE day_end_closes SET counted_cash = COALESCE(counted_cash, 0), counted_card = COALESCE(counted_card, 0), counted_upi = COALESCE(counted_upi, 0)")
    with op.batch_alter_table('day_end_closes') as batch:
        batch.alter_column('counted_cash', existing_type=sa.Float(), nullable=False)
        batch.alter_column('counted_card', existing_type=sa.Float(), nullable=False)
        batch.alter_column('counted_upi', existing_type=sa.Float(), nullable=False)
    op.drop_column('day_end_closes', 'auto_closed')