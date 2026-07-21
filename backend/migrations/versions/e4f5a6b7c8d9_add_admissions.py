"""add admission (IPD) tracking tables; link test_orders and invoices to admissions"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'admissions' not in existing_tables:
        op.create_table(
            'admissions',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('admitting_doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('ward', sa.String(), nullable=False),
            sa.Column('bed_number', sa.String(), nullable=False),
            sa.Column('diagnosis', sa.Text(), nullable=True),
            sa.Column('daily_room_charge', sa.Float(), nullable=False, server_default='0'),
            sa.Column('status', sa.String(), nullable=False, server_default='admitted'),
            sa.Column('admission_date', sa.DateTime(), nullable=False),
            sa.Column('discharge_date', sa.DateTime(), nullable=True),
            sa.Column('discharge_summary', sa.Text(), nullable=True),
            sa.Column('discharge_invoice_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    if 'admission_medication_orders' not in existing_tables:
        op.create_table(
            'admission_medication_orders',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=False),
            sa.Column('medicine_id', sa.Integer(), sa.ForeignKey('hospital_medicines.id'), nullable=True),
            sa.Column('medicine_name', sa.String(), nullable=False),
            sa.Column('dosage', sa.String(), nullable=False),
            sa.Column('route', sa.String(), nullable=False, server_default='Oral'),
            sa.Column('frequency_note', sa.String(), nullable=True),
            sa.Column('prescribed_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('is_active', sa.Boolean(), server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    if 'admission_medication_administrations' not in existing_tables:
        op.create_table(
            'admission_medication_administrations',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('admission_medication_orders.id'), nullable=False),
            sa.Column('administered_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('administered_at', sa.DateTime(), nullable=False),
            sa.Column('notes', sa.String(), nullable=True),
        )

    if 'admission_charges' not in existing_tables:
        op.create_table(
            'admission_charges',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=False),
            sa.Column('charge_type', sa.String(), nullable=False),
            sa.Column('description', sa.String(), nullable=False),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('added_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('charged_at', sa.DateTime(), nullable=True),
        )

    # Link existing test_orders to admissions (OPD keeps using consultation_id; IPD uses this)
    test_order_cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'admission_id' not in test_order_cols:
        op.add_column('test_orders', sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=True))
    if 'consultation_id' in test_order_cols:
        op.alter_column('test_orders', 'consultation_id', nullable=True)

    # Discharge bills have no Checkin — invoices needs to support that
    invoice_cols = {c['name'] for c in insp.get_columns('invoices')}
    if 'admission_id' not in invoice_cols:
        op.add_column('invoices', sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=True))
    if 'checkin_id' in invoice_cols:
        op.alter_column('invoices', 'checkin_id', nullable=True)

    # FK for admissions.discharge_invoice_id -> invoices.id (added after invoices exists/is stable)
    op.create_foreign_key('fk_admission_discharge_invoice', 'admissions', 'invoices', ['discharge_invoice_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_admission_discharge_invoice', 'admissions', type_='foreignkey')
    op.alter_column('invoices', 'checkin_id', nullable=False)
    op.drop_column('invoices', 'admission_id')
    op.alter_column('test_orders', 'consultation_id', nullable=False)
    op.drop_column('test_orders', 'admission_id')
    op.drop_table('admission_charges')
    op.drop_table('admission_medication_administrations')
    op.drop_table('admission_medication_orders')
    op.drop_table('admissions')