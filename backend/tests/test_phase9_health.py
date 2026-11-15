import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.utils import monitoring


@pytest.fixture()
def api():
    return TestClient(main.app, raise_server_exceptions=False)


def test_health_live_never_touches_database(api, monkeypatch):
    class Boom:
        def connect(self):
            raise RuntimeError("database is down")

    monkeypatch.setattr(main, "engine", Boom())
    r = api.get("/health/live")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_health_runs_select_1_and_reports_counters(api):
    r = api.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert "audit_write_failures" in body and "server_errors" in body


def test_health_returns_503_when_database_is_down(api, monkeypatch):
    class Boom:
        def connect(self):
            raise RuntimeError("database is down")

    monkeypatch.setattr(main, "engine", Boom())
    r = api.get("/health")
    assert r.status_code == 503
    assert r.json()["database"] == "down" and "database is down" not in r.text


def test_unhandled_error_is_counted_and_hidden(api):
    monitoring.reset_for_tests()

    def boom():
        raise RuntimeError("secret patient detail")

    main.app.add_api_route("/__p9_boom", boom, methods=["GET"])
    r = api.get("/__p9_boom")
    assert r.status_code == 500
    assert "secret patient detail" not in r.text
    assert monitoring.snapshot()["server_errors"] == 1


def test_migrations_skipped_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "RUN_MIGRATIONS_ON_BOOT", False)

    def explode():
        raise AssertionError("migrations must not run")

    monkeypatch.setattr(main, "_run_migrations_locked", explode)
    main._run_migrations()


@pytest.mark.parametrize("tutorial,catalog", [(True, True), (False, False), (True, False)])
def test_boot_tasks_follow_the_flags(monkeypatch, tutorial, catalog):
    calls = []
    monkeypatch.setattr(settings, "SEED_TUTORIAL_ON_BOOT", tutorial)
    monkeypatch.setattr(settings, "MASTER_CATALOG_AUTOLOAD_ON_BOOT", catalog)
    monkeypatch.setattr(main, "_seed_tutorial_content", lambda: calls.append("tutorial"))
    monkeypatch.setattr(main, "_seed_master_catalog", lambda: calls.append("catalog"))
    monkeypatch.setattr(main, "_backfill_billing_period", lambda: calls.append("backfill"))
    main._run_boot_tasks()
    assert ("tutorial" in calls) == tutorial
    assert ("catalog" in calls) == catalog
    assert "backfill" in calls