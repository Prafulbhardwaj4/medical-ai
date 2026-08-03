"""split_room_name_into_number_and_name

Revision ID: l0m1n2o3p4q5
Revises: k9l0m1n2o3p4
Create Date: 2026-07-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'l0m1n2o3p4q5'
down_revision = 'k9l0m1n2o3p4'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('rooms', sa.Column('room_number', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('rooms', 'room_number')
    with op.batch_alter_table('rooms') as batch_op:
        batch_op.alter_column('name', nullable=False)