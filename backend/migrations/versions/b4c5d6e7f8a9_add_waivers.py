"""add waiver_requests table and hospital waiver settings"""
from alembic import op
import sqlalchemy as sa

revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    hospital_cols = {c['name'] for c in insp.get_columns('hospitals')}
    if 'waiver_auto_approve_cap' not in hospital_cols:
        op.add_column('hospitals', sa.Column('waiver_auto_approve_cap', sa.Float(), nullable=True))
    if 'waiver_requests' in insp.get_table_names():
        return
    if 'waiver_auto_approve_percent' not in hospital_cols:
        op.add_column('hospitals', sa.Column('waiver_auto_approve_percent', sa.Float(), nullable=True))

    if 'waiver_requests' not in insp.get_table_names():
        op.create_table(
            'waiver_requests',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('checkin_id', sa.Integer(), sa.ForeignKey('checkins.id'), nullable=True),
            sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=True),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('reason', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='approved'),
            sa.Column('requested_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('resolved_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
            sa.Column('requested_at', sa.DateTime(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
            sa.Column('charge_id', sa.Integer(), nullable=True),
        )
        # No separate create_index needed — sa.Column('id', ..., index=True)
        # above already creates it as part of create_table.


def downgrade():
    op.drop_table('waiver_requests')
    op.drop_column('hospitals', 'waiver_auto_approve_percent')
    op.drop_column('hospitals', 'waiver_auto_approve_cap')