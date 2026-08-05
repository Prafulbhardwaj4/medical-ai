"""add admission_progress_notes table"""
from alembic import op
import sqlalchemy as sa

revision = 'd7e6f5a4b3c2'
down_revision = 'c8d7e6f5a4b3'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'admission_progress_notes' not in insp.get_table_names():
        op.create_table(
            'admission_progress_notes',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=False),
            sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('note', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table('admission_progress_notes')