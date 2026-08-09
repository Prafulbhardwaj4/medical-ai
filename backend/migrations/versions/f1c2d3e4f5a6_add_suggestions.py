"""add suggestions table"""
from alembic import op
import sqlalchemy as sa

revision = 'f1c2d3e4f5a6'
down_revision = 'a9f3e17c4b02'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'suggestions' in insp.get_table_names():
        return
    op.create_table(
        'suggestions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('hospital_name', sa.String(), nullable=False),
        sa.Column('submitted_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('submitted_by_name', sa.String(), nullable=False),
        sa.Column('submitted_by_role', sa.String(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='sent'),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('resolved_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('suggestions')