"""One place for stored files (Phase 8).

STORAGE_BACKEND=local (default): files stay on disk exactly where they were.
STORAGE_BACKEND=s3: files go to an S3-compatible bucket (AWS S3, Cloudflare R2, Backblaze B2 ...) through boto3.
    Needs S3_BUCKET. Optional: S3_REGION, S3_ENDPOINT_URL (R2 / Backblaze), S3_ACCESS_KEY_ID and
    S3_SECRET_ACCESS_KEY (leave empty to use the server's own AWS role), S3_PREFIX, S3_SSE.

Keys:  chat_uploads/<file>   and   generated/<folder>/<file>   (folder = prescriptions, reports, token_slips, invoices)
Chat files can be encrypted at rest (ENCRYPT_CHAT_FILES=true, uses DATA_ENC_KEYS). Plain old files still open.
Generated PDFs are rebuilt from the database whenever they are opened, so the copies kept here are only a cache.
"""
import functools
import logging
import os
import time
from typing import List, Optional, Tuple

from app.config import settings
from app.utils.field_crypto import _multi as _data_fernet

log = logging.getLogger(__name__)

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CHAT_PREFIX = "chat_uploads/"
GENERATED_PREFIX = "generated/"
MAGIC = b"MSENC1\n"
_client_cache = None


def backend_name() -> str:
    return (settings.STORAGE_BACKEND or "local").strip().lower()


def _check_key(key: str) -> str:
    parts = (key or "").split("/")
    if not key or key.startswith("/") or "\\" in key or any(p in ("", ".", "..") for p in parts):
        raise ValueError("Invalid storage key")
    return key


# ------------------------------------------------------------------ local

def _local_path(key: str) -> str:
    _check_key(key)
    if key.startswith(CHAT_PREFIX):
        return os.path.join(os.environ.get("CHAT_UPLOAD_DIR", "chat_uploads"), key[len(CHAT_PREFIX):])
    if key.startswith(GENERATED_PREFIX):
        return os.path.join(BACKEND_DIR, key[len(GENERATED_PREFIX):])
    return os.path.join(os.environ.get("STORAGE_LOCAL_DIR", os.path.join(BACKEND_DIR, "storage")), key)


# ----------------------------------------------------------------- object store

def _client():
    global _client_cache
    if _client_cache is None:
        if not (settings.S3_BUCKET or "").strip():
            raise RuntimeError("STORAGE_BACKEND is s3 but S3_BUCKET is not set")
        import boto3
        from botocore.config import Config
        kwargs = {"config": Config(signature_version="s3v4",
                                   s3={"addressing_style": "path"} if settings.S3_ENDPOINT_URL else {})}
        if settings.S3_REGION:
            kwargs["region_name"] = settings.S3_REGION
        if settings.S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        if settings.S3_ACCESS_KEY_ID and settings.S3_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"] = settings.S3_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = settings.S3_SECRET_ACCESS_KEY
        _client_cache = boto3.client("s3", **kwargs)
    return _client_cache


def _s3_key(key: str) -> str:
    prefix = (settings.S3_PREFIX or "").strip("/")
    return f"{prefix}/{key}" if prefix else key


def _is_missing(err) -> bool:
    code = str(getattr(err, "response", {}).get("Error", {}).get("Code", ""))
    return code in ("NoSuchKey", "404", "NotFound")


# --------------------------------------------------------------------- basic API

def put_bytes(key: str, data: bytes) -> None:
    _check_key(key)
    if backend_name() == "s3":
        extra = {"ServerSideEncryption": settings.S3_SSE} if settings.S3_SSE else {}
        _client().put_object(Bucket=settings.S3_BUCKET, Key=_s3_key(key), Body=data, **extra)
        return
    path = _local_path(key)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def get_bytes(key: str) -> Optional[bytes]:
    _check_key(key)
    if backend_name() == "s3":
        from botocore.exceptions import ClientError
        try:
            return _client().get_object(Bucket=settings.S3_BUCKET, Key=_s3_key(key))["Body"].read()
        except ClientError as e:
            if _is_missing(e):
                return None
            raise
    path = _local_path(key)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def exists(key: str) -> bool:
    _check_key(key)
    if backend_name() == "s3":
        from botocore.exceptions import ClientError
        try:
            _client().head_object(Bucket=settings.S3_BUCKET, Key=_s3_key(key))
            return True
        except ClientError as e:
            if _is_missing(e):
                return False
            raise
    return os.path.isfile(_local_path(key))


