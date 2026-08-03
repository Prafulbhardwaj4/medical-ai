"""add HSN/SAC codes and place of supply fields"""
from alembic import op
import sqlalchemy as sa

revision = 'd6e7f8a9b0c1'
down_revision = 'c5d6e7f8a9b0'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    hospital_cols = {c['name'] for c in insp.get_columns('hospitals')}
    for col in ('hsn_consultation', 'hsn_room', 'hsn_test', 'hsn_charge'):
        if col not in hospital_cols:
            op.add_column('hospitals', sa.Column(col, sa.String(), nullable=True))

    invoice_cols = {c['name'] for c in insp.get_columns('invoices')}
    if 'place_of_supply' not in invoice_cols:
        op.add_column('invoices', sa.Column('place_of_supply', sa.String(), nullable=True))

    medicine_cols = {c['name'] for c in insp.get_columns('hospital_medicines')}
    if 'hsn_code' not in medicine_cols:
        op.add_column('hospital_medicines', sa.Column('hsn_code', sa.String(), nullable=True))


def downgrade():
    op.drop_column('hospital_medicines', 'hsn_code')
    op.drop_column('invoices', 'place_of_supply')
    for col in ('hsn_charge', 'hsn_test', 'hsn_room', 'hsn_consultation'):
        op.drop_column('hospitals', col)