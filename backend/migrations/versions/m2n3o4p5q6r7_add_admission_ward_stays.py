"""add admission_ward_stays table (per-ward billing segments)"""
from alembic import op
import sqlalchemy as sa

revision = 'm2n3o4p5q6r7'
down_revision = 'l1m2n3o4p5q6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'admission_ward_stays' not in insp.get_table_names():
        op.create_table(
            'admission_ward_stays',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=False),
            sa.Column('ward_type_id', sa.Integer(), sa.ForeignKey('admission_ward_types.id'), nullable=True),
            sa.Column('ward_name', sa.String(), nullable=False),
            sa.Column('bed_number', sa.String(), nullable=False),
            sa.Column('daily_charge', sa.Float(), nullable=False, server_default='0'),
            sa.Column('start_date', sa.DateTime(), nullable=False),
            sa.Column('end_date', sa.DateTime(), nullable=True),
            sa.Column('changed_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    # Backfill: give every existing admission one open (or closed, if discharged)
    # segment matching its current ward/bed/rate, starting at its admission_date —
    # so the new per-segment billing logic has data to sum for stays that started
    # before this migration ran.
    conn = op.get_bind()
    existing = conn.execute(sa.text(
        "SELECT id, ward, bed_number, daily_room_charge, ward_type_id, admission_date, discharge_date FROM admissions"
    )).fetchall()
    for row in existing:
        already = conn.execute(
            sa.text("SELECT COUNT(*) FROM admission_ward_stays WHERE admission_id = :aid"),
            {"aid": row.id}
        ).scalar()
        if already:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO admission_ward_stays "
                "(admission_id, ward_type_id, ward_name, bed_number, daily_charge, start_date, end_date) "
                "VALUES (:aid, :wtid, :ward, :bed, :charge, :start, :end)"
            ),
            {
                "aid": row.id, "wtid": row.ward_type_id, "ward": row.ward, "bed": row.bed_number,
                "charge": row.daily_room_charge, "start": row.admission_date, "end": row.discharge_date,
            }
        )


def downgrade():
    op.drop_table('admission_ward_stays')