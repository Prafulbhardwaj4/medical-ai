"""reserve e-invoicing (IRN/QR) fields on invoices"""
from alembic import op
import sqlalchemy as sa

revision = 'f8a9b0c1d2e3'
down_revision = 'e7f8a9b0c1d2'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    invoice_cols = {c['name'] for c in insp.get_columns('invoices')}

    if 'irn' not in invoice_cols:
        op.add_column('invoices', sa.Column('irn', sa.String(), nullable=True))
    if 'irn_ack_no' not in invoice_cols:
        op.add_column('invoices', sa.Column('irn_ack_no', sa.String(), nullable=True))
    if 'irn_ack_date' not in invoice_cols:
        op.add_column('invoices', sa.Column('irn_ack_date', sa.DateTime(), nullable=True))
    if 'einvoice_qr_data' not in invoice_cols:
        op.add_column('invoices', sa.Column('einvoice_qr_data', sa.Text(), nullable=True))
    if 'einvoice_status' not in invoice_cols:
        op.add_column('invoices', sa.Column('einvoice_status', sa.String(), nullable=True))


def downgrade():
    op.drop_column('invoices', 'einvoice_status')
    op.drop_column('invoices', 'einvoice_qr_data')
    op.drop_column('invoices', 'irn_ack_date')
    op.drop_column('invoices', 'irn_ack_no')
    op.drop_column('invoices', 'irn')