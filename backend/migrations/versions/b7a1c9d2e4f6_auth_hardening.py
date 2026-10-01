"""auth hardening: password_changed_at on doctors + patient_accounts, server-side captcha table"""
from alembic import op
import sqlalchemy as sa

revision = 'b7a1c9d2e4f6'
down_revision = 'ce77303f5000'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    doctor_cols = {c['name'] for c in insp.get_columns('doctors')}
    if 'password_changed_at' not in doctor_cols:
        op.add_column('doctors', sa.Column('password_changed_at', sa.DateTime(), nullable=True))

    account_cols = {c['name'] for c in insp.get_columns('patient_accounts')}
    if 'password_changed_at' not in account_cols:
        op.add_column('patient_accounts', sa.Column('password_changed_at', sa.DateTime(), nullable=True))

    if 'captcha_challenges' not in insp.get_table_names():
        op.create_table(
            'captcha_challenges',
            sa.Column('id', sa.String(length=64), primary_key=True),
            sa.Column('answer', sa.String(length=16), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_captcha_challenges_expires_at', 'captcha_challenges', ['expires_at'])


def downgrade():
    op.drop_index('ix_captcha_challenges_expires_at', table_name='captcha_challenges')
    op.drop_table('captcha_challenges')
    op.drop_column('patient_accounts', 'password_changed_at')
    op.drop_column('doctors', 'password_changed_at')