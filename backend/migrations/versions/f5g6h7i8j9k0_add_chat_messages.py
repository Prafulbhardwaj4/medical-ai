"""add chat_messages table (admin<->staff chat)"""
from alembic import op
import sqlalchemy as sa

revision = 'f5g6h7i8j9k0'
down_revision = 'e4f5a6b7c8d9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'chat_messages' not in insp.get_table_names():
        op.create_table(
            'chat_messages',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('staff_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('sender_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('body', sa.Text(), nullable=False),
            sa.Column('is_read_by_staff', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('is_read_by_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_chat_messages_staff_id', 'chat_messages', ['staff_id'])


def downgrade():
    op.drop_index('ix_chat_messages_staff_id', table_name='chat_messages')
    op.drop_table('chat_messages')