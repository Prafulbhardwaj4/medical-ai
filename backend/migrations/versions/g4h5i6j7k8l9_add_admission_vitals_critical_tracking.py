"""add critical-value tracking fields to admission_vitals"""
from alembic import op
import sqlalchemy as sa

revision = 'g4h5i6j7k8l9'
down_revision = 'b3c4d5e6f7a9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('admission_vitals')}

    if 'is_critical' not in existing_cols:
        op.add_column('admission_vitals', sa.Column('is_critical', sa.Boolean(), nullable=False, server_default='false'))
    if 'critical_note' not in existing_cols:
        op.add_column('admission_vitals', sa.Column('critical_note', sa.Text(), nullable=True))
    if 'critical_detected_at' not in existing_cols:
        op.add_column('admission_vitals', sa.Column('critical_detected_at', sa.DateTime(), nullable=True))
    if 'critical_ack_at' not in existing_cols:
        op.add_column('admission_vitals', sa.Column('critical_ack_at', sa.DateTime(), nullable=True))
    if 'critical_escalated_at' not in existing_cols:
        op.add_column('admission_vitals', sa.Column('critical_escalated_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('admission_vitals', 'critical_escalated_at')
    op.drop_column('admission_vitals', 'critical_ack_at')
    op.drop_column('admission_vitals', 'critical_detected_at')
    op.drop_column('admission_vitals', 'critical_note')
    op.drop_column('admission_vitals', 'is_critical')