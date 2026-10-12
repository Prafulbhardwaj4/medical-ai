"""master catalogs: master_tests, master_test_parameters, master_medicines (new tables),
plus nullable master_test_id / master_medicine_id links on hospital rows.

This revision also MERGES the two heads that existed in the repo before it
(m6f7a8b9c0d1 patient_suggestions and f6c853b583ae add_import_batches), so the chain
has a single head again. Startup runs `alembic upgrade heads`, which applies this safely.
Additive and idempotent: new tables and nullable columns only.
"""
from alembic import op
import sqlalchemy as sa

revision = '7b3e9c41a2d8'
down_revision = ('m6f7a8b9c0d1', 'f6c853b583ae')


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    if 'master_tests' not in existing:
        op.create_table(
            'master_tests',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('name_norm', sa.String(), nullable=False),
            sa.Column('aliases', sa.Text(), nullable=True),
            sa.Column('category', sa.String(), nullable=True),
            sa.Column('required_tube', sa.String(), nullable=True),
            sa.Column('fasting_required', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('turnaround_hours', sa.Integer(), nullable=True),
            sa.Column('is_panel', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('purpose', sa.Text(), nullable=True),
            sa.Column('unit', sa.String(), nullable=True),
            sa.Column('reference_range_male', sa.String(), nullable=True),
            sa.Column('reference_range_female', sa.String(), nullable=True),
            sa.Column('critical_low', sa.Float(), nullable=True),
            sa.Column('critical_high', sa.Float(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_master_tests_id', 'master_tests', ['id'])
        op.create_index('ix_master_tests_name_norm', 'master_tests', ['name_norm'], unique=True)

    if 'master_test_parameters' not in existing:
        op.create_table(
            'master_test_parameters',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('master_test_id', sa.Integer(), sa.ForeignKey('master_tests.id'), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('unit', sa.String(), nullable=True),
            sa.Column('reference_range_male', sa.String(), nullable=True),
            sa.Column('reference_range_female', sa.String(), nullable=True),
            sa.Column('purpose', sa.Text(), nullable=True),
            sa.Column('critical_low', sa.Float(), nullable=True),
            sa.Column('critical_high', sa.Float(), nullable=True),
            sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_master_test_parameters_id', 'master_test_parameters', ['id'])
        op.create_index('ix_master_test_parameters_master_test_id', 'master_test_parameters', ['master_test_id'])

    if 'master_medicines' not in existing:
        op.create_table(
            'master_medicines',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('generic_name', sa.String(), nullable=False),
            sa.Column('strength', sa.String(), nullable=True),
            sa.Column('dosage_form', sa.String(), nullable=True),
            sa.Column('schedule', sa.String(), nullable=False, server_default='otc'),
            sa.Column('default_pack_size', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('default_billing_mode', sa.String(), nullable=False, server_default='per_unit'),
            sa.Column('gst_percent', sa.Float(), nullable=True),
            sa.Column('hsn_code', sa.String(), nullable=True),
            sa.Column('category', sa.String(), nullable=True),
            sa.Column('display_name', sa.String(), nullable=False),
            sa.Column('name_norm', sa.String(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_master_medicines_id', 'master_medicines', ['id'])
        op.create_index('ix_master_medicines_name_norm', 'master_medicines', ['name_norm'], unique=True)

    insp = sa.inspect(bind)
    test_cols = {c['name'] for c in insp.get_columns('test_catalog_items')}
    if 'master_test_id' not in test_cols:
        op.add_column('test_catalog_items', sa.Column(
            'master_test_id', sa.Integer(), sa.ForeignKey('master_tests.id'), nullable=True))

    med_cols = {c['name'] for c in insp.get_columns('hospital_medicines')}
    if 'master_medicine_id' not in med_cols:
        op.add_column('hospital_medicines', sa.Column(
            'master_medicine_id', sa.Integer(), sa.ForeignKey('master_medicines.id'), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    med_cols = {c['name'] for c in insp.get_columns('hospital_medicines')}
    if 'master_medicine_id' in med_cols:
        op.drop_column('hospital_medicines', 'master_medicine_id')
    test_cols = {c['name'] for c in insp.get_columns('test_catalog_items')}
    if 'master_test_id' in test_cols:
        op.drop_column('test_catalog_items', 'master_test_id')
    existing = set(insp.get_table_names())
    for table in ('master_medicines', 'master_test_parameters', 'master_tests'):
        if table in existing:
            op.drop_table(table)