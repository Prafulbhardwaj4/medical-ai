"""shift_utc_timestamps_to_ist

Revision ID: f3a1b9c8d2e7
Revises: d3f6a1b2c9e4
Create Date: 2026-07-17 00:00:00.000000

Data-only migration. Application code now writes every timestamp as IST-naive
(see app/utils/timezone.now_ist_naive). This shifts EXISTING rows that were
written under the old datetime.utcnow() convention forward by +5:30 so
historical data lines up with the new convention. Columns that were already
being written as IST (checkins.created_at, checkins.vitals_recorded_at,
checkins.post_consult_recorded_at, attendance_records.shift_started_at,
consultations.dispensed_at, medicine_orders.dispensed_at,
blacklisted_tokens.blacklisted_at) are deliberately NOT touched here.

attendance_records.created_at is also deliberately NOT touched — it was a
mixed-convention column (see audit notes) and a blanket shift would corrupt
rows that were already IST. Left for manual/no-op.
"""
from alembic import op

revision = 'f3a1b9c8d2e7'
down_revision = 'd3f6a1b2c9e4'
branch_labels = None
depends_on = None

# (table, column) pairs that were always written via datetime.utcnow()
SHIFT_TARGETS = [
    ("doctors", "created_at"),
    ("doctors", "locked_until"),
    ("patients", "created_at"),
    ("hospitals", "created_at"),
    ("consultations", "created_at"),
    ("test_orders", "created_at"),
    ("test_orders", "paid_at"),
    ("test_orders", "queued_at"),
    ("test_orders", "collected_at"),
    ("test_orders", "completed_at"),
    ("medicine_orders", "created_at"),
    ("medicine_orders", "paid_at"),
    ("medicine_orders", "queued_at"),
    ("checkins", "paid_at"),
    ("hospital_medicines", "created_at"),
    ("medicine_batches", "created_at"),
    ("invoices", "generated_at"),
    ("test_catalog_items", "created_at"),
    ("test_catalog_parameters", "created_at"),
    ("notifications", "created_at"),
    ("notifications", "updated_at"),
]


def _shift(direction: str):
    bind = op.get_bind()
    dialect = bind.dialect.name
    for table, column in SHIFT_TARGETS:
        if dialect == "sqlite":
            sign_hours = "+5 hours" if direction == "forward" else "-5 hours"
            sign_mins = "+30 minutes" if direction == "forward" else "-30 minutes"
            op.execute(
                f"UPDATE {table} SET {column} = datetime({column}, '{sign_hours}', '{sign_mins}') "
                f"WHERE {column} IS NOT NULL"
            )
        else:  # postgresql
            op_sign = "+" if direction == "forward" else "-"
            op.execute(
                f"UPDATE {table} SET {column} = {column} {op_sign} interval '5 hours 30 minutes' "
                f"WHERE {column} IS NOT NULL"
            )


def upgrade() -> None:
    _shift("forward")


def downgrade() -> None:
    _shift("backward")