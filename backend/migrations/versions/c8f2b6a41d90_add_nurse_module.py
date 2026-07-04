"""add nurse module fields to checkins"""
from alembic import op
import sqlalchemy as sa

revision = 'c8f2b6a41d90'
down_revision = 'b7e4a29f10c3'

def upgrade():
    with op.batch_alter_table('checkins') as batch_op:
        batch_op.add_column(sa.Column('nurse_id', sa.Integer(), sa.ForeignKey('doctors.id', name='fk_checkins_nurse_id'), nullable=True))
        batch_op.add_column(sa.Column('vitals_status', sa.String(), nullable=False, server_default='none'))
        batch_op.add_column(sa.Column('vitals_data', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('vitals_recorded_by', sa.Integer(), sa.ForeignKey('doctors.id', name='fk_checkins_vitals_recorded_by'), nullable=True))
        batch_op.add_column(sa.Column('vitals_recorded_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('post_consult_status', sa.String(), nullable=False, server_default='none'))
        batch_op.add_column(sa.Column('post_consult_note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('post_consult_data', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('post_consult_recorded_by', sa.Integer(), sa.ForeignKey('doctors.id', name='fk_checkins_post_consult_recorded_by'), nullable=True))
        batch_op.add_column(sa.Column('post_consult_recorded_at', sa.DateTime(), nullable=True))

def downgrade():
    with op.batch_alter_table('checkins') as batch_op:
        batch_op.drop_column('post_consult_recorded_at')
        batch_op.drop_column('post_consult_recorded_by')
        batch_op.drop_column('post_consult_data')
        batch_op.drop_column('post_consult_note')
        batch_op.drop_column('post_consult_status')
        batch_op.drop_column('vitals_recorded_at')
        batch_op.drop_column('vitals_recorded_by')
        batch_op.drop_column('vitals_data')
        batch_op.drop_column('vitals_status')
        batch_op.drop_column('nurse_id')