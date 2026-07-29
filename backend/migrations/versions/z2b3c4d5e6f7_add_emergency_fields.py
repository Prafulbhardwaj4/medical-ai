"""add emergency intake and notification targeting fields"""
from alembic import op
import sqlalchemy as sa

revision = 'z2b3c4d5e6f7'
down_revision = 'z1a2b3c4d5e6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    checkin_cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'is_emergency' not in checkin_cols:
        op.add_column('checkins', sa.Column('is_emergency', sa.Boolean(), nullable=False, server_default='false'))

    patient_cols = {c['name'] for c in insp.get_columns('patients')}
    if 'is_emergency_unverified' not in patient_cols:
        op.add_column('patients', sa.Column('is_emergency_unverified', sa.Boolean(), nullable=False, server_default='false'))

    notif_cols = {c['name'] for c in insp.get_columns('notifications')}
    if 'target_doctor_id' not in notif_cols:
        with op.batch_alter_table('notifications') as batch_op:
            batch_op.add_column(sa.Column('target_doctor_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_notifications_target_doctor_id', 'doctors', ['target_doctor_id'], ['id'])


def downgrade():
    with op.batch_alter_table('notifications') as batch_op:
        batch_op.drop_constraint('fk_notifications_target_doctor_id', type_='foreignkey')
        batch_op.drop_column('target_doctor_id')
    op.drop_column('patients', 'is_emergency_unverified')
    op.drop_column('checkins', 'is_emergency')