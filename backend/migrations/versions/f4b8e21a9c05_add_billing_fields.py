"""add billing fields, billing_enabled flag, and per-doctor consultation fee"""
from alembic import op
import sqlalchemy as sa

revision = 'f4b8e21a9c05'
down_revision = 'c8f2b6a41d90'

def upgrade():
    op.add_column('hospitals', sa.Column('billing_enabled', sa.Boolean(), nullable=False, server_default='1'))
    op.add_column('hospitals', sa.Column('default_consultation_fee', sa.Float(), nullable=True))

    op.add_column('doctors', sa.Column('consultation_fee', sa.Float(), nullable=True))

    op.add_column('checkins', sa.Column('consultation_fee', sa.Float(), nullable=True))
    op.add_column('checkins', sa.Column('test_fee', sa.Float(), nullable=True))
    op.add_column('checkins', sa.Column('is_paid', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('checkins', sa.Column('paid_at', sa.DateTime(), nullable=True))

    # Retroactively turn billing off for existing government hospitals (new hospitals
    # get this decided at creation time in admin.py; this just backfills existing rows).
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE hospitals SET billing_enabled = 0 WHERE hospital_type = 'government'"))

def downgrade():
    op.drop_column('checkins', 'paid_at')
    op.drop_column('checkins', 'is_paid')
    op.drop_column('checkins', 'test_fee')
    op.drop_column('checkins', 'consultation_fee')
    op.drop_column('doctors', 'consultation_fee')
    op.drop_column('hospitals', 'default_consultation_fee')
    op.drop_column('hospitals', 'billing_enabled')