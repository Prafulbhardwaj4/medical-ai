"""add doctor/admission professional fee fields"""
from alembic import op
import sqlalchemy as sa

revision = '801b4d923931'
down_revision = 'b4c5d6e7f8a9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    doctor_cols = {c['name'] for c in insp.get_columns('doctors')}
    if 'professional_fee_per_admission' not in doctor_cols:
        op.add_column('doctors', sa.Column('professional_fee_per_admission', sa.Float(), nullable=True))

    admission_cols = {c['name'] for c in insp.get_columns('admissions')}
    if 'professional_fee_override' not in admission_cols:
        op.add_column('admissions', sa.Column('professional_fee_override', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('admissions', 'professional_fee_override')
    op.drop_column('doctors', 'professional_fee_per_admission')