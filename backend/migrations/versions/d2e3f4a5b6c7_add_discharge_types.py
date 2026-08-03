"""add LAMA/DAMA and death-in-hospital discharge type fields"""
from alembic import op
import sqlalchemy as sa

revision = '07b5bcd756e9'
down_revision = 'c1d2e3f4a5b6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admissions')}

    if 'discharge_type' not in cols:
        op.add_column('admissions', sa.Column('discharge_type', sa.String(), nullable=False, server_default='planned'))
    if 'capacity_evaluation_note' not in cols:
        op.add_column('admissions', sa.Column('capacity_evaluation_note', sa.Text(), nullable=True))
    if 'time_of_death' not in cols:
        op.add_column('admissions', sa.Column('time_of_death', sa.DateTime(), nullable=True))
    if 'certifying_doctor_id' not in cols:
        with op.batch_alter_table('admissions') as batch_op:
            batch_op.add_column(sa.Column('certifying_doctor_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_admissions_certifying_doctor_id', 'doctors', ['certifying_doctor_id'], ['id'])
    if 'cause_of_death' not in cols:
        op.add_column('admissions', sa.Column('cause_of_death', sa.Text(), nullable=True))
    if 'is_mlc' not in cols:
        op.add_column('admissions', sa.Column('is_mlc', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('admissions', 'is_mlc')
    op.drop_column('admissions', 'cause_of_death')
    with op.batch_alter_table('admissions') as batch_op:
        batch_op.drop_constraint('fk_admissions_certifying_doctor_id', type_='foreignkey')
        batch_op.drop_column('certifying_doctor_id')
    op.drop_column('admissions', 'time_of_death')
    op.drop_column('admissions', 'capacity_evaluation_note')
    op.drop_column('admissions', 'discharge_type')