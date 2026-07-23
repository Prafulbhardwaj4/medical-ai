"""add public_token to admissions (opaque, non-enumerable ID for URLs)"""
import secrets
from alembic import op
import sqlalchemy as sa

revision = 'j9k0l1m2n3o4'
down_revision = 'i8j9k0l1m2n3'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    is_sqlite = bind.dialect.name == 'sqlite'
    cols = {c['name'] for c in insp.get_columns('admissions')}
    if 'public_token' not in cols:
        op.add_column('admissions', sa.Column('public_token', sa.String(), nullable=True))

    # backfill existing rows
    result = bind.execute(sa.text("SELECT id FROM admissions WHERE public_token IS NULL"))
    for row in result:
        token = secrets.token_urlsafe(16)
        bind.execute(sa.text("UPDATE admissions SET public_token = :token WHERE id = :id"), {"token": token, "id": row[0]})

    if is_sqlite:
        with op.batch_alter_table('admissions') as batch_op:
            batch_op.create_unique_constraint('uq_admissions_public_token', ['public_token'])
            batch_op.alter_column('public_token', nullable=False)
    else:
        op.create_unique_constraint('uq_admissions_public_token', 'admissions', ['public_token'])
        op.alter_column('admissions', 'public_token', nullable=False)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('admissions') as batch_op:
            batch_op.drop_constraint('uq_admissions_public_token', type_='unique')
            batch_op.drop_column('public_token')
    else:
        op.drop_constraint('uq_admissions_public_token', 'admissions', type_='unique')
        op.drop_column('admissions', 'public_token')