"""add balance_collected fields to admissions"""
from alembic import op
import sqlalchemy as sa

revision = 'z4d5e6f7a8b9'
down_revision = 'z1a2b3c4d5e6'  # add_is_emergency_ward — adjust to your real current head (multiple heads still unmerged, see prior notes)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admissions')}
    if 'balance_collected' not in cols:
        op.add_column('admissions', sa.Column('balance_collected', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'balance_payment_method' not in cols:
        op.add_column('admissions', sa.Column('balance_payment_method', sa.String(), nullable=True))
    if 'balance_collected_at' not in cols:
        op.add_column('admissions', sa.Column('balance_collected_at', sa.DateTime(), nullable=True))
    if 'balance_collected_by' not in cols:
        if bind.dialect.name == 'sqlite':
            op.add_column('admissions', sa.Column('balance_collected_by', sa.Integer(), nullable=True))
        else:
            op.add_column('admissions', sa.Column('balance_collected_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True))


def downgrade():
    op.drop_column('admissions', 'balance_collected_by')
    op.drop_column('admissions', 'balance_collected_at')
    op.drop_column('admissions', 'balance_payment_method')
    op.drop_column('admissions', 'balance_collected')