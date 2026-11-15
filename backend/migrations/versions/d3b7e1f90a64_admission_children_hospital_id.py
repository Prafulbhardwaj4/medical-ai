"""admission children: add hospital_id (nullable, indexed) and backfill it from the parent admission.

Additive only. Nothing is deleted or rewritten except filling empty hospital_id values. Safe to re-run.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd3b7e1f90a64'
down_revision = 'c4e8a1d7f203'
branch_labels = None
depends_on = None

BY_ADMISSION = [
    'admission_medication_orders', 'admission_medication_returns', 'admission_charges',
    'admission_consents', 'admission_deposits', 'admission_deposit_topup_requests',
    'admission_progress_notes', 'admission_vitals', 'admission_ward_stays',
]
BY_ORDER = ['admission_medication_administrations', 'admission_medication_dispenses']


def _ix(table):
    return f'ix_{table}_hospital_id'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table in BY_ADMISSION + BY_ORDER:
        if table not in tables:
            continue
        cols = {c['name'] for c in insp.get_columns(table)}
        if 'hospital_id' not in cols:
            op.add_column(table, sa.Column('hospital_id', sa.Integer(), nullable=True))
            if bind.dialect.name == 'postgresql':
                op.create_foreign_key(f'fk_{table}_hospital_id', table, 'hospitals', ['hospital_id'], ['id'])
        if _ix(table) not in {i['name'] for i in sa.inspect(bind).get_indexes(table)}:
            op.create_index(_ix(table), table, ['hospital_id'])
    for table in BY_ADMISSION:
        if table in tables:
            bind.execute(sa.text(
                f"UPDATE {table} SET hospital_id = "
                f"(SELECT a.hospital_id FROM admissions a WHERE a.id = {table}.admission_id) "
                f"WHERE hospital_id IS NULL"
            ))
    if 'admission_medication_orders' in tables:
        for table in BY_ORDER:
            if table in tables:
                bind.execute(sa.text(
                    f"UPDATE {table} SET hospital_id = "
                    f"(SELECT a.hospital_id FROM admission_medication_orders o "
                    f"JOIN admissions a ON a.id = o.admission_id WHERE o.id = {table}.order_id) "
                    f"WHERE hospital_id IS NULL"
                ))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table in BY_ADMISSION + BY_ORDER:
        if table not in tables:
            continue
        if _ix(table) in {i['name'] for i in insp.get_indexes(table)}:
            op.drop_index(_ix(table), table_name=table)
        if 'hospital_id' in {c['name'] for c in insp.get_columns(table)}:
            with op.batch_alter_table(table) as batch:
                batch.drop_column('hospital_id')