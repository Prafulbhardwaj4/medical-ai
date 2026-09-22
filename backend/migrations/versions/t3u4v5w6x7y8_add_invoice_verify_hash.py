"""merge heads + add verify_hash to invoices (item 9)"""
from alembic import op
import sqlalchemy as sa

revision = 't3u4v5w6x7y8'
down_revision = ('q9r0s1t2u3v4', 's2t3u4v5w6x7')
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('invoices')}
    if 'verify_hash' not in cols:
        op.add_column('invoices', sa.Column('verify_hash', sa.String(), nullable=True))
        op.create_index('ix_invoices_verify_hash', 'invoices', ['verify_hash'], unique=True)


def downgrade():
    op.drop_index('ix_invoices_verify_hash', table_name='invoices')
    op.drop_column('invoices', 'verify_hash')