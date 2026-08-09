"""add suggestion_replies table"""
from alembic import op
import sqlalchemy as sa

revision = 'z3c4d5e6f7a8'
down_revision = 'b3c4d5e6f7a8'  # add_suggestion_follow_up — adjust to your real current head (multiple heads still unmerged)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'suggestion_replies' not in insp.get_table_names():
        op.create_table(
            'suggestion_replies',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('suggestion_id', sa.Integer(), sa.ForeignKey('suggestions.id'), nullable=False),
            sa.Column('sender', sa.String(), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )


def downgrade():
    op.drop_table('suggestion_replies')