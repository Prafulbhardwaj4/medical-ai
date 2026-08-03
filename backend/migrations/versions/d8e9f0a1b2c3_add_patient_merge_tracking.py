"""add patient merged_into_id for manual duplicate merge tool"""
from alembic import op
import sqlalchemy as sa

revision = '84a7a8931b0b'
down_revision = 'c7d8e9f0a1b2'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('patients')}
    if 'merged_into_id' not in existing_cols:
        with op.batch_alter_table('patients') as batch_op:
            batch_op.add_column(sa.Column('merged_into_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_patients_merged_into_id_tracking', 'patients', ['merged_into_id'], ['id'])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('patients')}
    if 'merged_into_id' in cols:
        with op.batch_alter_table('patients') as batch_op:
            batch_op.drop_constraint('fk_patients_merged_into_id_tracking', type_='foreignkey')
            batch_op.drop_column('merged_into_id')