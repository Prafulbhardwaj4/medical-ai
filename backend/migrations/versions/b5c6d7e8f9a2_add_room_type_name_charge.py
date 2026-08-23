"""add room_name, room_type, daily_charge to admission_rooms

Supports the redesigned Add Rooms flow: room type (General/Private),
an optional display name alongside room_number, and an optional per-room
daily charge override (Private rooms require their own price; General
rooms inherit the ward's daily_charge unless explicitly overridden).

Revision ID: b5c6d7e8f9a2
Revises: a4b5c6d7e8f1
Create Date: 2026-08-22 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'b5c6d7e8f9a2'
down_revision = 'a4b5c6d7e8f1'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'admission_rooms' not in insp.get_table_names():
        return
    cols = {c['name'] for c in insp.get_columns('admission_rooms')}
    if 'room_name' not in cols:
        op.add_column('admission_rooms', sa.Column('room_name', sa.String(), nullable=True))
    if 'room_type' not in cols:
        op.add_column('admission_rooms', sa.Column('room_type', sa.String(), nullable=False, server_default='general'))
    if 'daily_charge' not in cols:
        op.add_column('admission_rooms', sa.Column('daily_charge', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('admission_rooms', 'daily_charge')
    op.drop_column('admission_rooms', 'room_type')
    op.drop_column('admission_rooms', 'room_name')