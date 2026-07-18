from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'a9b8c7d6e5f4'
down_revision = 'f3a1b9c8d2e7'


def upgrade():
    bind = op.get_bind()
    insp = inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('hospital_medicines')}
    existing_fks = {fk['name'] for fk in insp.get_foreign_keys('hospital_medicines') if fk['name']}

    cols_to_add = []
    if 'brand_name' not in existing_cols:
        cols_to_add.append(sa.Column('brand_name', sa.String(), nullable=True))
    if 'parent_medicine_id' not in existing_cols:
        cols_to_add.append(sa.Column('parent_medicine_id', sa.Integer(), nullable=True))

    if cols_to_add:
        with op.batch_alter_table('hospital_medicines') as batch_op:
            for col in cols_to_add:
                batch_op.add_column(col)

    if 'fk_hospital_medicines_parent_medicine_id' not in existing_fks:
        with op.batch_alter_table('hospital_medicines') as batch_op:
            batch_op.create_foreign_key(
                'fk_hospital_medicines_parent_medicine_id',
                'hospital_medicines',
                ['parent_medicine_id'], ['id']
            )


def downgrade():
    with op.batch_alter_table('hospital_medicines') as batch_op:
        batch_op.drop_constraint('fk_hospital_medicines_parent_medicine_id', type_='foreignkey')

    with op.batch_alter_table('hospital_medicines') as batch_op:
        batch_op.drop_column('parent_medicine_id')
        batch_op.drop_column('brand_name')