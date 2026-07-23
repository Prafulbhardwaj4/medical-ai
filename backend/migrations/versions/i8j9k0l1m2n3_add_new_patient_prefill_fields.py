"""add new_patient_name/gender to portal_appointments"""
from alembic import op
import sqlalchemy as sa

revision = 'i8j9k0l1m2n3'
down_revision = 'h7i8j9k0l1m2'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('portal_appointments')}
    if 'new_patient_name' not in cols:
        op.add_column('portal_appointments', sa.Column('new_patient_name', sa.String(), nullable=True))
    if 'new_patient_gender' not in cols:
        op.add_column('portal_appointments', sa.Column('new_patient_gender', sa.String(), nullable=True))


def downgrade():
    op.drop_column('portal_appointments', 'new_patient_gender')
    op.drop_column('portal_appointments', 'new_patient_name')