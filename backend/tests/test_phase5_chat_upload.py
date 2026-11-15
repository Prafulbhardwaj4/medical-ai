import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from app.routers import chat

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPG = b"\xff\xd8\xff\xe0" + b"0" * 64
PDF = b"%PDF-1.7\n" + b"0" * 64


def _docx_bytes(valid=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml" if valid else "other.xml", "<x/>")
        z.writestr("word/document.xml" if valid else "misc/a.xml", "<x/>")
    return buf.getvalue()


def _upload(name, data):
    return UploadFile(file=io.BytesIO(data), filename=name)


@pytest.fixture
def doctor():
    return SimpleNamespace(role=SimpleNamespace(value="doctor"))


@pytest.fixture(autouse=True)
def saved(monkeypatch):
    store = {}
    monkeypatch.setattr(chat.storage, "save_chat_file", lambda name, data: store.__setitem__(name, data))
    return store


@pytest.mark.parametrize("name,data", [("a.png", PNG), ("a.jpg", JPG), ("a.jpeg", JPG), ("a.pdf", PDF),
                                       ("a.docx", _docx_bytes()), ("a.gif", b"GIF89a" + b"0" * 20),
                                       ("a.webp", b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 20),
                                       ("a.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 20)])
def test_real_files_are_accepted(name, data, doctor, saved):
    out = chat.upload_chat_attachment(file=_upload(name, data), current_doctor=doctor)
    assert out["attachment_filename"].endswith(name[name.rfind("."):])
    assert saved[out["attachment_filename"]] == data


@pytest.mark.parametrize("name,data", [
    ("evil.png", b"<html><script>alert(1)</script></html>"),
    ("evil.pdf", b"MZ\x90\x00 this is an exe"),
    ("evil.jpg", PNG),
    ("evil.docx", _docx_bytes(valid=False)),
    ("evil.docx", b"not a zip at all"),
    ("evil.gif", b"GIF"),
])
def test_wrong_signature_is_refused_and_nothing_is_saved(name, data, doctor, saved):
    with pytest.raises(HTTPException) as e:
        chat.upload_chat_attachment(file=_upload(name, data), current_doctor=doctor)
    assert e.value.status_code == 400
    assert saved == {}


def test_unknown_extension_refused(doctor):
    with pytest.raises(HTTPException) as e:
        chat.upload_chat_attachment(file=_upload("a.exe", b"MZ"), current_doctor=doctor)
    assert e.value.status_code == 400


def test_empty_file_refused(doctor):
    with pytest.raises(HTTPException) as e:
        chat.upload_chat_attachment(file=_upload("a.png", b""), current_doctor=doctor)
    assert e.value.status_code == 400


def test_oversize_stops_reading_at_the_cap(doctor):
    reads = []

    class Spy(io.BytesIO):
        def read(self, n=-1):
            data = super().read(n)
            reads.append(len(data))
            return data

    big = PNG + b"0" * (chat.MAX_ATTACHMENT_BYTES + 5 * 1024 * 1024)
    with pytest.raises(HTTPException) as e:
        chat.upload_chat_attachment(file=UploadFile(file=Spy(big), filename="big.png"), current_doctor=doctor)
    assert e.value.status_code == 400
    assert sum(reads) < len(big)
    assert max(reads) <= chat._READ_CHUNK_BYTES


def test_scan_hook_default_is_noop_and_can_reject(doctor, saved, monkeypatch):
    assert chat.scan_upload("whatever") is None

    def bad(path):
        raise ValueError("infected")
    monkeypatch.setattr(chat, "scan_upload", bad)
    with pytest.raises(HTTPException) as e:
        chat.upload_chat_attachment(file=_upload("a.png", PNG), current_doctor=doctor)
    assert e.value.status_code == 400
    assert saved == {}


def test_role_check_still_applies():
    with pytest.raises(HTTPException) as e:
        chat.upload_chat_attachment(file=_upload("a.png", PNG), current_doctor=SimpleNamespace(role=SimpleNamespace(value="patient")))
    assert e.value.status_code == 403