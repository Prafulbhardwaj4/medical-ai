# MedScribe Runbook

For the person on call. Plain steps, in the order you need them. Times are Indian time (IST).

## 1. What runs where

| Part | Where | Notes |
|---|---|---|
| Staff and patient websites | Vercel (`frontend/`) | Plain HTML, CSS and JavaScript. The API address is in `frontend/config.js`. |
| API | Render today, AWS planned (`backend/`) | FastAPI. Health: `/health/live` (never touches the database) and `/health` (checks the database, answers 503 if it is down). |
| Database | PostgreSQL (SQLite only for development) | Backups: section 6. |
| Files | Local disk by default, or an S3-compatible bucket when `STORAGE_BACKEND=s3` | Chat attachments and generated PDFs. |
| Speech to text | Sarvam (`SARVAM_API_KEY`) | Live scribe. |
| AI structuring | Groq (`GROQ_API_KEY`) | Turns the transcript into a prescription. |
| WhatsApp | Messages list that staff send by hand | No WhatsApp provider is connected. |
| Error tracking | Sentry, when `SENTRY_DSN` is set | No patient data is sent. |

## 2. Deploy

1. Make a branch, change the code, open a pull request. CI must be green (tests, migration safety, dependency audit, secret scan).
2. Merge to `main`. Vercel publishes the websites. Render builds and starts the API.
3. After the API starts, check `https://<api>/health` answers with 200, then sign in and open one patient.
4. If the release contains a migration, read section 4 first.

Typical start command (check the one set in Render): `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Never use `--reload` in production; the app refuses to start with it when it detects production (`RENDER` or `ENVIRONMENT=production` is set). The startup log prints which environment it detected.

## 3. Roll back

**Code only (no migration in the release):** in Render, open the service, Deploys, pick the last good deploy, Rollback. In Vercel, Deployments, the last good one, Promote to Production.

**Release with a migration:** migrations are written to be additive (new column, new table, new index), so the previous code keeps working on the new database. Roll the code back and leave the database as it is. Never run a migration "down" on live data. If a migration itself failed, nothing was half-applied on PostgreSQL (migrations run in a transaction); fix forward with a new migration.

**Data damage:** restore from a backup into a scratch database (section 6), compare, and copy back only what is needed. Never restore over the live database without a second person looking.

## 4. Migrations as a release step

Today every start runs the migrations (`RUN_MIGRATIONS_ON_BOOT=true`). To run them once, before the new code starts:

1. Set `RUN_MIGRATIONS_ON_BOOT=false` on the service.
2. Before each deploy that has a migration, run from your laptop:
   `python scripts/run_migrations.py --database-url "<production database url>"`
   It takes the same database lock the app uses, prints the version before and after, and exits 0 on success.
3. Check: `python scripts/check_alembic_head.py --database-url "<url>"` prints "OK: the database is at head", and `python scripts/check_schema_drift.py --database-url "<url>"` prints "OK: the database has every table and column the code uses". Only when both print OK is it safe to set `RUNTIME_SCHEMA_SYNC=false`.
4. Deploy the code.

Other boot switches (all default to today's behaviour): `RUNTIME_SCHEMA_SYNC` (adds missing columns at start and logs each one; set false once `check_alembic_head.py` is at head), `SEED_TUTORIAL_ON_BOOT`, `MASTER_CATALOG_AUTOLOAD_ON_BOOT`, `DAY_END_CATCHUP_ON_BOOT`. When more than one API instance starts together, a PostgreSQL lock makes them take turns for migrations and seeding.

Before deploying migration `c4e8a1d7f203` (one day-end close per hospital per day) run `python scripts/list_duplicate_day_end_closes.py`. If it lists anything, fix those rows by hand first; the migration stops with a message and deletes nothing if duplicates exist.

Every new migration is checked in CI by `scripts/check_migration_safety.py`: dropping or renaming a column or table, or narrowing a column type, fails the build unless a reviewed `# migration-safety: allow` comment is on that line.

## 5. Scheduler (background loops)

