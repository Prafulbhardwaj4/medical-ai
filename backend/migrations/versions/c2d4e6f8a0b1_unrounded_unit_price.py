"""C2: store catalog unit price unrounded (price_per_pack / pack_size) so a full strip bills exactly MRP.
Existing MedicineOrder.unit_price values are NOT touched - they are frozen on past bills."""
from alembic import op

revision = 'c2d4e6f8a0b1'
down_revision = 'b7a1c9d2e4f6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE hospital_medicines SET price = price_per_pack * 1.0 / pack_size "
        "WHERE price_per_pack IS NOT NULL AND pack_size IS NOT NULL AND pack_size >= 1"
    )


def downgrade():
    op.execute(
        "UPDATE hospital_medicines SET price = ROUND(CAST(price_per_pack * 1.0 / pack_size AS NUMERIC), 2) "
        "WHERE price_per_pack IS NOT NULL AND pack_size IS NOT NULL AND pack_size >= 1"
    )