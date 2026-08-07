"""add custom_windows to doctor_availability_templates"""
from alembic import op
import sqlalchemy as sa

revision = 'z0f1a2b3c4d5'
down_revision = 'z9e0f1a2b3c4'  # <-- adjust to your real current head before running


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('doctor_availability_templates')}
    if 'custom_windows' not in cols:
        op.add_column('doctor_availability_templates', sa.Column('custom_windows', sa.String(), nullable=False, server_default='{}'))


def downgrade():
    op.drop_column('doctor_availability_templates', 'custom_windows')