def delete(key: str) -> None:
    _check_key(key)
    if backend_name() == "s3":
        _client().delete_object(Bucket=settings.S3_BUCKET, Key=_s3_key(key))
        return
    try:
        os.remove(_local_path(key))
    except FileNotFoundError:
        pass


def list_keys(prefix: str) -> List[Tuple[str, float]]:
    """(key, last-modified as epoch seconds) for every file under a prefix that ends with '/'."""
    if backend_name() == "s3":
        out, strip = [], (settings.S3_PREFIX or "").strip("/")
        for page in _client().get_paginator("list_objects_v2").paginate(Bucket=settings.S3_BUCKET, Prefix=_s3_key(prefix)):
            for obj in page.get("Contents", []):
                k = obj["Key"]
                if strip and k.startswith(strip + "/"):
                    k = k[len(strip) + 1:]
                out.append((k, obj["LastModified"].timestamp()))
        return out
    base = os.path.dirname(_local_path(prefix + "_"))
    if not os.path.isdir(base):
        return []
    out = []
    for root, _dirs, files in os.walk(base):
        for name in files:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            try:
                out.append((prefix + rel, os.path.getmtime(full)))
            except OSError:
                pass
    return out


# ------------------------------------------------------------------ chat files

def prepare_chat_bytes(data: bytes) -> bytes:
    """Encrypts chat file bytes when ENCRYPT_CHAT_FILES is on and DATA_ENC_KEYS is set."""
    multi = _data_fernet() if settings.ENCRYPT_CHAT_FILES else None
    return MAGIC + multi.encrypt(data) if multi else data


def save_chat_file(name: str, data: bytes) -> None:
    put_bytes(CHAT_PREFIX + name, prepare_chat_bytes(data))


def read_chat_file(name: str) -> Optional[bytes]:
    data = get_bytes(CHAT_PREFIX + name)
    if data is None or not data.startswith(MAGIC):
        return data
    multi = _data_fernet()
    if multi is None:
        log.error("An encrypted chat file was requested but DATA_ENC_KEYS is not set.")
        return None
    try:
        return multi.decrypt(data[len(MAGIC):])
    except Exception:
        log.error("An encrypted chat file could not be read with any key in DATA_ENC_KEYS.")
        return None


def delete_chat_file(name: str) -> None:
    delete(CHAT_PREFIX + name)


# ------------------------------------------------------------- generated files

def mirror_generated(func):
    """Decorator for the PDF builders. The builder still returns the same local path; with the s3
    backend a copy is also stored. A storage problem never stops the PDF from being made."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        path = func(*args, **kwargs)
        if backend_name() == "s3" and isinstance(path, str):
            try:
                rel = os.path.relpath(os.path.abspath(path), BACKEND_DIR).replace(os.sep, "/")
                if not rel.startswith(".."):
                    with open(path, "rb") as f:
                        put_bytes(GENERATED_PREFIX + rel, f.read())
            except Exception as e:
                log.warning("Could not store a copy of %s: %s", os.path.basename(str(path)), e)
        return path
    return wrapper


def purge_older_than(prefix: str, days: int, keep_name_prefixes=()) -> int:
    """Removes stored files older than `days` (object store only; local files have their own cleanup)."""
    if backend_name() != "s3" or days <= 0:
        return 0
    cutoff, removed = time.time() - days * 86400, 0
    for key, modified in list_keys(prefix):
        name = key.rsplit("/", 1)[-1]
        if any(name.startswith(p) for p in keep_name_prefixes) or modified >= cutoff:
            continue
        try:
            delete(key)
            removed += 1
        except Exception as e:
            log.warning("Could not remove %s: %s", key, e)
    return removed