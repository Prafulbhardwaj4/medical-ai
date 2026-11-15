import io
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.services import storage


@pytest.fixture()
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_UPLOAD_DIR", str(tmp_path / "chat"))
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "ENCRYPT_CHAT_FILES", False)
    return tmp_path


def test_local_round_trip_and_missing_file(local):
    storage.save_chat_file("a.pdf", b"%PDF-1")
    assert storage.read_chat_file("a.pdf") == b"%PDF-1"
    assert storage.read_chat_file("nope.pdf") is None
    storage.delete_chat_file("a.pdf")
    assert storage.read_chat_file("a.pdf") is None


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../b", "a\\b", ""])
def test_keys_cannot_escape_the_folder(local, bad):
    with pytest.raises(ValueError):
        storage.put_bytes(bad, b"x")


def test_chat_files_are_encrypted_when_switched_on_and_old_plain_files_still_open(local, monkeypatch):
    storage.save_chat_file("old.png", b"plain-old")
    monkeypatch.setattr(settings, "DATA_ENC_KEYS", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "ENCRYPT_CHAT_FILES", True)
    storage.save_chat_file("new.png", b"secret-image")
    on_disk = open(os.path.join(os.environ["CHAT_UPLOAD_DIR"], "new.png"), "rb").read()
    assert on_disk.startswith(storage.MAGIC) and b"secret-image" not in on_disk
    assert storage.read_chat_file("new.png") == b"secret-image"
    assert storage.read_chat_file("old.png") == b"plain-old"


def test_chat_purge_removes_only_old_files(local, monkeypatch):
    from app.utils import retention
    storage.save_chat_file("old.pdf", b"1")
    storage.save_chat_file("new.pdf", b"2")
    old = os.path.join(os.environ["CHAT_UPLOAD_DIR"], "old.pdf")
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    monkeypatch.setattr(settings, "CHAT_UPLOAD_RETENTION_DAYS", 30)
    assert retention.purge_chat_uploads() == 1
    assert storage.read_chat_file("old.pdf") is None and storage.read_chat_file("new.pdf") == b"2"
    monkeypatch.setattr(settings, "CHAT_UPLOAD_RETENTION_DAYS", 0)
    assert retention.purge_chat_uploads() == 0


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **extra):
        self.objects[Key] = (Body, datetime.now(timezone.utc))

    def get_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key][0])}

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def get_paginator(self, _name):
        outer = self

        class P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k, "LastModified": v[1]} for k, v in outer.objects.items() if k.startswith(Prefix)]}
        return P()


@pytest.fixture()
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "S3_BUCKET", "bucket")
    monkeypatch.setattr(settings, "S3_PREFIX", "prod")
    monkeypatch.setattr(storage, "_client_cache", fake)
    return fake


def test_s3_round_trip_uses_prefix(s3):
    storage.save_chat_file("a.pdf", b"data")
    assert "prod/chat_uploads/a.pdf" in s3.objects
    assert storage.read_chat_file("a.pdf") == b"data" and storage.read_chat_file("b.pdf") is None
    assert storage.exists("chat_uploads/a.pdf") and not storage.exists("chat_uploads/b.pdf")


def test_generated_pdf_is_copied_and_old_copies_are_purged_but_radiology_kept(s3, tmp_path):
    path = os.path.join(storage.BACKEND_DIR, "reports", "__p8_test.pdf")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    @storage.mirror_generated
    def build():
        with open(path, "wb") as f:
            f.write(b"%PDF")
        return path

    try:
        assert build() == path
        assert s3.objects["prod/generated/reports/__p8_test.pdf"][0] == b"%PDF"
    finally:
        os.remove(path)
    long_ago = datetime.now(timezone.utc) - timedelta(days=10)
    s3.objects["prod/generated/reports/radiology_report_1.pdf"] = (b"r", long_ago)
    s3.objects["prod/generated/reports/__p8_test.pdf"] = (b"%PDF", long_ago)
    assert storage.purge_older_than("generated/", 3, keep_name_prefixes=("radiology_report_",)) == 1
    assert "prod/generated/reports/radiology_report_1.pdf" in s3.objects


def test_copy_failure_never_breaks_pdf_building(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "S3_BUCKET", "")
    monkeypatch.setattr(storage, "_client_cache", None)

    @storage.mirror_generated
    def build():
        return os.path.join(storage.BACKEND_DIR, "reports", "x.pdf")

    assert build().endswith("x.pdf")