The loops (midnight day-end close, lab escalation, retention purges) run inside the API process. With several instances, a PostgreSQL lock elects one leader; the others check every `SCHEDULER_LEADER_RETRY_SECONDS`. `SCHEDULER_ENABLED=false` turns them off on an instance (for example a one-off worker). If the leader dies, another instance takes over within that interval. The midnight close catches up on missed days at start, in the background, so the API answers requests first.

## 6. Backups and restore

**Nightly backup:** GitHub Actions workflow "Nightly database backup" runs at 02:00 IST. It dumps the database, checks the dump can be read, encrypts it (AES-256, passphrase `BACKUP_PASSPHRASE`), uploads it to the private bucket and deletes copies older than 14 days.

Secrets to set in GitHub (Settings, Secrets and variables, Actions): `BACKUP_DATABASE_URL`, `BACKUP_PASSPHRASE`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`; optional `BACKUP_S3_REGION`, `BACKUP_S3_ENDPOINT` (for R2 or Backblaze). Optional variables: `PG_MAJOR` (must match the database server's major version, default 16), `BACKUP_RETENTION_DAYS`, `BACKUP_PREFIX`. Keep the passphrase somewhere other than GitHub too; a backup without it cannot be opened.

**Restore test (do this monthly, and once now):**
```
export RESTORE_ADMIN_URL="postgresql://user:pass@localhost:5432/postgres"   # a local server where a scratch database can be made
export BACKUP_PASSPHRASE="..."
export BACKUP_S3_BUCKET=... BACKUP_S3_ACCESS_KEY_ID=... BACKUP_S3_SECRET_ACCESS_KEY=...
bash scripts/restore_test.sh            # newest backup from the bucket
bash scripts/restore_test.sh file.gpg   # or a file you downloaded
```
It restores into a scratch database, checks the table count, the migration version and row counts (hospitals and doctors must not be empty), prints PASS or FAIL and removes the scratch database. A FAIL means do not trust that backup.

**Restore for real:** download the newest backup, decrypt with `gpg --decrypt`, restore into a NEW database with `pg_restore --no-owner --no-privileges -d <new database> file.dump`, check it, then point `DATABASE_URL` at it. Keep the old database until everything is verified.

## 7. Key rotation

All keys are Fernet keys unless stated. Make one with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
List-type settings take comma-separated keys, newest first; old keys stay in the list until the re-encryption script reports nothing unreadable.

| Secret | How to rotate | What happens |
|---|---|---|
| `TOTP_ENC_KEY` (2FA secrets) | Put the new key first, deploy, run `python scripts/rotate_totp_keys.py --dry-run` then without `--dry-run`. Remove the old key when it reports nothing unreadable. | Nobody has to set up 2FA again. |
| `DATA_ENC_KEYS` (field encryption) | New key first, keep old keys after it, deploy, run `python scripts/rotate_data_keys.py --dry-run`, then for real. Remove old keys afterwards. | Transparent. |
| First time turning on field encryption | Set `DATA_ENC_KEYS`, deploy, run `python scripts/encrypt_existing_data.py --dry-run`, then for real (safe to repeat). | Existing rows become encrypted; old plain values keep reading until then. |
| `WHATSAPP_MESSAGES_KEYS` / `WHATSAPP_MESSAGES_KEY` | Put the new key first in `WHATSAPP_MESSAGES_KEYS`, keep the old key in the list (or in the single `WHATSAPP_MESSAGES_KEY`). Remove the old one after the undo window and stored secrets have expired. | Secrets stored under the old key stay readable while it is listed. |
| `QR_HASH_KEY` | Set it once. New QR codes use it; old printed ones still verify through the SECRET_KEY hash. | Do not rotate `SECRET_KEY` while old printed QR codes must still work: their hash was made with it. |
| `SECRET_KEY` | Rotate `TOTP_ENC_KEY` first (so 2FA does not depend on it), set `QR_HASH_KEY`, then change `SECRET_KEY`. | Everyone is signed out once. QR codes printed before `QR_HASH_KEY` was set stop verifying. |
| `PORTAL_INVITE_SECRET` | Change it and redeploy. | Patient invite and registration links already sent stop working; patients can ask for a new one. |
| `SUPER_ADMIN_KEY` | Keep it EMPTY in production. Set it only for the minute you create a super admin, then empty it again. | |
| Database password | Change it at the database host, update `DATABASE_URL` (and `BACKUP_DATABASE_URL` in GitHub), redeploy. | A short blip while the API restarts. |
| `SARVAM_API_KEY`, `GROQ_API_KEY` | Create a new key at the provider, update it on the server, delete the old key at the provider. | The scribe works again on the next request. |

After any rotation run `python scripts/check_secrets_strength.py` (it prints PASS or FAIL per secret and never prints the secret itself).

## 8. Super admin access and 2FA

- Every super admin must have 2FA: `python scripts/list_superadmins_without_2fa.py` lists any that do not (exit code 1 if any).
- First 2FA setup needs a one-time code made for that account: `python scripts/issue_totp_enrolment_code.py name@example.com`. Shown once, valid 24 hours, works once.
- Locked out: `python scripts/reset_superadmin_2fa.py name@example.com --database-url "<url>"`. It prints which database it will change and waits for you to type `RESET`. It clears that account's 2FA and writes an audit entry; they sign in and set 2FA up again. It runs from your laptop (it only needs database access). Keep at least two super admins so one can recover the other.

## 9. Files and storage

Default is the server's disk, which Render wipes on every deploy for free instances. To use a bucket: set `STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_REGION` (and `S3_ENDPOINT_URL`, keys for R2 or Backblaze; on AWS leave the keys empty and use the server's role), then copy what exists:
`STORAGE_BACKEND=s3 python scripts/migrate_files_to_s3.py --dry-run`, then without `--dry-run` (safe to repeat; `--delete-local` removes local copies that were uploaded). `ENCRYPT_CHAT_FILES=true` encrypts new chat attachments (needs `DATA_ENC_KEYS`).

## 10. Moving the API (for example to AWS)

1. Deploy the new API with the same database settings and secrets.
2. Set `TRUSTED_PROXY_HOPS` to the real chain (1 for a load balancer, 2 for CloudFront plus load balancer) and check the startup log line shows the right client address.
3. Add the new origin to `CORS_EXTRA_ORIGINS`, change the production URL in `frontend/config.js`, and add the new origin to `connect-src` in `frontend/vercel.json`.
4. Set `PUBLIC_FRONTEND_URL` to your own permanent domain (printed QR codes carry it).
5. Keep the scribe connection alive: `WS_PING_INTERVAL_SECONDS` must stay below the load balancer idle timeout (60 s on AWS).
6. Run migrations as a release step (section 4) and use `AWS_SECRETS_ID` if secrets live in Secrets Manager.

## 11. Incidents

**Everyone gets errors or the site is down.** Open `/health/live`: if it fails, the API is down (Render logs, last deploy; roll back, section 3). If `/health/live` works but `/health` says 503, the database is down or slow: check the database host, then connection counts (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`).

