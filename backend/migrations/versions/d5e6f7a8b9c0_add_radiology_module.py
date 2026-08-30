"""add radiology module tables"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'

def upgrade():
    op.create_table(
        'radiology_templates',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('study_type', sa.String(), nullable=False),
        sa.Column('fee', sa.Float(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'radiology_template_sections',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('radiology_template_id', sa.Integer(), sa.ForeignKey('radiology_templates.id'), nullable=False),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('default_finding_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'radiology_orders',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('consultation_id', sa.Integer(), sa.ForeignKey('consultations.id'), nullable=True),
        sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=True),
        sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('template_id', sa.Integer(), sa.ForeignKey('radiology_templates.id'), nullable=True),
        sa.Column('study_name', sa.String(), nullable=False),
        sa.Column('study_type', sa.String(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False, server_default='0'),
        sa.Column('order_batch_id', sa.String(), nullable=True),
        sa.Column('included', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('status', sa.String(), nullable=False, server_default='payment_pending'),
        sa.Column('priority', sa.String(), nullable=False, server_default='routine'),
        sa.Column('clinical_indication', sa.Text(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('payment_method', sa.String(), nullable=True),
        sa.Column('queued_at', sa.DateTime(), nullable=True),
        sa.Column('sections_data', sa.Text(), nullable=True),
        sa.Column('impression', sa.Text(), nullable=True),
        sa.Column('advised', sa.Text(), nullable=True),
        sa.Column('reported_at', sa.DateTime(), nullable=True),
        sa.Column('reported_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
        sa.Column('verified_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
        sa.Column('self_verified_sole_staff', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_radiology_orders_order_batch_id', 'radiology_orders', ['order_batch_id'])

def downgrade():
    op.drop_index('ix_radiology_orders_order_batch_id', table_name='radiology_orders')
    op.drop_table('radiology_orders')
    op.drop_table('radiology_template_sections')
    op.drop_table('radiology_templates')