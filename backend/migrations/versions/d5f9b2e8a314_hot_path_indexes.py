"""hot_path_indexes: additive indexes for queries the code runs on every screen.

Each index is created only if the table and columns exist and no index already starts with the same
columns, so it is safe to run on any database state. Nothing is dropped or rewritten.
Proof of use (filters in the routers/services): Patient.hospital_id (about 50 queries),
Appointment hospital/status/requested_time (about 25 each), Checkin hospital + visit_date (37),
AuditLog hospital + created_at, TestOrder hospital + status (about 30), Notification.hospital_id (16),
Admission hospital + status (about 20), Invoice.hospital_id, Consultation.patient_id (25) and .doctor_id (17).
(whatsapp_messages and blacklisted_tokens.token_hash already have the right indexes.)

If other migrations were added after d3b7e1f90a64, point down_revision at the newest one instead.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5f9b2e8a314'
down_revision = 'd3b7e1f90a64'
branch_labels = None
depends_on = None

INDEXES = [
    ('ix_patients_hospital_id', 'patients', ['hospital_id']),
    ('ix_portal_appointments_hospital_status_time', 'portal_appointments', ['hospital_id', 'status', 'requested_time']),
    ('ix_checkins_hospital_visit_date', 'checkins', ['hospital_id', 'visit_date']),
    ('ix_audit_logs_hospital_created_at', 'audit_logs', ['hospital_id', 'created_at']),
    ('ix_test_orders_hospital_status', 'test_orders', ['hospital_id', 'status']),
    ('ix_notifications_hospital_id', 'notifications', ['hospital_id']),
    ('ix_admissions_hospital_status', 'admissions', ['hospital_id', 'status']),
    ('ix_invoices_hospital_id', 'invoices', ['hospital_id']),
    ('ix_consultations_patient_id', 'consultations', ['patient_id']),
    ('ix_consultations_doctor_id', 'consultations', ['doctor_id']),
]


def upgrade():
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, cols in INDEXES:
        if table not in tables:
            continue
        if not set(cols) <= {c['name'] for c in insp.get_columns(table)}:
            continue
        existing = insp.get_indexes(table)
        if any(ix['name'] == name or list(ix['column_names'])[:len(cols)] == cols for ix in existing):
            continue
        op.create_index(name, table, cols)


def downgrade():
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, cols in INDEXES:
        if table in tables and name in {ix['name'] for ix in insp.get_indexes(table)}:
            op.drop_index(name, table_name=table)