**Bad deploy.** Roll back (section 3), then investigate.

**Many failed logins or a lockout wave.** Sentry raises an alert when failed logins pass `LOGIN_FAILURE_ALERT_THRESHOLD` inside `LOGIN_FAILURE_ALERT_WINDOW_SECONDS`. Each failure is in the audit log (account, network address, reason, never the password). A single attacker network is throttled on its own and does not lock the real user out. If the attack is large, set `REDIS_URL` so limits are shared across instances.

**Audit entries are failing.** The log shows `AUDIT_WRITE_FAILED` and Sentry gets the error. Requests keep working, but treat it as urgent: check the database and the audit table.

**Suspected data exposure.** Write down the time and what you saw. Rotate the exposed secret (section 7), sign everyone out by rotating `SECRET_KEY` if tokens may be exposed, check the audit log for who opened what (patient record opens, documents, PDFs and lists are logged), and call your lawyer: breach notice duties and timelines apply. Do not delete anything.

**Wrong patient data or a deletion request.** Admins can, for one patient in their own hospital: export (`GET /data-rights/patients/{id}/export`), correct demographic fields (`PUT /data-rights/patients/{id}/correct`), or anonymise (`POST /data-rights/patients/{id}/anonymise`, type `ANONYMISE <patient id>` to confirm). Anonymising is irreversible: it removes who the patient is and keeps invoices and clinical rows without identity. Every one is audited.

