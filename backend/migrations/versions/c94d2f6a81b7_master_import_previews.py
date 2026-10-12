"""master_import_previews: short-lived server-side preview store for the Super Admin master-list Excel upload (new table only)"""
from alembic import op
import sqlalchemy as sa

revision = 'c94d2f6a81b7'
down_revision = '7b3e9c41a2d8'  # master_catalogs (Phase 1)


def upgrade():
    insp = sa.inspect(op.get_bind())
    if 'master_import_previews' not in set(insp.get_table_names()):
        op.create_table(
            'master_import_previews',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('file_name', sa.String(), nullable=True),
            sa.Column('payload', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('consumed', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index('ix_master_import_previews_doctor_id', 'master_import_previews', ['doctor_id'])


def downgrade():
    insp = sa.inspect(op.get_bind())
    if 'master_import_previews' in set(insp.get_table_names()):
        op.drop_table('master_import_previews')