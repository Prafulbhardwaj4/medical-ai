"""hospital_usage_snapshots: stored per-month / per-cycle consultation counts

Idempotent: startup create_all may already have created the table on Render.
Plain create_table/drop_table, so it works on PostgreSQL and SQLite.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c0d1e2f3a4b5'
down_revision = 'b9c0d1e2f3a4'
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table('hospital_usage_snapshots'):
        return
    op.create_table(
        'hospital_usage_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('period_kind', sa.String(), nullable=False),
        sa.Column('period_start', sa.DateTime(), nullable=False),
        sa.Column('period_end', sa.DateTime(), nullable=False),
        sa.Column('completed_consultations', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ai_scribe_consultations', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tier', sa.String(), nullable=True),
        sa.Column('billing_period', sa.String(), nullable=True),
        sa.Column('finalized_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('hospital_id', 'period_kind', 'period_start', name='uq_usage_snapshot_period'),
    )
    op.create_index('ix_hospital_usage_snapshots_id', 'hospital_usage_snapshots', ['id'])
    op.create_index('ix_hospital_usage_snapshots_hospital_id', 'hospital_usage_snapshots', ['hospital_id'])


def downgrade():
    op.drop_table('hospital_usage_snapshots')