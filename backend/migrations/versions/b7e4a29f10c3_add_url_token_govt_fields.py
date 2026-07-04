"""add patient url_token, aadhaar/abha fields, hospital_type"""
from alembic import op
import sqlalchemy as sa
import secrets

revision = 'b7e4a29f10c3'
down_revision = 'e5f6a7b8c9d0'

def upgrade():
    op.add_column('patients', sa.Column('url_token', sa.String(), nullable=True))
    op.add_column('patients', sa.Column('aadhaar_number', sa.String(), nullable=True))
    op.add_column('patients', sa.Column('abha_number', sa.String(), nullable=True))
    op.add_column('hospitals', sa.Column('hospital_type', sa.String(), nullable=False, server_default='private'))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM patients")).fetchall()
    used = set()
    for row in rows:
        token = secrets.token_urlsafe(9)
        while token in used:
            token = secrets.token_urlsafe(9)
        used.add(token)
        conn.execute(sa.text("UPDATE patients SET url_token = :t WHERE id = :id"), {"t": token, "id": row[0]})

    op.alter_column('patients', 'url_token', nullable=False)
    op.create_index('ix_patients_url_token', 'patients', ['url_token'], unique=True)

def downgrade():
    op.drop_index('ix_patients_url_token', table_name='patients')
    op.drop_column('patients', 'url_token')
    op.drop_column('patients', 'aadhaar_number')
    op.drop_column('patients', 'abha_number')
    op.drop_column('hospitals', 'hospital_type')