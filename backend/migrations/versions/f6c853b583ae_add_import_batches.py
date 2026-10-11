"""excel import: import_batches, import_batch_items, import_previews (new tables only)"""
from alembic import op
import sqlalchemy as sa

revision = 'f6c853b583ae'
down_revision = 'm6f7a8b9c0d1'  # patient_suggestions - the single head when this was written; run `alembic heads` first


def upgrade():
    insp = sa.inspect(op.get_bind())
    existing = set(insp.get_table_names())
    if 'import_batches' not in existing:
        op.create_table(
            'import_batches',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
            sa.Column('created_by_name', sa.String(), nullable=True),
            sa.Column('created_by_role', sa.String(), nullable=True),
            sa.Column('file_name', sa.String(), nullable=True),
            sa.Column('status', sa.String(), nullable=False, server_default='applied'),
            sa.Column('summary', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('undone_at', sa.DateTime(), nullable=True),
            sa.Column('undone_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
        )
        op.create_index('ix_import_batches_id', 'import_batches', ['id'])
        op.create_index('ix_import_batches_hospital_id', 'import_batches', ['hospital_id'])
    if 'import_batch_items' not in existing:
        op.create_table(
            'import_batch_items',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('batch_id', sa.Integer(), sa.ForeignKey('import_batches.id'), nullable=False),
            sa.Column('entity', sa.String(), nullable=False),
            sa.Column('entity_id', sa.Integer(), nullable=False),
            sa.Column('action', sa.String(), nullable=False),
            sa.Column('before_json', sa.Text(), nullable=True),
            sa.Column('after_json', sa.Text(), nullable=True),
        )
        op.create_index('ix_import_batch_items_id', 'import_batch_items', ['id'])
        op.create_index('ix_import_batch_items_batch_id', 'import_batch_items', ['batch_id'])
    if 'import_previews' not in existing:
        op.create_table(
            'import_previews',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('file_name', sa.String(), nullable=True),
            sa.Column('payload', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('consumed', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index('ix_import_previews_hospital_id', 'import_previews', ['hospital_id'])


def downgrade():
    op.drop_table('import_previews')
    op.drop_table('import_batch_items')
    op.drop_table('import_batches')