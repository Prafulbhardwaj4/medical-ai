"""add GST fields to hospitals and invoices"""
from alembic import op
import sqlalchemy as sa

revision = 'w4x5y6z7a8b9'
down_revision = 'v3w4x5y6z7a8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    hospital_cols = {c['name'] for c in insp.get_columns('hospitals')}
    if 'consultation_gst_percent' not in hospital_cols:
        op.add_column('hospitals', sa.Column('consultation_gst_percent', sa.Float(), nullable=True))
    if 'test_gst_percent' not in hospital_cols:
        op.add_column('hospitals', sa.Column('test_gst_percent', sa.Float(), nullable=True))
    if 'room_gst_percent' not in hospital_cols:
        op.add_column('hospitals', sa.Column('room_gst_percent', sa.Float(), nullable=True))
    if 'charge_gst_percent' not in hospital_cols:
        op.add_column('hospitals', sa.Column('charge_gst_percent', sa.Float(), nullable=True))
    if 'room_gst_threshold_per_day' not in hospital_cols:
        op.add_column('hospitals', sa.Column('room_gst_threshold_per_day', sa.Float(), nullable=False, server_default='5000.0'))

    invoice_cols = {c['name'] for c in insp.get_columns('invoices')}
    if 'subtotal' not in invoice_cols:
        op.add_column('invoices', sa.Column('subtotal', sa.Float(), nullable=True))
    if 'gst_total' not in invoice_cols:
        op.add_column('invoices', sa.Column('gst_total', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('invoices', 'gst_total')
    op.drop_column('invoices', 'subtotal')
    op.drop_column('hospitals', 'room_gst_threshold_per_day')
    op.drop_column('hospitals', 'charge_gst_percent')
    op.drop_column('hospitals', 'room_gst_percent')
    op.drop_column('hospitals', 'test_gst_percent')
    op.drop_column('hospitals', 'consultation_gst_percent')