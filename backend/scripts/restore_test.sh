#!/usr/bin/env bash
# Restores the latest backup into a scratch database and runs row-count sanity checks.
#
#   scripts/restore_test.sh [backup-file]
#
# Needs:
#   RESTORE_ADMIN_URL   a PostgreSQL server where a scratch database may be created and dropped
#                       (a local one is best; for example postgresql://postgres:pw@localhost:5432/postgres)
#   BACKUP_PASSPHRASE   only when the file ends in .gpg
# Without a file argument the newest backup is downloaded from the bucket (BACKUP_S3_* settings, see backup_s3.py).
# Optional:
#   SOURCE_DATABASE_URL compare the restored row counts with the live database (fails if less than half is there)
#
# Exit code 0 = the backup restored and looks sane. Anything else = do not trust this backup.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
SCRATCH="medscribe_restore_check_$(date +%s)"
CREATED=0

plain_url() { echo "$1" | sed -E 's#^postgresql\+[a-z0-9]+://#postgresql://#'; }
with_db()   { python3 - "$1" "$2" <<'PY'
import sys
from urllib.parse import urlparse, urlunparse
u = urlparse(sys.argv[1])
print(urlunparse(u._replace(path="/" + sys.argv[2])))
PY
}

cleanup() {
  if [ "$CREATED" = "1" ]; then
    psql "$ADMIN" -v ON_ERROR_STOP=0 -qc "DROP DATABASE IF EXISTS \"$SCRATCH\"" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

fail() { echo "FAIL: $1" >&2; exit 1; }

[ -n "${RESTORE_ADMIN_URL:-}" ] || fail "RESTORE_ADMIN_URL is not set."
ADMIN="$(plain_url "$RESTORE_ADMIN_URL")"
command -v pg_restore >/dev/null || fail "pg_restore is not installed (install the PostgreSQL client)."

# 1. get the backup file
FILE="${1:-}"
if [ -z "$FILE" ]; then
  FILE="$WORK/latest.backup"
  python3 "$HERE/backup_s3.py" latest "$FILE"
fi
[ -s "$FILE" ] || fail "the backup file is missing or empty."

# 2. decrypt if needed
DUMP="$FILE"
case "$FILE" in
  *.gpg)
    [ -n "${BACKUP_PASSPHRASE:-}" ] || fail "BACKUP_PASSPHRASE is not set."
    DUMP="$WORK/restore.dump"
    gpg --batch --yes --quiet --pinentry-mode loopback --passphrase "$BACKUP_PASSPHRASE" -d -o "$DUMP" "$FILE" \
      || fail "the backup could not be decrypted (wrong passphrase or damaged file)."
    ;;
esac
pg_restore --list "$DUMP" >/dev/null 2>&1 || fail "the file is not a valid PostgreSQL dump."

# 3. restore into a scratch database
psql "$ADMIN" -v ON_ERROR_STOP=1 -qc "CREATE DATABASE \"$SCRATCH\"" >/dev/null
CREATED=1
TARGET="$(with_db "$ADMIN" "$SCRATCH")"
pg_restore --no-owner --no-privileges --exit-on-error -d "$TARGET" "$DUMP" >/dev/null 2>"$WORK/restore.log" \
  || { tail -5 "$WORK/restore.log" >&2; fail "pg_restore stopped with an error."; }
echo "Restore finished into scratch database $SCRATCH."

# 4. sanity checks
q() { psql "$TARGET" -tAc "$1"; }
tables="$(q "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'")"
[ "$tables" -ge 20 ] || fail "only $tables tables were restored."
revision="$(q "select count(*) from alembic_version")"
[ "$revision" = "1" ] || fail "alembic_version has $revision rows (expected 1)."
echo "tables: $tables, migration version: $(q 'select version_num from alembic_version')"

check_count() {  # name, minimum
  local n
  n="$(q "select count(*) from $1" 2>/dev/null)" || fail "table $1 is missing."
  echo "  $1: $n rows"
  [ "$n" -ge "$2" ] || fail "table $1 has $n rows (expected at least $2)."
  if [ -n "${SOURCE_DATABASE_URL:-}" ]; then
    local live
    live="$(psql "$(plain_url "$SOURCE_DATABASE_URL")" -tAc "select count(*) from $1")" || fail "could not count $1 in the live database."
    [ $((n * 2)) -ge "$live" ] || fail "$1: the backup has $n rows but the live database has $live."
  fi
}
check_count hospitals 1
check_count doctors 1
check_count patients 0
check_count consultations 0
check_count invoices 0
check_count audit_logs 0

echo "PASS: the backup restored and passed the checks."