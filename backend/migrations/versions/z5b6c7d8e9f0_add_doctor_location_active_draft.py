"""add doctor location, away-emergency support, and active draft tracking"""
from alembic import op
import sqlalchemy as sa

revision = 'z5b6c7d8e9f0'
down_revision = 'z3c4d5e6f7g8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    attendance_cols = {c['name'] for c in insp.get_columns('attendance_records')}
    if 'doctor_location' not in attendance_cols:
        op.add_column('attendance_records', sa.Column('doctor_location', sa.String(), nullable=True))

    doctor_cols = {c['name'] for c in insp.get_columns('doctors')}
    if 'active_consultation_id' not in doctor_cols:
        with op.batch_alter_table('doctors') as batch_op:
            batch_op.add_column(sa.Column('active_consultation_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_doctors_active_consultation_id', 'consultations', ['active_consultation_id'], ['id'])


def downgrade():
    with op.batch_alter_table('doctors') as batch_op:
        batch_op.drop_constraint('fk_doctors_active_consultation_id', type_='foreignkey')
        batch_op.drop_column('active_consultation_id')
    op.drop_column('attendance_records', 'doctor_location')