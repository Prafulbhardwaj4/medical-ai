"""Copies the files on this server's disk into the S3-compatible bucket.

    STORAGE_BACKEND=s3 python scripts/migrate_files_to_s3.py --dry-run     (lists what would be copied)
    STORAGE_BACKEND=s3 python scripts/migrate_files_to_s3.py               (copies; files already in the bucket are skipped)
    STORAGE_BACKEND=s3 python scripts/migrate_files_to_s3.py --delete-local  (copies, then removes the local copy that was uploaded)

Needs STORAGE_BACKEND=s3 and S3_BUCKET (see app/services/storage.py for the other S3_ settings).
Chat files are encrypted on the way if ENCRYPT_CHAT_FILES=true. Safe to run again.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.services import storage  # noqa: E402

GENERATED_FOLDERS = ("prescriptions", "reports", "token_slips", "invoices")


def _files(folder):
    if not os.path.isdir(folder):
        return
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and not name.endswith(".tmp"):
            yield name, path


def main():
    args = sys.argv[1:]
    dry, delete_local = "--dry-run" in args, "--delete-local" in args
    if storage.backend_name() != "s3":
        print("STORAGE_BACKEND is not s3. Set STORAGE_BACKEND=s3 (and S3_BUCKET) first.")
        sys.exit(1)
    if not (settings.S3_BUCKET or "").strip():
        print("S3_BUCKET is not set.")
        sys.exit(1)

    jobs = [(os.environ.get("CHAT_UPLOAD_DIR", "chat_uploads"), storage.CHAT_PREFIX, True)]
    jobs += [(os.path.join(storage.BACKEND_DIR, f), f"{storage.GENERATED_PREFIX}{f}/", False) for f in GENERATED_FOLDERS]

    copied = skipped = failed = 0
    for folder, prefix, is_chat in jobs:
        for name, path in _files(folder):
            key = prefix + name
            try:
                if storage.exists(key):
                    skipped += 1
                    continue
                if dry:
                    print("would copy", path, "->", key)
                    copied += 1
                    continue
                with open(path, "rb") as f:
                    data = f.read()
                storage.put_bytes(key, storage.prepare_chat_bytes(data) if is_chat else data)
                copied += 1
                if delete_local:
                    os.remove(path)
            except Exception as e:
                failed += 1
                print("FAILED", path, "-", e)
    print(f"{'Would copy' if dry else 'Copied'} {copied}, already in the bucket {skipped}, failed {failed}")
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()