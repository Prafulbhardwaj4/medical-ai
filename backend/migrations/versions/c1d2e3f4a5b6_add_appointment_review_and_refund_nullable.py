"""add appointment approval workflow columns, fee snapshot, refund nullable fields"""
from alembic import op
import sqlalchemy as sa

revision = 'cf1068f09aaa'
down_revision = 'z8d9e0f1a2b3'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # New appointment status value for hospital-side review. Postgres native
    # enums require ADD VALUE outside a transaction block.
    if bind.dialect.name == 'postgresql':
        op.execute("COMMIT")
        op.execute("ALTER TYPE appointmentstatus ADD VALUE IF NOT EXISTS 'pending_review'")

    existing_cols = {c['name'] for c in insp.get_columns('portal_appointments')}
    if 'fee_amount' not in existing_cols:
        op.add_column('portal_appointments', sa.Column('fee_amount', sa.Float(), nullable=True))
    if 'review_deadline_at' not in existing_cols:
        op.add_column('portal_appointments', sa.Column('review_deadline_at', sa.DateTime(), nullable=True))
    if 'review_followup_sent_at' not in existing_cols:
        op.add_column('portal_appointments', sa.Column('review_followup_sent_at', sa.DateTime(), nullable=True))

    refund_cols = {c['name'] for c in insp.get_columns('refunds')}
    if 'patient_id' in refund_cols or 'processed_by' in refund_cols:
        # SQLite has no ALTER COLUMN at all — batch mode does the
        # copy-and-move it needs. Works fine on Postgres too (no table copy
        # needed there), so no dialect branch required.
        with op.batch_alter_table('refunds') as batch_op:
            if 'patient_id' in refund_cols:
                batch_op.alter_column('patient_id', existing_type=sa.Integer(), nullable=True)
            if 'processed_by' in refund_cols:
                batch_op.alter_column('processed_by', existing_type=sa.Integer(), nullable=True)


def downgrade():
    with op.batch_alter_table('refunds') as batch_op:
        batch_op.alter_column('processed_by', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('patient_id', existing_type=sa.Integer(), nullable=False)
    op.drop_column('portal_appointments', 'review_followup_sent_at')
    op.drop_column('portal_appointments', 'review_deadline_at')
    op.drop_column('portal_appointments', 'fee_amount')