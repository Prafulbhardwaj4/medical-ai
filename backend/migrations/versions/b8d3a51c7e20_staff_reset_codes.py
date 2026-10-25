"""staff_reset_codes: forgot-password codes for staff and hospital-admin accounts (new table only)"""
from alembic import op
import sqlalchemy as sa

revision = 'b8d3a51c7e20'
down_revision = '9e46b4471f3d'  # patient_reset_codes (the single current head)


def upgrade():
    insp = sa.inspect(op.get_bind())
    if 'staff_reset_codes' in set(insp.get_table_names()):
        return
    op.create_table(
        'staff_reset_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('code_hash', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_staff_reset_codes_id', 'staff_reset_codes', ['id'])
    op.create_index('ix_staff_reset_codes_doctor_created', 'staff_reset_codes', ['doctor_id', 'created_at'])


def downgrade():
    insp = sa.inspect(op.get_bind())
    if 'staff_reset_codes' in set(insp.get_table_names()):
        op.drop_table('staff_reset_codes')