**Scribe will not start recording.** The doctor must first confirm "The patient has agreed to AI recording" (stored as a consent record under the current `CONSENT_NOTICE_VERSION`). If the notice version changes, consent is asked again.

**Disk or bucket full.** Retention is OFF by default. `CHAT_UPLOAD_RETENTION_DAYS` and `RAW_TRANSCRIPT_RETENTION_DAYS` turn on deletion of chat attachments and old transcripts; `WHATSAPP_MESSAGE_RETENTION_DAYS` defaults to 180. Medical records and audit rows are never deleted automatically.

## 12. Checks you can run any time

| Command | What it tells you |
|---|---|
| `python scripts/check_alembic_head.py` | Is the database at the newest migration. |
| `python scripts/check_secrets_strength.py` | Are the secrets long and random enough. |
| `python scripts/list_superadmins_without_2fa.py` | Which super admins have no 2FA. |
| `python scripts/list_missing_indexes.py` | Columns that may need an index (suggestions only, changes nothing). |
| `python scripts/list_duplicate_day_end_closes.py` | Duplicate day-end rows (read only). |

Database for these comes from `--database-url`, else `DATABASE_URL`.

## 13. Environment variables

Set in the Render dashboard (Environment) or in `backend/.env` for local work. Anything marked "(empty)" is off or unset by default. Defaults keep today's behaviour; the app logs a warning at start for any safe setting that is not yet in place.

Also read straight from the environment: `RENDER` (set by Render) and `ENVIRONMENT=production` (set it yourself on AWS) tell the app it is in production. CI and tests use `MEDSCRIBE_TEST_PG_URL`. The backup workflow and `scripts/backup_s3.py` use `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`, `BACKUP_S3_REGION`, `BACKUP_S3_ENDPOINT`, `BACKUP_PREFIX` and `BACKUP_RETENTION_DAYS`; `scripts/restore_test.sh` uses `RESTORE_ADMIN_URL`, `BACKUP_PASSPHRASE` and `SOURCE_DATABASE_URL`.

