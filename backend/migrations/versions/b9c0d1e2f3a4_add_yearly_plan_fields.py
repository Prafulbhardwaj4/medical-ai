"""yearly plans: hospitals.billing_period backfill, plan_end_date, ai_scribe_yearly_allowance

Idempotent: the startup schema sync may already have added these columns on Render.
Works on PostgreSQL and SQLite (batch mode for the SQLite-unsafe downgrade).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b9c0d1e2f3a4'
down_revision = 'a8b9c0d1e2f3'
branch_labels = None
depends_on = None


def _existing_columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns('hospitals')}


def upgrade():
    existing = _existing_columns()
    if 'billing_period' not in existing:
        op.add_column('hospitals', sa.Column('billing_period', sa.String(), nullable=True, server_default='monthly'))
    if 'plan_end_date' not in existing:
        op.add_column('hospitals', sa.Column('plan_end_date', sa.DateTime(), nullable=True))
    if 'ai_scribe_yearly_allowance' not in existing:
        op.add_column('hospitals', sa.Column('ai_scribe_yearly_allowance', sa.Integer(), nullable=True))
    # Existing hospitals stay monthly and behave exactly as before.
    op.execute("UPDATE hospitals SET billing_period = 'monthly' WHERE billing_period IS NULL")


def downgrade():
    # billing_period is left in place: it existed before this migration (runtime-synced).
    with op.batch_alter_table('hospitals') as batch:
        batch.drop_column('ai_scribe_yearly_allowance')
        batch.drop_column('plan_end_date')