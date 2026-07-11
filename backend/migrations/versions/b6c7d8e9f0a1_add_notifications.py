"""add notifications table"""
from alembic import op
import sqlalchemy as sa

revision = 'b6c7d8e9f0a1'
down_revision = 'a5b6c7d8e9f0'

def upgrade():
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('source_key', sa.String(), nullable=False),  # unique per (hospital, condition) — used to upsert/dedupe
        sa.Column('type', sa.String(), nullable=False),  # "low_stock", "expiring_stock", (later: "idle_staff", etc.)
        sa.Column('severity', sa.String(), nullable=False, server_default='warning'),  # info / warning / critical
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('message', sa.String(), nullable=False),
        sa.Column('link_type', sa.String(), nullable=True),  # e.g. "medicine"
        sa.Column('link_id', sa.Integer(), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_notifications_source_key', 'notifications', ['hospital_id', 'source_key'], unique=True)

def downgrade():
    op.drop_index('ix_notifications_source_key', table_name='notifications')
    op.drop_table('notifications')