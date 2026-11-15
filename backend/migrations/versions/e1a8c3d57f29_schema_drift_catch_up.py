"""schema_drift_catch_up: the table and columns the app used to add itself at start-up.

A database built only from the migrations was missing the admission_rooms table, hospitals.tier,
consultations.ai_scribe_credit_consumed and admission_medication_orders.order_batch_id (the app's
RUNTIME_SCHEMA_SYNC added them when it started). This migration adds each one only if it is missing,
with the same default the app used, so it is safe on a live database that already has them and on a
brand new one. Nothing is dropped, renamed or rewritten, and downgrade does nothing on purpose.

After it has run on production, `python scripts/check_schema_drift.py` should print OK, and
RUNTIME_SCHEMA_SYNC can be switched off.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1a8c3d57f29'
down_revision = 'd5f9b2e8a314'
branch_labels = None
depends_on = None


def _columns(insp, table):
    return {c['name'] for c in insp.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # hospitals.tier (existing hospitals become "foundation", the same as before)
    if 'hospitals' in tables and 'tier' not in _columns(insp, 'hospitals'):
        op.add_column('hospitals', sa.Column('tier', sa.String(), nullable=False, server_default='foundation'))

    # consultations.ai_scribe_credit_consumed (existing consultations count as "not charged")
    if 'consultations' in tables and 'ai_scribe_credit_consumed' not in _columns(insp, 'consultations'):
        op.add_column('consultations', sa.Column('ai_scribe_credit_consumed', sa.Boolean(), nullable=True, server_default=sa.false()))

    # admission_medication_orders.order_batch_id (+ the index the model declares)
    if 'admission_medication_orders' in tables:
        if 'order_batch_id' not in _columns(insp, 'admission_medication_orders'):
            op.add_column('admission_medication_orders', sa.Column('order_batch_id', sa.String(), nullable=True))
        existing = insp.get_indexes('admission_medication_orders')
        if not any(list(ix['column_names'])[:1] == ['order_batch_id'] for ix in existing):
            op.create_index('ix_admission_medication_orders_order_batch_id', 'admission_medication_orders', ['order_batch_id'])

    # admission_rooms
    if 'admission_rooms' not in tables and {'hospitals', 'admission_ward_types'} <= tables:
        op.create_table(
            'admission_rooms',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('ward_type_id', sa.Integer(), sa.ForeignKey('admission_ward_types.id'), nullable=False),
            sa.Column('room_number', sa.String(), nullable=False),
            sa.Column('room_name', sa.String(), nullable=True),
            sa.Column('room_type', sa.String(), nullable=False, server_default='general'),
            sa.Column('daily_charge', sa.Float(), nullable=True),
            sa.Column('beds_count', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_admission_rooms_id', 'admission_rooms', ['id'])


def downgrade():
    # Intentionally empty: these were added to match the code, and removing them could lose data.
    pass