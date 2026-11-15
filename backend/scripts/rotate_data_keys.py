"""Re-encrypts every encrypted column with the newest DATA_ENC_KEYS key.

    python scripts/rotate_data_keys.py --dry-run     (shows what would change, writes nothing)
    python scripts/rotate_data_keys.py               (does it, in batches)

Put the NEW key first in DATA_ENC_KEYS and keep the old keys after it, then run this. When it
reports nothing unreadable, the old keys can be removed. Values that cannot be read with any key
are listed and left untouched. Database comes from DATABASE_URL (environment or .env).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401  (registers every model)
from app.config import parse_key_list, settings  # noqa: E402
from app.database import engine  # noqa: E402
from app.utils.field_crypto import is_encrypted, rotate_value  # noqa: E402

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
    unreadable = []
    for table, column in TARGETS:
        last_id, changed = 0, 0
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
                    if not is_encrypted(value):
                        continue
                    new_value = rotate_value(value)
                    if new_value is None:
                        unreadable.append(f"{table}.{column} id {row_id}")
                        continue
                    if not dry:
                        conn.execute(text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),
                                     {"v": new_value, "id": row_id})
                    changed += 1
        print(f"{table}.{column}: {'would re-encrypt' if dry else 're-encrypted'} {changed}")
    if unreadable:
        print("Could not read (left untouched):")
        for item in unreadable:
            print("  ", item)
        sys.exit(2)


if __name__ == "__main__":
    main()