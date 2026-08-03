"""add invoice_sequences table for atomic FY-scoped numbering"""
from alembic import op
import sqlalchemy as sa

revision = 'e7f8a9b0c1d2'
down_revision = 'd6e7f8a9b0c1'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'invoice_sequences' in insp.get_table_names():
        return
    op.create_table(
        'invoice_sequences',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('sequence_type', sa.String(), nullable=False),
        sa.Column('financial_year', sa.String(), nullable=False),
        sa.Column('last_number', sa.Integer(), nullable=False, server_default='0'),
    )
    # No separate index for 'id' needed — sa.Column('id', ..., index=True)
    # above already creates it.
    with op.batch_alter_table('invoice_sequences') as batch_op:
        batch_op.create_unique_constraint('uq_invoice_sequence', ['hospital_id', 'sequence_type', 'financial_year'])


def downgrade():
    with op.batch_alter_table('invoice_sequences') as batch_op:
        batch_op.drop_constraint('uq_invoice_sequence', type_='unique')
    op.drop_table('invoice_sequences')