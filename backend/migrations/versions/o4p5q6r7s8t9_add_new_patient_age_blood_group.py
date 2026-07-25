"""add new_patient_age/new_patient_blood_group to portal_appointments"""
from alembic import op
import sqlalchemy as sa

revision = 'o4p5q6r7s8t9'
down_revision = 'n3o4p5q6r7s8_chat_attachments'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('portal_appointments')}
    if 'new_patient_age' not in cols:
        op.add_column('portal_appointments', sa.Column('new_patient_age', sa.Integer(), nullable=True))
    if 'new_patient_blood_group' not in cols:
        op.add_column('portal_appointments', sa.Column('new_patient_blood_group', sa.String(), nullable=True))


def downgrade():
    op.drop_column('portal_appointments', 'new_patient_blood_group')
    op.drop_column('portal_appointments', 'new_patient_age')