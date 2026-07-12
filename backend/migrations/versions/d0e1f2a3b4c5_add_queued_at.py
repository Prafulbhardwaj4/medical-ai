"""add queued_at to test_orders and medicine_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'

def upgrade():
    op.add_column('test_orders', sa.Column('queued_at', sa.DateTime(), nullable=True))
    op.add_column('medicine_orders', sa.Column('queued_at', sa.DateTime(), nullable=True))

    # Backfill existing paid+ rows so they don't vanish from today's queue views
    op.execute("""
        UPDATE test_orders SET queued_at = paid_at
        WHERE status IN ('paid', 'sample_collected', 'processing', 'completed')
        AND paid_at IS NOT NULL
    """)
    op.execute("""
        UPDATE medicine_orders SET queued_at = paid_at
        WHERE status IN ('paid', 'dispensed')
        AND paid_at IS NOT NULL
    """)

def downgrade():
    op.drop_column('medicine_orders', 'queued_at')
    op.drop_column('test_orders', 'queued_at')