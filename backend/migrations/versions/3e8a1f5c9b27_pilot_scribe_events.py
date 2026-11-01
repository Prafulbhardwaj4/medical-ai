"""pilot_scribe_events: consultations.ai_scribe_credit_at (when a scribe credit was used) and the superadmin_events table. Additive and idempotent."""
from alembic import op
import sqlalchemy as sa

revision = '3e8a1f5c9b27'
down_revision = '5c19e7a2d4b8'  # pilot_plans (the single current head)


def upgrade():
    insp = sa.inspect(op.get_bind())

    cols = {c['name'] for c in insp.get_columns('consultations')}
    if 'ai_scribe_credit_at' not in cols:
        op.add_column('consultations', sa.Column('ai_scribe_credit_at', sa.DateTime(), nullable=True))

    if 'superadmin_events' not in set(insp.get_table_names()):
        op.create_table(
            'superadmin_events',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('dedupe_key', sa.String(), nullable=False),
            sa.Column('event_type', sa.String(), nullable=False),
            sa.Column('severity', sa.String(), nullable=False, server_default='warning'),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('message', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_superadmin_events_id', 'superadmin_events', ['id'])
        op.create_index('ix_superadmin_events_hospital_id', 'superadmin_events', ['hospital_id'])
        op.create_index('ix_superadmin_events_dedupe_key', 'superadmin_events', ['dedupe_key'], unique=True)


def downgrade():
    insp = sa.inspect(op.get_bind())
    if 'superadmin_events' in set(insp.get_table_names()):
        op.drop_table('superadmin_events')
    cols = {c['name'] for c in insp.get_columns('consultations')}
    if 'ai_scribe_credit_at' in cols:
        op.drop_column('consultations', 'ai_scribe_credit_at')