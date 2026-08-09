"""add follow_up_requested_at to suggestions"""
from alembic import op
import sqlalchemy as sa

revision = 'b3c4d5e6f7a8'
down_revision = 'f1c2d3e4f5a6'  # add_suggestions — most relevant parent; adjust to your real current head (multiple heads still unmerged, see prior notes)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('suggestions')}
    if 'follow_up_requested_at' not in cols:
        op.add_column('suggestions', sa.Column('follow_up_requested_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('suggestions', 'follow_up_requested_at')