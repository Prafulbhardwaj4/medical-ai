"""A database built only from the migrations must have everything the models expect.

The SQLite tests run everywhere. The PostgreSQL test builds a fresh database from the migrations inside a
throw-away schema and runs when MEDSCRIBE_TEST_PG_URL is set (the CI workflow sets it).
"""
import importlib.util
import os

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic import command as alembic_command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401  (importing the app registers every model)
from app.database import Base
from app.models.hospital import Hospital

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
MIGRATION = os.path.join(BACKEND, "migrations", "versions", "e1a8c3d57f29_schema_drift_catch_up.py")
SCRIPT = os.path.join(BACKEND, "scripts", "check_schema_drift.py")
PG_URL = os.environ.get("MEDSCRIBE_TEST_PG_URL", "")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


drift = _load("check_schema_drift_under_test", SCRIPT)


def _engine():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


def _make_it_like_an_old_migrations_only_database(engine):
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE admission_rooms"))
        conn.execute(sa.text("DROP INDEX ix_admission_medication_orders_order_batch_id"))
        for table, col in [("hospitals", "tier"), ("consultations", "ai_scribe_credit_consumed"),
                           ("admission_medication_orders", "order_batch_id")]:
            conn.execute(sa.text(f'ALTER TABLE {table} DROP COLUMN {col}'))


def _run_migration(engine):
    mod = _load("p11_drift_migration", MIGRATION)
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
    return mod


def test_no_drift_when_the_database_matches_the_models():
    assert drift.find_drift(_engine(), Base.metadata) == []


def test_drift_lists_every_missing_table_and_column():
    engine = _engine()
    _make_it_like_an_old_migrations_only_database(engine)
    assert drift.find_drift(engine, Base.metadata) == [
        "missing column admission_medication_orders.order_batch_id",
        "missing table admission_rooms",
        "missing column consultations.ai_scribe_credit_consumed",
        "missing column hospitals.tier",
    ]


def test_migration_fills_the_gaps_and_is_safe_to_run_twice():
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(Hospital.__table__.insert().values(name="Old Hospital", hospital_code="OLD1"))
    _make_it_like_an_old_migrations_only_database(engine)
    mod = _run_migration(engine)
    assert drift.find_drift(engine, Base.metadata) == []
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT tier FROM hospitals WHERE hospital_code='OLD1'")).scalar() == "foundation"
    _run_migration(engine)  # already there: nothing happens, nothing fails
    assert drift.find_drift(engine, Base.metadata) == []
    mod.downgrade()  # does nothing on purpose
    assert drift.find_drift(engine, Base.metadata) == []


def test_migration_leaves_existing_rows_and_columns_alone():
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(Hospital.__table__.insert().values(name="Scale Hospital", hospital_code="SC1", tier="scale"))
    _run_migration(engine)
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT tier FROM hospitals WHERE hospital_code='SC1'")).scalar() == "scale"


def test_the_migration_is_chained_from_the_single_head():
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(BACKEND, "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1
    rev = script.get_revision("e1a8c3d57f29")
    assert rev is not None and rev.down_revision == "d5f9b2e8a314"


@pytest.mark.skipif(not PG_URL, reason="needs PostgreSQL (set MEDSCRIBE_TEST_PG_URL)")
def test_postgres_built_from_migrations_alone_has_no_drift(monkeypatch):
    admin = sa.create_engine(PG_URL)
    with admin.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS drift_test CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA drift_test"))
    url = PG_URL + ("&" if "?" in PG_URL else "?") + "options=-csearch_path=drift_test"
    monkeypatch.setenv("DATABASE_URL", url)  # alembic's env.py reads this
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(BACKEND, "migrations"))
    try:
        alembic_command.upgrade(cfg, "head")
        engine = sa.create_engine(PG_URL, connect_args={"options": "-csearch_path=drift_test"})
        assert drift.find_drift(engine, Base.metadata) == []
        engine.dispose()
    finally:
        with admin.begin() as conn:
            conn.execute(sa.text("DROP SCHEMA IF EXISTS drift_test CASCADE"))
        admin.dispose()