| Name | Default | What it does |
|---|---|---|
| `SECRET_KEY` | `(weak placeholder, must be set)` | Signs staff login tokens (and is the old key for QR hashes and 2FA secrets). Random, 32+ characters. Required. |
| `ALGORITHM` | `HS256` | Login token algorithm. Leave as HS256. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Staff login token lifetime (minutes). |
| `SUPER_ADMIN_KEY` | `(empty)` | Header key for creating a super admin. Leave EMPTY in production: the route then does not exist. |
| `DEV_CAPTCHA_ANSWER` | `(empty)` | Local development only. The app refuses to start in production if set. |
| `DEV_SKIP_SUPERADMIN_2FA` | `False` | Local development only. The app refuses to start in production if true. |
| `DATABASE_URL` | `sqlite:///./medscribe.db` | Database address. SQLite for development, PostgreSQL in production. |
| `SARVAM_API_KEY` | `(empty)` | Speech-to-text provider key (live scribe). |
| `GROQ_API_KEY` | `(empty)` | AI structuring provider key. |
| `BASE_URL` | `http://localhost:8000` | This API's own address. |
| `PUBLIC_FRONTEND_URL` | `https://medical-s-ai.vercel.app` | Staff site address. It is printed inside every prescription and invoice QR code, so it must be your permanent domain. |
| `PORTAL_INVITE_SECRET` | `(weak placeholder, must be set)` | Signs patient invite and registration links. Random, 32+ characters. |
| `PORTAL_INVITE_EXPIRE_DAYS` | `30` | Invite link lifetime (days). |
| `PORTAL_ACCESS_TOKEN_EXPIRE_MINUTES` | `240` | Patient portal login lifetime (minutes). Renewed while the patient is active. |
| `PORTAL_SESSION_MAX_MINUTES` | `720` | Hard cap on a portal session, counted from the original sign-in. |
| `PORTAL_TEMP_PASSWORD` | `(empty)` | Leave empty. Empty means every account gets its own random temporary password. |
| `PORTAL_LINK_CONFIRM_EXPIRE_HOURS` | `24` | Link-confirmation token lifetime (hours). |
| `PORTAL_FRONTEND_URL` | `http://localhost:5501` | Patient portal site address. |
| `WHATSAPP_MESSAGES_KEY` | `(empty)` | Single Fernet key for the WhatsApp message secrets. Required in production. Still read after WHATSAPP_MESSAGES_KEYS is set. |
| `WHATSAPP_UNDO_WINDOW_SECONDS` | `90` | How long a sent or cancelled message's secret is kept for Undo. |
| `CORS_EXTRA_ORIGINS` | `(empty)` | Extra allowed website origins, comma-separated. Add the new staff site here when it moves. |
| `CORS_ORIGIN_REGEX` | `(empty)` | Pattern for allowed preview sites. The app logs a warning at start when it is set; keep it narrow. |
| `TRUSTED_PROXY_HOPS` | `1` | Proxies in front of the API: Render 1, AWS load balancer only 1, CloudFront plus load balancer 2, local 0. Check the startup log line. |
| `PORTAL_BOOKING_HOLD_MINUTES` | `15` | How long an unpaid online booking holds its slot. |
| `PORTAL_PAYMENT_GRACE_MINUTES` | `60` | Minutes after the slot a patient may still pay at reception and keep the slot. |
| `PORTAL_MAX_UNPAID_HOLDS_PER_ACCOUNT` | `3` | Most unpaid future slot holds per patient account. |
| `PORTAL_CANCEL_FULL_REFUND_HOURS` | `24` | Cancelling within this many hours of booking refunds in full. |
| `PORTAL_CANCEL_PARTIAL_REFUND_PERCENT` | `30` | Refund percentage after that window. |
| `PORTAL_CANCEL_BLOCK_HOURS_BEFORE_CONSULT` | `24` | No cancellation inside this many hours of the consultation. |
| `PORTAL_REVIEW_RESPONSE_MINUTES` | `60` | Minutes before an unactioned appointment review is chased. |
| `PORTAL_REVIEW_AUTO_DECLINE_GRACE_MINUTES` | `60` | Further minutes before an unactioned review is auto-declined with a full refund. |
| `PORTAL_GRACE_WINDOW_MINUTES` | `5` | Minutes a patient may arrive late and keep priority. |
| `PORTAL_NO_SHOW_THRESHOLD_MINUTES` | `60` | Minutes after the slot before a possible no-show is flagged. |
| `LAB_CRITICAL_ACK_MINUTES` | `15` | Critical lab value unacknowledged this long goes to the nurse or ward. |
| `LAB_CRITICAL_ESCALATION_GRACE_MINUTES` | `15` | Still unacknowledged this much longer goes to the admin. |
| `VITALS_CRITICAL_ACK_MINUTES` | `10` | Critical vitals unacknowledged this long goes to the nurse or ward. |
| `VITALS_CRITICAL_ESCALATION_GRACE_MINUTES` | `10` | Still unacknowledged this much longer goes to the admin. |
| `ADMISSION_SAMPLE_OVERDUE_MINUTES` | `120` | Ward sample not collected this long after ordering alerts lab staff. |
| `LAB_TAT_ROUTINE_HOURS` | `24.0` | Lab turnaround target, routine tests (hours). |
| `LAB_TAT_URGENT_HOURS` | `4.0` | Lab turnaround target, urgent tests (hours). |
| `LAB_TAT_STAT_HOURS` | `1.0` | Lab turnaround target, STAT tests (hours). |
| `TOTP_ENC_KEY` | `(empty)` | Key(s) that encrypt 2FA secrets, comma-separated, newest first. Unset: the SECRET_KEY-derived key is used and a warning is logged. |
| `QR_HASH_KEY` | `(empty)` | Key for new QR verification hashes. Old SECRET_KEY hashes keep verifying. Unset: SECRET_KEY is used and a warning is logged. |
| `WHATSAPP_MESSAGES_KEYS` | `(empty)` | Fernet keys for WhatsApp message secrets, comma-separated, newest first. |
| `DATA_ENC_KEYS` | `(empty)` | Fernet keys for field encryption (transcripts, ABHA number, WhatsApp message text), comma-separated, newest first. Empty: no field encryption. |
| `RUN_MIGRATIONS_ON_BOOT` | `True` | true (default): every start runs migrations. Set false once migrations run as a release step. |
| `RUNTIME_SCHEMA_SYNC` | `True` | true (default): every start adds missing columns outside migrations and logs each one. Set false once check_alembic_head.py says the database is at head. |
| `SCHEDULER_ENABLED` | `True` | false turns the background loops off on this instance. |
| `SEED_TUTORIAL_ON_BOOT` | `True` | false skips tutorial seeding at start. |
| `MASTER_CATALOG_AUTOLOAD_ON_BOOT` | `True` | false skips the master catalogue autoload at start. |
| `DAY_END_CATCHUP_ON_BOOT` | `True` | false skips the day-end catch-up at start. |
| `DB_REQUIRE_SSL` | `False` | true adds sslmode=require to a PostgreSQL URL that has no sslmode. |
| `DB_POOL_SIZE` | `5` | Database connections kept open per instance. |
| `DB_MAX_OVERFLOW` | `10` | Extra connections allowed under load. |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | Connections older than this are replaced. |
| `MAX_BODY_BYTES` | `12582912` | Largest accepted request body. Uploads and imports have their own lower caps. |
| `DEFAULT_RATE_LIMIT` | `600/minute` | Limit for every request per client, for example 600/minute. |
| `REDIS_URL` | `(empty)` | When set, rate limits and login throttles are shared across instances and survive restarts. Empty: in memory. |
| `SENTRY_DSN` | `(empty)` | Error tracking address. Empty: off. No patient data is sent. |
| `LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING or ERROR. |
| `LOGIN_FAILURE_ALERT_THRESHOLD` | `20` | Failed logins within the window that raise an alert. |
| `LOGIN_FAILURE_ALERT_WINDOW_SECONDS` | `300` | Length of that window. |
| `HEALTH_DB_TIMEOUT_SECONDS` | `3` | /health answers 503 if the database takes longer than this. |
| `BOOT_LOCK_TIMEOUT_SECONDS` | `600` | How long a starting instance waits for another one's migrations or seeding. |
| `WS_PING_INTERVAL_SECONDS` | `20` | Scribe connection keep-alive. Keep it below the load balancer idle timeout (60 s on AWS). |
| `SCHEDULER_LEADER_RETRY_SECONDS` | `30` | How often a non-leader instance checks whether it can take over the loops. |
| `CONSENT_NOTICE_VERSION` | `v0-PENDING-LEGAL-REVIEW` | Version label of the patient consent text. Put the lawyer-approved version here. A warning is logged while it contains PENDING. |
| `RAW_TRANSCRIPT_RETENTION_DAYS` | `0` | 0 = keep forever. Otherwise recording transcripts of confirmed consultations older than this are blanked. |
| `CHAT_UPLOAD_RETENTION_DAYS` | `0` | 0 = keep forever. Otherwise chat attachments older than this are deleted. |
| `WHATSAPP_MESSAGE_RETENTION_DAYS` | `180` | WhatsApp message rows older than this are deleted. 0 = off. |
| `STORAGE_BACKEND` | `local` | local (this server's disk) or s3 (S3-compatible bucket). |
| `S3_BUCKET` | `(empty)` | Bucket name when STORAGE_BACKEND=s3. |
| `S3_REGION` | `(empty)` | Bucket region. |
| `S3_ENDPOINT_URL` | `(empty)` | Only for R2, Backblaze and similar. Empty on AWS. |
| `S3_ACCESS_KEY_ID` | `(empty)` | Leave empty on AWS to use the server's role. |
| `S3_SECRET_ACCESS_KEY` | `(empty)` | Leave empty on AWS to use the server's role. |
| `S3_PREFIX` | `(empty)` | Optional folder prefix inside the bucket. |
| `S3_SSE` | `(empty)` | Server-side encryption: empty, AES256 or aws:kms. |
| `ENCRYPT_CHAT_FILES` | `False` | true encrypts new chat attachments at rest (needs DATA_ENC_KEYS). |
| `AWS_SECRETS_ID` | `(empty)` | When set as a real environment variable, secrets are loaded from AWS Secrets Manager before the settings are read. |