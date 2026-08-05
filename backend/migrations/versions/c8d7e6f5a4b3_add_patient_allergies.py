"""add patient_allergies table"""
from alembic import op
import sqlalchemy as sa

revision = 'c8d7e6f5a4b3'
down_revision = 'b9c8d7e6f5a4'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'patient_allergies' not in insp.get_table_names():
        op.create_table(
            'patient_allergies',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('allergen', sa.String(), nullable=False),
            sa.Column('reaction', sa.Text(), nullable=True),
            sa.Column('severity', sa.String(), nullable=False, server_default='moderate'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('noted_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('noted_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table('patient_allergies')