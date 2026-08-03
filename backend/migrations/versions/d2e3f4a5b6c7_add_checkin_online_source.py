"""add checkin online-booking source fields, make created_by nullable"""
from alembic import op
import sqlalchemy as sa

revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('checkins')}

    with op.batch_alter_table('checkins') as batch_op:
        if 'source' not in existing_cols:
            batch_op.add_column(sa.Column('source', sa.String(), nullable=False, server_default='walk_in'))
        if 'portal_appointment_id' not in existing_cols:
            batch_op.add_column(sa.Column('portal_appointment_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_checkins_portal_appointment_id', 'portal_appointments', ['portal_appointment_id'], ['id'])
        if 'booked_time' not in existing_cols:
            batch_op.add_column(sa.Column('booked_time', sa.DateTime(), nullable=True))
        if 'created_by' in existing_cols:
            batch_op.alter_column('created_by', existing_type=sa.Integer(), nullable=True)


def downgrade():
    with op.batch_alter_table('checkins') as batch_op:
        batch_op.alter_column('created_by', existing_type=sa.Integer(), nullable=False)
    op.drop_column('checkins', 'booked_time')
    op.drop_column('checkins', 'portal_appointment_id')
    op.drop_column('checkins', 'source')