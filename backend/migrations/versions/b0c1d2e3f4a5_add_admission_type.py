"""add admission_type field"""
from alembic import op
import sqlalchemy as sa

revision = 'b0c1d2e3f4a5'
down_revision = 'z8d9e0f1a2b3'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    admission_cols = {c['name'] for c in insp.get_columns('admissions')}
    if 'admission_type' not in admission_cols:
        op.add_column('admissions', sa.Column('admission_type', sa.String(), nullable=False, server_default='planned'))


def downgrade():
    op.drop_column('admissions', 'admission_type')