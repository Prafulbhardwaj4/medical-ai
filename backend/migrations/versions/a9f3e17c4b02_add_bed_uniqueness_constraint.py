"""add bed uniqueness constraint for active admissions

Revision ID: a9f3e17c4b02
Revises: 2785c745c6ac
Create Date: 2026-08-08 00:00:00.000000

The emergency-admit bed-assignment retry loop catches IntegrityError to
handle two simultaneous emergency admissions racing onto the same bed —
but there was no actual constraint at the database level to trigger that
error, making the retry loop a no-op. This adds a partial unique index on
(ward_type_id, bed_number) scoped to status = 'admitted' only, so two
active admissions can never share a bed in the same ward type, while a
bed number is still freely reusable once the earlier admission discharges.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a9f3e17c4b02'
down_revision = '2785c745c6ac'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'uq_admission_bed_active',
        'admissions',
        ['ward_type_id', 'bed_number'],
        unique=True,
        postgresql_where=sa.text("status = 'admitted'"),
        sqlite_where=sa.text("status = 'admitted'"),
    )


def downgrade() -> None:
    op.drop_index('uq_admission_bed_active', table_name='admissions')