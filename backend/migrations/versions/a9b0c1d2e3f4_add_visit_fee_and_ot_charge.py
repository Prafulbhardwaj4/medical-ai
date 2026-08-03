"""add doctor visit fee and OT ward-type fields"""
from alembic import op
import sqlalchemy as sa

revision = 'a9b0c1d2e3f4'
down_revision = 'f8a9b0c1d2e3'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    doctor_cols = {c['name'] for c in insp.get_columns('doctors')}
    if 'visit_fee' not in doctor_cols:
        op.add_column('doctors', sa.Column('visit_fee', sa.Float(), nullable=True))

    ward_type_cols = {c['name'] for c in insp.get_columns('admission_ward_types')}
    if 'is_ot' not in ward_type_cols:
        op.add_column('admission_ward_types', sa.Column('is_ot', sa.Boolean(), nullable=False, server_default='false'))
    if 'ot_charge' not in ward_type_cols:
        op.add_column('admission_ward_types', sa.Column('ot_charge', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('admission_ward_types', 'ot_charge')
    op.drop_column('admission_ward_types', 'is_ot')
    op.drop_column('doctors', 'visit_fee')