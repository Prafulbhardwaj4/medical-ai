"""add credit_debit_notes table"""
from alembic import op
import sqlalchemy as sa

revision = 'a3b4c5d6e7f8'
down_revision = 'f4a5b6c7d8e9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'credit_debit_notes' in insp.get_table_names():
        return
    op.create_table(
        'credit_debit_notes',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('invoice_id', sa.Integer(), sa.ForeignKey('invoices.id'), nullable=False),
        sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('note_type', sa.String(), nullable=False),
        sa.Column('note_number', sa.String(), nullable=False),
        sa.Column('invoice_number', sa.String(), nullable=True),
        sa.Column('invoice_date', sa.DateTime(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('refund_id', sa.Integer(), sa.ForeignKey('refunds.id'), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_credit_debit_notes_note_number', 'credit_debit_notes', ['note_number'], unique=True)
    # No separate index for 'id' needed — sa.Column('id', ..., index=True)
    # above already creates it.


def downgrade():
    op.drop_index('ix_credit_debit_notes_note_number', table_name='credit_debit_notes')
    op.drop_table('credit_debit_notes')