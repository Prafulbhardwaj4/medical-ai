"""temp_password_expiry: temporary passwords expire after 7 days (nullable column on doctors and patient_accounts)

NULL means no expiry, so every existing account keeps working. Idempotent (startup schema sync may have added them).
"""
from alembic import op
import sqlalchemy as sa

revision = '504a0c891593'
down_revision = 'd7aa0a17554e'
branch_labels = None
depends_on = None


def _has_column(table, column):
    insp = sa.inspect(op.get_bind())
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade():
    for table in ('doctors', 'patient_accounts'):
        if not _has_column(table, 'temp_password_expires_at'):
            op.add_column(table, sa.Column('temp_password_expires_at', sa.DateTime(), nullable=True))


def downgrade():
    for table in ('doctors', 'patient_accounts'):
        if _has_column(table, 'temp_password_expires_at'):
            op.drop_column(table, 'temp_password_expires_at')