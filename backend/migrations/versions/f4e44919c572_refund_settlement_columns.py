"""refunds: original-collection date + who/when settled"""
from alembic import op
import sqlalchemy as sa

revision = 'f4e44919c572'
down_revision = 'k4d5e6f7a8b9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('refunds')}
    if 'collected_at' not in cols:
        op.add_column('refunds', sa.Column('collected_at', sa.DateTime(), nullable=True))
    if 'settled_at' not in cols:
        op.add_column('refunds', sa.Column('settled_at', sa.DateTime(), nullable=True))
    if 'settled_by' not in cols:
        op.add_column('refunds', sa.Column('settled_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True))


def downgrade():
    op.drop_column('refunds', 'settled_by')
    op.drop_column('refunds', 'settled_at')
    op.drop_column('refunds', 'collected_at')