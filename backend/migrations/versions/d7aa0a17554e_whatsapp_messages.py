"""whatsapp_messages: prepared WhatsApp messages shown in the staff "WhatsApp messages" list (new table only)

Also MERGES the two Alembic heads that existed before this file ('c94d2f6a81b7' and 'c0d1e2f3a4b5'),
so the chain has a single head again. Both parents are only referenced, nothing in them is changed.
Idempotent: startup create_all may already have created the table.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd7aa0a17554e'
down_revision = ('c94d2f6a81b7', 'c0d1e2f3a4b5')
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if 'whatsapp_messages' in set(insp.get_table_names()):
        return
    op.create_table(
        'whatsapp_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=True),
        sa.Column('recipient_kind', sa.String(), nullable=False, server_default='patient'),
        sa.Column('recipient_id', sa.Integer(), nullable=True),
        sa.Column('recipient_name', sa.String(), nullable=False),
        sa.Column('recipient_role', sa.String(), nullable=False),
        sa.Column('recipient_phone', sa.String(), nullable=False),
        sa.Column('template_key', sa.String(), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('is_secret', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('secret_enc', sa.Text(), nullable=True),
        sa.Column('visibility', sa.String(), nullable=False, server_default='all'),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('prev_status', sa.String(), nullable=True),
        sa.Column('status_changed_at', sa.DateTime(), nullable=True),
        sa.Column('due_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('is_sample', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
        sa.Column('sent_marked_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
        sa.Column('sent_marked_at', sa.DateTime(), nullable=True),
        sa.Column('appointment_id', sa.Integer(), nullable=True),
        sa.Column('checkin_id', sa.Integer(), nullable=True),
        sa.Column('token_number', sa.String(), nullable=True),
    )
    op.create_index('ix_whatsapp_messages_id', 'whatsapp_messages', ['id'])
    op.create_index('ix_whatsapp_messages_appointment_id', 'whatsapp_messages', ['appointment_id'])
    op.create_index('ix_whatsapp_messages_checkin_id', 'whatsapp_messages', ['checkin_id'])
    op.create_index('ix_whatsapp_messages_hospital_status_due', 'whatsapp_messages', ['hospital_id', 'status', 'due_at'])


def downgrade():
    insp = sa.inspect(op.get_bind())
    if 'whatsapp_messages' in set(insp.get_table_names()):
        op.drop_table('whatsapp_messages')