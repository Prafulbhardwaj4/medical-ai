import importlib.util
import os

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401  (importing the app registers every model)
from app.database import Base

HERE = os.path.dirname(__file__)
INDEX_MIGRATION = os.path.join(HERE, "..", "migrations", "versions", "d5f9b2e8a314_hot_path_indexes.py")


def _fresh_engine():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


def _upgrade(engine):
    spec = importlib.util.spec_from_file_location("p9_hot_indexes", INDEX_MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
    return mod


def _index_names(engine, table):
    return {i["name"] for i in sa.inspect(engine).get_indexes(table)}


def test_index_migration_creates_hot_path_indexes_and_is_repeatable():
    engine = _fresh_engine()
    mod = _upgrade(engine)
    _upgrade(engine)
    for name, table, cols in mod.INDEXES:
        assert name in _index_names(engine, table), name


def test_index_migration_skips_missing_tables():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool)
    _upgrade(engine)  # no tables at all: nothing happens, no error


def test_index_migration_chains_after_the_day_end_migration():
    from scripts.check_alembic_head import script_directory
    script = script_directory()
    rev = script.get_revision("d5f9b2e8a314")
    assert rev.down_revision == "d3b7e1f90a64"
    assert script.get_revision("d3b7e1f90a64") is not None


def test_list_missing_indexes_sees_then_stops_listing():
    from scripts.list_missing_indexes import find_missing
    engine = _fresh_engine()
    before = find_missing(sa.inspect(engine))
    assert ("patients", "hospital_id") in before["foreign_keys"]
    _upgrade(engine)
    after = find_missing(sa.inspect(engine))
    assert ("patients", "hospital_id") not in after["foreign_keys"]
    assert ("portal_appointments", "hospital_id") not in after["foreign_keys"]


def test_check_alembic_head_compare():
    from scripts.check_alembic_head import compare, script_directory
    script = script_directory()
    heads = script.get_heads()
    assert compare(script, heads)[0] in ("ok", "multiple_heads")
    if len(heads) == 1:
        assert compare(script, heads)[0] == "ok"
        status, message = compare(script, ["b9d2f6308e1c"])
        assert status == "behind" and "behind by" in message
        assert compare(script, ["zzzzzzzzzzzz"])[0] == "ahead"


def test_run_migrations_and_alembic_head_scripts_skip_sqlite(capsys):
    from app.database import engine
    if engine.dialect.name != "sqlite":
        pytest.skip("needs the local SQLite test database")
    from scripts import run_migrations, check_alembic_head
    assert run_migrations.main([]) == 0
    assert "SQLite" in capsys.readouterr().out
    assert check_alembic_head.main([]) == 0


SAFE = '''
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column("t", sa.Column("x", sa.String(50)))
    op.create_index("ix", "t", ["x"])
    op.alter_column("t", "y", type_=sa.String(200), existing_type=sa.String(100))
    op.alter_column("t", "z", type_=sa.Text(), existing_type=sa.String(100))
    op.alter_column("t", "n", type_=sa.BigInteger(), existing_type=sa.Integer())

def downgrade():
    op.drop_column("t", "x")
    op.drop_table("gone")
'''

BAD = '''
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.drop_column("t", "x")
    op.drop_table("old")
    op.rename_table("a", "b")
    op.alter_column("t", "c", new_column_name="d")
    op.alter_column("t", "y", type_=sa.String(10), existing_type=sa.String(100))
    op.alter_column("t", "q", type_=sa.String(10))
    op.alter_column("t", "n", type_=sa.Integer(), existing_type=sa.BigInteger())
    op.execute("DROP TABLE legacy")
    op.execute("UPDATE t SET x = 1")

def downgrade():
    pass
'''

ALLOWED = '''
from alembic import op

def upgrade():
    op.drop_column("t", "x")  # migration-safety: allow
'''


def test_safety_checker_passes_safe_migration_and_ignores_downgrade():
    from scripts.check_migration_safety import scan_source
    assert scan_source(SAFE) == []


def test_safety_checker_flags_every_destructive_operation():
    from scripts.check_migration_safety import scan_source
    messages = [m for _, m in scan_source(BAD)]
    assert len(messages) == 8
    joined = " | ".join(messages)
    for word in ("drops a column", "drops a table", "renames a table", "renames a column", "narrows a text column",
                 "without existing_type", "narrows an integer column", "raw SQL"):
        assert word in joined


def test_safety_checker_respects_reviewed_exception():
    from scripts.check_migration_safety import scan_source
    assert scan_source(ALLOWED) == []


def test_safety_checker_cli_on_files(tmp_path, capsys):
    from scripts.check_migration_safety import main
    good, bad = tmp_path / "good.py", tmp_path / "bad.py"
    good.write_text(SAFE)
    bad.write_text(BAD)
    assert main([str(good)]) == 0
    assert main([str(bad)]) == 1
    assert "FAILED" in capsys.readouterr().out