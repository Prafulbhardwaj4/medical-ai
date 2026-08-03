"""add default_service_hsn_sac to hospitals"""
from alembic import op
import sqlalchemy as sa

revision = 'a4b5c6d7e8f9'
down_revision = '267f1483d160'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    hospital_cols = {c['name'] for c in insp.get_columns('hospitals')}
    if 'default_service_hsn_sac' not in hospital_cols:
        op.add_column(
            'hospitals',
            sa.Column('default_service_hsn_sac', sa.String(), nullable=True, server_default='999311'),
        )


def downgrade():
    op.drop_column('hospitals', 'default_service_hsn_sac')