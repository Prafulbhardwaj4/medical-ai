"""blacklisted_tokens: store a SHA-256 hash instead of the raw token (additive; old rows are backfilled and kept)"""
import hashlib

from alembic import op
import sqlalchemy as sa

revision = 'a7c41e92d05b'
down_revision = '3e8a1f5c9b27'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'blacklisted_tokens' not in insp.get_table_names():
        return

    cols = {c['name'] for c in insp.get_columns('blacklisted_tokens')}
    if 'token_hash' not in cols:
        op.add_column('blacklisted_tokens', sa.Column('token_hash', sa.String(64), nullable=True))

    rows = bind.execute(sa.text(
        "SELECT id, token FROM blacklisted_tokens WHERE token_hash IS NULL AND token IS NOT NULL"
    )).fetchall()
    for row_id, raw in rows:
        bind.execute(
            sa.text("UPDATE blacklisted_tokens SET token_hash = :h WHERE id = :i"),
            {"h": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "i": row_id},
        )

    existing_indexes = {i['name'] for i in sa.inspect(bind).get_indexes('blacklisted_tokens')}
    if 'ix_blacklisted_tokens_token_hash' not in existing_indexes:
        op.create_index('ix_blacklisted_tokens_token_hash', 'blacklisted_tokens', ['token_hash'], unique=True)

    # New rows no longer store the raw token, so the old column must accept NULL.
    op.alter_column('blacklisted_tokens', 'token', existing_type=sa.String(), nullable=True)


def downgrade():
    pass