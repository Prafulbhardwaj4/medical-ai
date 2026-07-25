"""add attachment columns to chat_messages"""
from alembic import op
import sqlalchemy as sa

revision = 'n3o4p5q6r7s8_chat_attachments'
down_revision = 'n3o4p5q6r7s8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('chat_messages')}
    if 'attachment_filename' not in cols:
        op.add_column('chat_messages', sa.Column('attachment_filename', sa.String(), nullable=True))
    if 'attachment_name' not in cols:
        op.add_column('chat_messages', sa.Column('attachment_name', sa.String(), nullable=True))
    if 'attachment_type' not in cols:
        op.add_column('chat_messages', sa.Column('attachment_type', sa.String(), nullable=True))


def downgrade():
    op.drop_column('chat_messages', 'attachment_type')
    op.drop_column('chat_messages', 'attachment_name')
    op.drop_column('chat_messages', 'attachment_filename')