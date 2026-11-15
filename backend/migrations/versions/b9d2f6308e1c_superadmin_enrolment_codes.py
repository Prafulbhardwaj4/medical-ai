"""superadmin_enrolment_codes: one-time codes for first-time super admin 2FA enrolment (new table only)"""
from alembic import op
import sqlalchemy as sa

revision = 'b9d2f6308e1c'
down_revision = 'a7c41e92d05b'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'superadmin_enrolment_codes' in insp.get_table_names():
        return
    op.create_table(
        'superadmin_enrolment_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('code_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('claimed_at', sa.DateTime(), nullable=True),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_superadmin_enrolment_codes_id', 'superadmin_enrolment_codes', ['id'])
    op.create_index('ix_superadmin_enrolment_codes_doctor_id', 'superadmin_enrolment_codes', ['doctor_id'])


def downgrade():
    pass