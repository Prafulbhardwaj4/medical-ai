"""consent_records table"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f7'
down_revision = 'e5f6a7b8c9d1'   # run `alembic heads`; it must show this single head before you paste
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if 'consent_records' not in insp.get_table_names():
        op.create_table(
            'consent_records',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=True),
            sa.Column('subject_type', sa.String(), nullable=False),
            sa.Column('subject_id', sa.Integer(), nullable=False),
            sa.Column('purpose', sa.String(), nullable=False),
            sa.Column('notice_version', sa.String(), nullable=False),
            sa.Column('recorded_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_consent_records_subject_id', 'consent_records', ['subject_id'])
        op.create_index('ix_consent_records_hospital_id', 'consent_records', ['hospital_id'])


def downgrade():
    op.drop_table('consent_records')