"""add recipient_id to chat_messages for peer-to-peer staff chat"""
from alembic import op
import sqlalchemy as sa

revision = 'f3a9c1d4e8b2'
down_revision = '8c66c6640c00'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('chat_messages')}
    if 'recipient_id' not in cols:
        op.add_column('chat_messages', sa.Column('recipient_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True))
        op.create_index('ix_chat_messages_recipient_id', 'chat_messages', ['recipient_id'])


def downgrade():
    op.drop_index('ix_chat_messages_recipient_id', table_name='chat_messages')
    op.drop_column('chat_messages', 'recipient_id')