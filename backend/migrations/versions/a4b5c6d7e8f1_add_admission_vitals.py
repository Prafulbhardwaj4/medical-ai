"""add admission_vitals table

Nurse-recorded, timestamped IPD vitals log (item 49) — a "Vitals" card next
to Diagnosis on admission-detail.html, Record button nurse-only, readings
visible to everyone with page access. Distinct from OPD's single-blob
Checkin.vitals_data since admitted patients get vitals taken repeatedly.

Revision ID: a4b5c6d7e8f1
Revises: e1f2a3b4c5d6
Create Date: 2026-08-22 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'a4b5c6d7e8f1'
down_revision = 'e1f2a3b4c5d6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'admission_vitals' not in insp.get_table_names():
        op.create_table(
            'admission_vitals',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=False),
            sa.Column('recorded_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('data', sa.Text(), nullable=False),
            sa.Column('recorded_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table('admission_vitals')