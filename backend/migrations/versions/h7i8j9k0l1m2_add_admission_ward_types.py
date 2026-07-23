"""add admission_ward_types table + ward_type_id on admissions"""
from alembic import op
import sqlalchemy as sa

revision = 'h7i8j9k0l1m2'
down_revision = 'g6h7i8j9k0l1'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'admission_ward_types' not in insp.get_table_names():
        op.create_table(
            'admission_ward_types',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('total_beds', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('daily_charge', sa.Float(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    admission_cols = {c['name'] for c in insp.get_columns('admissions')}
    if 'ward_type_id' not in admission_cols:
        if bind.dialect.name == 'sqlite':
            with op.batch_alter_table('admissions') as batch_op:
                batch_op.add_column(sa.Column('ward_type_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_admissions_ward_type_id', 'admission_ward_types', ['ward_type_id'], ['id'])
        else:
            op.add_column('admissions', sa.Column('ward_type_id', sa.Integer(), sa.ForeignKey('admission_ward_types.id'), nullable=True))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('admissions') as batch_op:
            batch_op.drop_constraint('fk_admissions_ward_type_id', type_='foreignkey')
            batch_op.drop_column('ward_type_id')
    else:
        op.drop_column('admissions', 'ward_type_id')
    op.drop_table('admission_ward_types')