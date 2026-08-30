"""add PCPNDT Form F support: hospital registration number, order flag, form_f table"""
from alembic import op
import sqlalchemy as sa

revision = 'f7a8b9c0d1e2'
down_revision = 'e6f7a8b9c0d1'

def upgrade():
    op.add_column('hospitals', sa.Column('pcpndt_registration_number', sa.String(), nullable=True))
    op.add_column('radiology_orders', sa.Column('is_reproductive_age_woman', sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        'radiology_form_f',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('radiology_order_id', sa.Integer(), sa.ForeignKey('radiology_orders.id'), nullable=False, unique=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('patient_age', sa.Integer(), nullable=True),
        sa.Column('total_living_children', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('living_sons_ages', sa.Text(), nullable=True),
        sa.Column('living_daughters_ages', sa.Text(), nullable=True),
        sa.Column('guardian_name', sa.String(), nullable=False),
        sa.Column('patient_address_contact', sa.Text(), nullable=False),
        sa.Column('referral_type', sa.String(), nullable=False),
        sa.Column('referring_doctor_details', sa.Text(), nullable=False),
        sa.Column('lmp_or_gestational_weeks', sa.String(), nullable=False),
        sa.Column('performing_doctor_name', sa.String(), nullable=False),
        sa.Column('indication_checklist', sa.Text(), nullable=True),
        sa.Column('declaration_obtained_date', sa.Date(), nullable=True),
        sa.Column('non_sex_determination_declared', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
        sa.Column('procedure_date', sa.DateTime(), nullable=True),
        sa.Column('result_brief', sa.Text(), nullable=True),
        sa.Column('conveyed_to', sa.String(), nullable=True),
        sa.Column('mtp_indication', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
    )

def downgrade():
    op.drop_table('radiology_form_f')
    op.drop_column('radiology_orders', 'is_reproductive_age_woman')
    op.drop_column('hospitals', 'pcpndt_registration_number')