import json
import logging
import sys
import types

import pytest
from sqlalchemy import create_engine

from app.config import settings


def test_scrubber_removes_request_data_text_and_variables():
    from app.utils.monitoring import scrub_event
    event = {
        "request": {"url": "https://x/y?token=abc", "query_string": "token=abc", "data": {"name": "Ravi"},
                    "headers": {"Authorization": "Bearer t", "Cookie": "a=b", "User-Agent": "u"}},
        "exception": {"values": [{"type": "ValueError", "value": "patient Ravi Kumar",
                                  "stacktrace": {"frames": [{"function": "f", "vars": {"p": "x"}}]}}]},
        "breadcrumbs": {"values": [{"message": "select * from patients"}]},
        "user": {"id": 1},
        "logentry": {"message": "UNHANDLED POST /patients Ravi", "params": ["Ravi"]},
    }
    out = scrub_event(event, {})
    assert "query_string" not in out["request"] and "data" not in out["request"]
    assert out["request"]["url"] == "https://x/y"
    assert list(out["request"]["headers"]) == ["User-Agent"]
    assert out["exception"]["values"][0]["value"] == "[removed]"
    assert "vars" not in out["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert out["breadcrumbs"] == {"values": []} and "user" not in out
    assert out["logentry"]["message"] == "[removed]" and "params" not in out["logentry"]


def test_scrubber_keeps_alert_markers():
    from app.utils.monitoring import scrub_event
    out = scrub_event({"logentry": {"message": "AUDIT_WRITE_FAILED an audit entry could not be saved"}}, {})
    assert out["logentry"]["message"].startswith("AUDIT_WRITE_FAILED")


def test_audit_failure_counter_and_marker(caplog):
    from app.utils import monitoring
    monitoring.reset_for_tests()
    with caplog.at_level(logging.ERROR, logger="audit"):
        monitoring.record_audit_write_failure(ValueError("x"))
    assert monitoring.snapshot()["audit_write_failures"] == 1
    assert "AUDIT_WRITE_FAILED" in caplog.text


def test_login_failure_spike_alerts_once_per_window(monkeypatch):
    from app.utils import monitoring
    monitoring.reset_for_tests()
    monkeypatch.setattr(settings, "REDIS_URL", "")
    monkeypatch.setattr(settings, "LOGIN_FAILURE_ALERT_THRESHOLD", 3)
    monkeypatch.setattr(settings, "LOGIN_FAILURE_ALERT_WINDOW_SECONDS", 3600)
    sent = []
    monkeypatch.setattr(monitoring, "capture_message", lambda m, level="error": sent.append(m))
    for _ in range(6):
        monitoring.record_login_failure()
    monitoring.record_login_failure(locked=True)
    assert len(sent) == 1 and sent[0].startswith("LOGIN_FAILURE_SPIKE")
    snap = monitoring.snapshot()
    assert snap["login_failures"] == 7 and snap["lockouts"] == 1


def test_reload_refused_in_production(monkeypatch):
    from app.utils import boot
    monkeypatch.setattr(sys, "argv", ["uvicorn", "app.main:app", "--reload"])
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(RuntimeError):
        boot.check_runtime_flags()


def test_reload_allowed_in_development(monkeypatch):
    from app.utils import boot
    monkeypatch.setattr(sys, "argv", ["uvicorn", "app.main:app", "--reload"])
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "")
    boot.check_runtime_flags()


def test_locks_are_noops_on_sqlite():
    from app.utils.boot import boot_lock, LeaderLock
    engine = create_engine("sqlite://")
    with boot_lock(engine, "migrations"):
        pass
    lock = LeaderLock(engine, "scheduler")
    assert lock.try_acquire() and lock.still_held()
    lock.release()


def test_aws_secrets_loader_fills_only_missing(monkeypatch):
    from app.aws_secrets import load_aws_secrets
    monkeypatch.delenv("AWS_SECRETS_ID", raising=False)
    assert load_aws_secrets() == 0

    class FakeClient:
        def get_secret_value(self, SecretId):
            return {"SecretString": json.dumps({"P9_NEW": "a", "P9_EXISTING": "b"})}

    fake = types.SimpleNamespace(client=lambda name: FakeClient())
    monkeypatch.setitem(sys.modules, "boto3", fake)
    monkeypatch.setenv("AWS_SECRETS_ID", "medscribe/prod")
    monkeypatch.setenv("P9_EXISTING", "keep")
    monkeypatch.delenv("P9_NEW", raising=False)
    assert load_aws_secrets() == 1
    import os
    assert os.environ["P9_NEW"] == "a" and os.environ["P9_EXISTING"] == "keep"
    monkeypatch.delenv("P9_NEW", raising=False)


def test_logging_setup_one_handler_one_line(capsys):
    from app.utils.logging_setup import configure_logging
    root = logging.getLogger()
    saved, level = list(root.handlers), root.level
    try:
        configure_logging("INFO")
        configure_logging("INFO")
        assert len(root.handlers) == 1
        logging.getLogger("t").info("first\nsecond")
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1 and "first | second" in out[0]
    finally:
        root.handlers = saved
        root.setLevel(level)


@pytest.mark.parametrize("hops", [1, 2])
def test_proxy_sample_picks_the_client(monkeypatch, caplog, hops):
    from app.utils import boot
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", hops)
    with caplog.at_level(logging.INFO, logger="medscribe"):
        boot.log_proxy_settings()
    assert f"TRUSTED_PROXY_HOPS={hops}" in caplog.text
    assert "would use client IP 198.51.100.23" in caplog.text