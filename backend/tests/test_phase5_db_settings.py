import pytest

from app import database
from app.config import settings

PG = "postgresql://user:pw@db.example.com:5432/med"


def test_url_unchanged_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "DB_REQUIRE_SSL", False)
    assert database._database_url(PG) == PG


def test_sslmode_added_when_flag_on(monkeypatch):
    monkeypatch.setattr(settings, "DB_REQUIRE_SSL", True)
    out = database._database_url(PG)
    assert "sslmode=require" in out
    assert "user:pw@db.example.com" in out


def test_existing_sslmode_is_never_overridden(monkeypatch):
    monkeypatch.setattr(settings, "DB_REQUIRE_SSL", True)
    url = PG + "?sslmode=verify-full"
    assert database._database_url(url) == url


def test_sqlite_never_gets_sslmode(monkeypatch):
    monkeypatch.setattr(settings, "DB_REQUIRE_SSL", True)
    assert database._database_url("sqlite:///./x.db") == "sqlite:///./x.db"


def test_engine_kwargs_postgres(monkeypatch):
    monkeypatch.setattr(settings, "DB_POOL_SIZE", 3)
    monkeypatch.setattr(settings, "DB_MAX_OVERFLOW", 4)
    monkeypatch.setattr(settings, "DB_POOL_RECYCLE_SECONDS", 900)
    kw = database._engine_kwargs(PG)
    assert kw["pool_pre_ping"] is True
    assert kw["pool_recycle"] == 900 and kw["pool_size"] == 3 and kw["max_overflow"] == 4
    assert kw["hide_parameters"] is True


def test_engine_kwargs_sqlite_has_no_pool_options():
    kw = database._engine_kwargs("sqlite:///./x.db")
    assert "pool_size" not in kw and "pool_pre_ping" not in kw
    assert kw["hide_parameters"] is True
    assert kw["connect_args"] == {"check_same_thread": False}


def test_live_engine_hides_parameters():
    assert database.engine.hide_parameters is True