"""add room_type and type_confirmed to rooms"""
from alembic import op
import sqlalchemy as sa

revision = 'b8c9d0e1f2a3'
down_revision = 'a1b2c3d4e5f7'

def upgrade():
    op.add_column('rooms', sa.Column('room_type', sa.String(), nullable=True))
    op.add_column('rooms', sa.Column('type_confirmed', sa.Boolean(), nullable=False, server_default='0'))
    # Legacy rooms had no type — default to General, and leave type_confirmed=False
    # (server_default above) so admin gets a notification to reclassify them.
    op.execute("UPDATE rooms SET room_type = 'General' WHERE room_type IS NULL")

def downgrade():
    op.drop_column('rooms', 'type_confirmed')
    op.drop_column('rooms', 'room_type')