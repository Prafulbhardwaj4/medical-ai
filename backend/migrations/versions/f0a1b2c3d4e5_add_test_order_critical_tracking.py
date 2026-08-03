"""add critical-value tracking fields to test_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'f0a1b2c3d4e5'
down_revision = 'e9f0a1b2c3d4'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('test_orders')}

    if 'is_critical' not in existing_cols:
        op.add_column('test_orders', sa.Column('is_critical', sa.Boolean(), nullable=False, server_default='false'))
    if 'critical_note' not in existing_cols:
        op.add_column('test_orders', sa.Column('critical_note', sa.Text(), nullable=True))
    if 'critical_detected_at' not in existing_cols:
        op.add_column('test_orders', sa.Column('critical_detected_at', sa.DateTime(), nullable=True))
    if 'critical_ack_at' not in existing_cols:
        op.add_column('test_orders', sa.Column('critical_ack_at', sa.DateTime(), nullable=True))
    if 'critical_escalated_at' not in existing_cols:
        op.add_column('test_orders', sa.Column('critical_escalated_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('test_orders', 'critical_escalated_at')
    op.drop_column('test_orders', 'critical_ack_at')
    op.drop_column('test_orders', 'critical_detected_at')
    op.drop_column('test_orders', 'critical_note')
    op.drop_column('test_orders', 'is_critical')