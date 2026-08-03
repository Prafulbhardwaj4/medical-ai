"""add structured discharge summary fields"""
from alembic import op
import sqlalchemy as sa

revision = 'd9bfb9f357dd'
down_revision = 'd2e3f4a5b6c7'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admissions')}

    if 'discharging_doctor_id' not in cols:
        with op.batch_alter_table('admissions') as batch_op:
            batch_op.add_column(sa.Column('discharging_doctor_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_admissions_discharging_doctor_id', 'doctors', ['discharging_doctor_id'], ['id'])
    for col in ('course_in_hospital', 'procedures_performed', 'discharge_diagnosis', 'condition_at_discharge', 'medications_on_discharge', 'follow_up_instructions'):
        if col not in cols:
            op.add_column('admissions', sa.Column(col, sa.Text(), nullable=True))


def downgrade():
    for col in ('follow_up_instructions', 'medications_on_discharge', 'condition_at_discharge', 'discharge_diagnosis', 'procedures_performed', 'course_in_hospital'):
        op.drop_column('admissions', col)
    with op.batch_alter_table('admissions') as batch_op:
        batch_op.drop_constraint('fk_admissions_discharging_doctor_id', type_='foreignkey')
        batch_op.drop_column('discharging_doctor_id')