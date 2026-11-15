import importlib.util
import os
from datetime import datetime, timedelta, timezone

_spec = importlib.util.spec_from_file_location(
    "backup_s3", os.path.join(os.path.dirname(__file__), "..", "scripts", "backup_s3.py"))
backup_s3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup_s3)

NOW = datetime(2026, 11, 14, 2, 0, tzinfo=timezone.utc)


def test_only_backups_older_than_the_retention_are_removed():
    objects = [
        ("db-backups/a.gpg", NOW - timedelta(days=30)),
        ("db-backups/b.gpg", NOW - timedelta(days=14, minutes=1)),
        ("db-backups/c.gpg", NOW - timedelta(days=13)),
        ("db-backups/d.gpg", NOW - timedelta(hours=3)),
    ]
    assert backup_s3.expired_keys(objects, NOW, 14) == ["db-backups/a.gpg", "db-backups/b.gpg"]


def test_nothing_is_removed_when_everything_is_recent():
    assert backup_s3.expired_keys([("k", NOW - timedelta(days=1))], NOW, 14) == []
    assert backup_s3.expired_keys([], NOW, 14) == []


def test_newest_backup_is_picked():
    objects = [("old", NOW - timedelta(days=5)), ("new", NOW - timedelta(hours=1)), ("mid", NOW - timedelta(days=2))]
    assert backup_s3.newest_key(objects) == "new"
    assert backup_s3.newest_key([]) is None