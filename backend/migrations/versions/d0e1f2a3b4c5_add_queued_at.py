"""add queued_at to test_orders and medicine_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'f7c96b82813c'
down_revision = 'c9d0e1f2a3b4'

def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    test_orders_cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'queued_at' not in test_orders_cols:
        op.add_column('test_orders', sa.Column('queued_at', sa.DateTime(), nullable=True))

    medicine_orders_cols = {c['name'] for c in insp.get_columns('medicine_orders')}
    if 'queued_at' not in medicine_orders_cols:
        op.add_column('medicine_orders', sa.Column('queued_at', sa.DateTime(), nullable=True))

    # Backfill existing paid+ rows so they don't vanish from today's queue views.
    # Safe to re-run — only touches rows where queued_at is still unset.
    op.execute("""
        UPDATE test_orders SET queued_at = paid_at
        WHERE status IN ('paid', 'sample_collected', 'processing', 'completed')
        AND paid_at IS NOT NULL
        AND queued_at IS NULL
    """)
    op.execute("""
        UPDATE medicine_orders SET queued_at = paid_at
        WHERE status IN ('paid', 'dispensed')
        AND paid_at IS NOT NULL
        AND queued_at IS NULL
    """)

def downgrade():
    op.drop_column('medicine_orders', 'queued_at')
    op.drop_column('test_orders', 'queued_at')