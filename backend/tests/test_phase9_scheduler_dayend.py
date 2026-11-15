import asyncio
import contextlib
import datetime
import importlib.util
import os
import threading

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

from app import scheduler
from app.config import settings
from app.routers import billing

MIGRATION = os.path.join(os.path.dirname(__file__), "..", "migrations", "versions", "c4e8a1d7f203_day_end_closes_unique.py")


def _load_migration():
    spec = importlib.util.spec_from_file_location("p9_day_end_unique", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _engine_with_closes(rows):
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE day_end_closes (id INTEGER PRIMARY KEY, hospital_id INTEGER NOT NULL, close_date DATE NOT NULL, "
            "auto_closed BOOLEAN, counted_cash FLOAT, closed_at DATETIME)"))
        for hid, day in rows:
            conn.execute(sa.text("INSERT INTO day_end_closes (hospital_id, close_date, auto_closed) VALUES (:h, :d, 1)"),
                         {"h": hid, "d": day})
    return engine


def _run_upgrade(engine):
    mod = _load_migration()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()


def test_migration_stops_on_duplicates_and_deletes_nothing():
    day = datetime.date(2026, 11, 1)
    engine = _engine_with_closes([(1, day), (1, day), (2, day)])
    with pytest.raises(RuntimeError) as err:
        _run_upgrade(engine)
    assert "hospital 1" in str(err.value) and "ids 1, 2" in str(err.value)
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM day_end_closes")).scalar() == 3


def test_migration_adds_unique_rule_when_clean():
    day = datetime.date(2026, 11, 1)
    engine = _engine_with_closes([(1, day), (2, day)])
    _run_upgrade(engine)
    _run_upgrade(engine)  # safe to run twice
    with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(sa.text("INSERT INTO day_end_closes (hospital_id, close_date) VALUES (1, :d)"), {"d": day})


def test_list_script_finds_duplicates():
    from scripts.list_duplicate_day_end_closes import find_duplicates
    day = datetime.date(2026, 11, 1)
    engine = _engine_with_closes([(1, day), (1, day), (2, day)])
    with engine.connect() as conn:
        dups = find_duplicates(conn)
    assert len(dups) == 1 and dups[0]["hospital_id"] == 1 and [r["id"] for r in dups[0]["rows"]] == [1, 2]


def test_close_handles_unique_violation(monkeypatch):
    class Query:
        def filter(self, *a, **k):
            return self

        def first(self):
            return True

    class FakeDB:
        rolled_back = False

        def query(self, *a):
            return Query()

        def add(self, obj):
            pass

        def commit(self):
            raise IntegrityError("insert", {}, Exception("duplicate"))

        def rollback(self):
            self.rolled_back = True

    monkeypatch.setattr(billing, "_day_end_summary_core", lambda db, h, d: {"system_totals": {}})
    db = FakeDB()
    assert billing.close_day_for_hospital(db, 1, datetime.date(2026, 11, 1)) is False
    assert db.rolled_back


def test_only_the_leader_runs_the_loops(monkeypatch):
    started = []

    class FakeLock:
        allow = False
        released = False

        def __init__(self, engine, name):
            pass

        def try_acquire(self):
            return FakeLock.allow

        def still_held(self):
            return True

        def release(self):
            FakeLock.released = True

    async def fake_midnight():
        started.append("midnight")
        await asyncio.sleep(3600)

    async def fake_lab():
        started.append("lab")
        await asyncio.sleep(3600)

    monkeypatch.setattr("app.utils.boot.LeaderLock", FakeLock)
    monkeypatch.setattr(scheduler, "midnight_close_loop", fake_midnight)
    monkeypatch.setattr(scheduler, "lab_escalation_loop", fake_lab)
    monkeypatch.setattr(settings, "SCHEDULER_LEADER_RETRY_SECONDS", 1)

    async def scenario():
        task = asyncio.create_task(scheduler._scheduler_leader_main())
        await asyncio.sleep(0.3)
        assert started == []  # not the leader: nothing runs
        FakeLock.allow = True
        await asyncio.sleep(1.6)
        assert sorted(started) == ["lab", "midnight"]
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert FakeLock.released


def test_scheduler_disabled_starts_nothing(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
    calls = []
    monkeypatch.setattr(scheduler, "_scheduler_leader_main", lambda: calls.append("x"))

    async def scenario():
        scheduler.start_scheduler()

    asyncio.run(scenario())
    assert calls == []


@pytest.mark.parametrize("flag", [True, False])
def test_startup_catchup_runs_off_the_event_loop_and_obeys_flag(monkeypatch, flag):
    seen = []
    monkeypatch.setattr(settings, "DAY_END_CATCHUP_ON_BOOT", flag)
    monkeypatch.setattr(scheduler, "_startup_catchup", lambda: seen.append(threading.current_thread() is not threading.main_thread()))

    async def scenario():
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(scheduler.midnight_close_loop(), timeout=0.5)

    asyncio.run(scenario())
    assert seen == ([True] if flag else [])