"""add visit_feedback and portal_suggestions tables"""
from alembic import op
import sqlalchemy as sa

revision = 'a813d4e7fd7b'
down_revision = 'b1c2d3e4f5a6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'visit_feedback' not in existing_tables:
        op.create_table(
            'visit_feedback',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('checkin_id', sa.Integer(), sa.ForeignKey('checkins.id'), nullable=False, unique=True),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('rating', sa.Integer(), nullable=False),
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    if 'portal_suggestions' not in existing_tables:
        op.create_table(
            'portal_suggestions',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('patient_accounts.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=True),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table('portal_suggestions')
    op.drop_table('visit_feedback')