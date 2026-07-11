"""add invoices table, checkin finalize fields, hospital gstin"""
from alembic import op
import sqlalchemy as sa

revision = 'z4a5b6c7d8e9'
down_revision = 'y3z4a5b6c7d8'

def upgrade():
    op.add_column('hospitals', sa.Column('gstin', sa.String(), nullable=True))
    op.add_column('checkins', sa.Column('is_finalized', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('checkins', sa.Column('invoice_id', sa.Integer(), nullable=True))

    op.create_table(
        'invoices',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('checkin_id', sa.Integer(), sa.ForeignKey('checkins.id'), nullable=False, unique=True),
        sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('items_json', sa.Text(), nullable=False),
        sa.Column('grand_total', sa.Float(), nullable=False),
        sa.Column('generated_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
        sa.Column('generated_from', sa.String(), nullable=True),
        sa.Column('pdf_path', sa.String(), nullable=True),
        sa.Column('generated_at', sa.DateTime(), nullable=True),
    )

def downgrade():
    op.drop_table('invoices')
    op.drop_column('checkins', 'invoice_id')
    op.drop_column('checkins', 'is_finalized')
    op.drop_column('hospitals', 'gstin')