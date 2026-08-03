"""add patient merge tool"""
from alembic import op
import sqlalchemy as sa

revision = 'd8e9f0a1b2c3'
down_revision = 'c7d8e9f0a1b2'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    patient_cols = {c['name'] for c in insp.get_columns('patients')}

    if 'is_active' not in patient_cols:
        op.add_column('patients', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))
    if 'merged_into_id' not in patient_cols:
        with op.batch_alter_table('patients') as batch_op:
            batch_op.add_column(sa.Column('merged_into_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_patients_merged_into_id', 'patients', ['merged_into_id'], ['id'])

    op.create_table(
        'patient_merge_requests',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('primary_patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('duplicate_patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending_confirmation'),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('flagged_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('flagged_at', sa.DateTime(), nullable=True),
        sa.Column('confirmation_note', sa.Text(), nullable=True),
        sa.Column('confirmed_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('merged_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
        sa.Column('merged_at', sa.DateTime(), nullable=True),
        sa.Column('unmerged_profile_link_note', sa.Text(), nullable=True),
    )
    # No separate create_index needed — sa.Column('id', ..., index=True)
    # above already creates it.


def downgrade():
    op.drop_table('patient_merge_requests')
    with op.batch_alter_table('patients') as batch_op:
        batch_op.drop_constraint('fk_patients_merged_into_id', type_='foreignkey')
        batch_op.drop_column('merged_into_id')
    op.drop_column('patients', 'is_active')