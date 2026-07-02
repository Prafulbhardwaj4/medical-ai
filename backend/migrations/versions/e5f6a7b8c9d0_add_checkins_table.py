"""add checkins table"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'

def upgrade():
    op.create_table(
        'checkins',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('token_number', sa.String(), nullable=False, unique=True),
        sa.Column('issue_category', sa.String(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('visit_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_checkins_token_number', 'checkins', ['token_number'])
    op.create_index('ix_checkins_visit_date', 'checkins', ['visit_date'])

def downgrade():
    op.drop_table('checkins')