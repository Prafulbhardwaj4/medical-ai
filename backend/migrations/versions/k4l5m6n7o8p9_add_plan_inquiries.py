"""add plan_inquiries

Revision ID: k4l5m6n7o8p9
Revises: z5e6f7a8b9c0
Create Date: 2026-09-13 00:00:00.000000

NOTE: down_revision below is a best-guess pick from several divergent heads
found in this migration history at the time this was written. Confirm with
`alembic heads` against your real environment before running — if it shows
a different current head, update down_revision to match before applying.
"""
from alembic import op
import sqlalchemy as sa

revision = "k4l5m6n7o8p9"
down_revision = "z5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plan_inquiries",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("requested_tier", sa.String(), nullable=False),
        sa.Column("billing_period", sa.String(), nullable=False),
        sa.Column("hospital_name", sa.String(), nullable=False),
        sa.Column("contact_name", sa.String(), nullable=False),
        sa.Column("contact_phone", sa.String(), nullable=False),
        sa.Column("contact_email", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("plan_inquiries")