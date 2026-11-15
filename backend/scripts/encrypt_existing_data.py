"""Encrypts the sensitive columns that are still stored as plain text.

    python scripts/encrypt_existing_data.py --dry-run     (shows what would change, writes nothing)
    python scripts/encrypt_existing_data.py               (does it, in batches)

Needs DATA_ENC_KEYS set. Safe to run again: values that are already encrypted are skipped.
Database comes from DATABASE_URL (environment or .env).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401  (registers every model)
from app.config import parse_key_list, settings  # noqa: E402
from app.database import engine  # noqa: E402
from app.utils.field_crypto import encrypt_value, is_encrypted  # noqa: E402

TARGETS = [
    ("consultations", "raw_transcript"),
    ("patients", "abha_number"),
    ("whatsapp_messages", "message_text"),
]
BATCH = 200


def main():
    dry = "--dry-run" in sys.argv[1:]
    if not parse_key_list(settings.DATA_ENC_KEYS):
        print("DATA_ENC_KEYS is not set. Set it first, then run this again.")
        sys.exit(1)
    print("Database:", engine.url.render_as_string(hide_password=True))
    for table, column in TARGETS:
        last_id, changed, skipped = 0, 0, 0
        while True:
            with engine.begin() as conn:
                rows = conn.execute(
                    text(f"SELECT id, {column} FROM {table} WHERE id > :last AND {column} IS NOT NULL ORDER BY id LIMIT :n"),
                    {"last": last_id, "n": BATCH},
                ).fetchall()
                if not rows:
                    break
                for row_id, value in rows:
                    last_id = row_id
                    if value == "" or is_encrypted(value):
                        skipped += 1
                        continue
                    if not dry:
                        conn.execute(text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),
                                     {"v": encrypt_value(value), "id": row_id})
                    changed += 1
        print(f"{table}.{column}: {'would encrypt' if dry else 'encrypted'} {changed}, already done or empty {skipped}")


if __name__ == "__main__":
    main()