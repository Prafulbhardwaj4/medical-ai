"""Upload, prune and fetch database backups in a private S3-compatible bucket (AWS S3, R2, Backblaze ...).

    python scripts/backup_s3.py upload  <file>                  # stores it under BACKUP_PREFIX
    python scripts/backup_s3.py prune                           # deletes backups older than BACKUP_RETENTION_DAYS (default 14)
    python scripts/backup_s3.py latest  <output-file>           # downloads the newest backup

Settings come from the environment only (never printed):
    BACKUP_S3_BUCKET, BACKUP_S3_ACCESS_KEY_ID, BACKUP_S3_SECRET_ACCESS_KEY,
    BACKUP_S3_REGION (optional), BACKUP_S3_ENDPOINT (optional, for R2 / Backblaze), BACKUP_PREFIX (default "db-backups/"),
    BACKUP_RETENTION_DAYS (default 14).
"""
import os
import sys
from datetime import datetime, timedelta, timezone


def expired_keys(objects, now, days):
    """objects: iterable of (key, last_modified aware datetime). Returns the keys older than `days` days."""
    cutoff = now - timedelta(days=days)
    return [key for key, modified in objects if modified < cutoff]


def newest_key(objects):
    """Key of the most recently modified object, or None."""
    items = list(objects)
    return max(items, key=lambda kv: kv[1])[0] if items else None


def _settings():
    bucket = os.environ.get("BACKUP_S3_BUCKET", "").strip()
    if not bucket:
        sys.exit("BACKUP_S3_BUCKET is not set.")
    prefix = os.environ.get("BACKUP_PREFIX", "db-backups/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    days = int(os.environ.get("BACKUP_RETENTION_DAYS", "14") or 14)
    return bucket, prefix, max(1, days)


def _client():
    import boto3
    kwargs = {}
    if os.environ.get("BACKUP_S3_ENDPOINT"):
        kwargs["endpoint_url"] = os.environ["BACKUP_S3_ENDPOINT"]
    if os.environ.get("BACKUP_S3_REGION"):
        kwargs["region_name"] = os.environ["BACKUP_S3_REGION"]
    return boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("BACKUP_S3_ACCESS_KEY_ID") or None,
        aws_secret_access_key=os.environ.get("BACKUP_S3_SECRET_ACCESS_KEY") or None,
        **kwargs,
    )


def _list(client, bucket, prefix):
    token, out = None, []
    while True:
        args = {"Bucket": bucket, "Prefix": prefix}
        if token:
            args["ContinuationToken"] = token
        page = client.list_objects_v2(**args)
        out += [(o["Key"], o["LastModified"]) for o in page.get("Contents", [])]
        if not page.get("IsTruncated"):
            return out
        token = page["NextContinuationToken"]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("upload", "prune", "latest"):
        sys.exit(__doc__)
    bucket, prefix, days = _settings()
    client = _client()
    cmd = argv[0]
    if cmd == "upload":
        path = argv[1]
        key = prefix + os.path.basename(path)
        client.upload_file(path, bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"} if not os.environ.get("BACKUP_S3_ENDPOINT") else {})
        print(f"Uploaded {os.path.basename(path)} ({os.path.getsize(path)} bytes).")
    elif cmd == "prune":
        old = expired_keys(_list(client, bucket, prefix), datetime.now(timezone.utc), days)
        for key in old:
            client.delete_object(Bucket=bucket, Key=key)
        print(f"Removed {len(old)} backup(s) older than {days} days.")
    else:
        key = newest_key(_list(client, bucket, prefix))
        if not key:
            sys.exit("No backups found.")
        client.download_file(bucket, key, argv[1])
        print(f"Downloaded the newest backup: {key.rsplit('/', 1)[-1]}")


if __name__ == "__main__":
    main()