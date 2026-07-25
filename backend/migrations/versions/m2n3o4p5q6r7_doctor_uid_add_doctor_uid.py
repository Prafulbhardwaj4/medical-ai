"""add doctor_uid to doctors, matching patient_uid format"""
import secrets
import string
from alembic import op
import sqlalchemy as sa

revision = 'm2n3o4p5q6r7_doctor_uid'
down_revision = 'm2n3o4p5q6r7'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('doctors')}
    if 'doctor_uid' not in cols:
        op.add_column('doctors', sa.Column('doctor_uid', sa.String(), nullable=True))

    alphabet = string.ascii_uppercase + string.digits
    existing_uids = {row[0] for row in bind.execute(sa.text("SELECT doctor_uid FROM doctors WHERE doctor_uid IS NOT NULL"))}

    rows = bind.execute(sa.text("""
        SELECT d.id, h.hospital_code FROM doctors d
        LEFT JOIN hospitals h ON h.id = d.hospital_id
        WHERE d.doctor_uid IS NULL
    """))
    for doctor_id, hospital_code in rows:
        prefix = (hospital_code or "STAF").replace("-", "")[:4].upper()
        while True:
            suffix = "".join(secrets.choice(alphabet) for _ in range(6))
            uid = f"{prefix}-{suffix}"
            if uid not in existing_uids:
                existing_uids.add(uid)
                break
        bind.execute(sa.text("UPDATE doctors SET doctor_uid = :uid WHERE id = :id"), {"uid": uid, "id": doctor_id})


def downgrade():
    op.drop_column('doctors', 'doctor_uid')