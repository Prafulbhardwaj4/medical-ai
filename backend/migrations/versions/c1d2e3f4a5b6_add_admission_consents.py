"""add admission_consents table"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'b0c1d2e3f4a5'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'admission_consents' in insp.get_table_names():
        # Already created by an earlier run that got partway through before
        # failing (SQLite DDL here isn't transactional, so a mid-migration
        # crash leaves the table behind without alembic recording this
        # revision as applied).
        return
    op.create_table(
        'admission_consents',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=False),
        sa.Column('consent_type', sa.String(), nullable=False),
        sa.Column('signer_name', sa.String(), nullable=False),
        sa.Column('signed_by_guardian', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('relationship', sa.String(), nullable=True),
        sa.Column('witness_name', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('recorded_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('signed_at', sa.DateTime(), nullable=True),
    )
    # No separate create_index needed — sa.Column('id', ..., index=True)
    # above already creates it as part of create_table.


def downgrade():
    op.drop_table('admission_consents')