from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SECRET_KEY: str = "changeme"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Brand. BRAND_NAME is the product name; COMPANY_LEGAL_NAME is the registered company
    # name (used in invoices, terms, privacy, agreements, PDF legal footers).
    # Change COMPANY_LEGAL_NAME after incorporation (env var COMPANY_LEGAL_NAME).
    BRAND_NAME: str = "ScribeKare"
    COMPANY_LEGAL_NAME: str = "ScribeKare"

    SUPER_ADMIN_KEY: str = ""

    # LOCAL DEV ONLY. When set, this fixed text is accepted as the captcha answer on
    # login. It is ignored (and the app refuses to start) in production.
    DEV_CAPTCHA_ANSWER: str = ""
    DEV_SKIP_SUPERADMIN_2FA: bool = False  # local dev only; startup refuses to run with it in production

    DATABASE_URL: str = "sqlite:///./medscribe.db"

    SARVAM_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    BASE_URL: str = "http://localhost:8000"

    # Main staff-frontend deployment — used to build the verify.html QR
    # links on prescriptions and invoices. Single source of truth so it
    # can never drift from what verify.html's own "only valid at..." copy
    # says (item 6).
    PUBLIC_FRONTEND_URL: str = "https://medical-s-ai.vercel.app"

    # --- Patient Portal ---
    PORTAL_INVITE_SECRET: str = "changeme-invite-secret"
    PORTAL_INVITE_EXPIRE_DAYS: int = 30
    # Portal login token lifetime (was 7 days). The portal swaps it for a fresh one while the patient is active
    # (POST /portal/auth/refresh), but never beyond PORTAL_SESSION_MAX_MINUTES after the original sign-in.
    # Tokens already issued keep working until their own expiry.
    PORTAL_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 4
    PORTAL_SESSION_MAX_MINUTES: int = 60 * 12
    # "" (default) = every patient account gets its own random temporary password. Never set a shared one in production.
    PORTAL_TEMP_PASSWORD: str = ""
    PORTAL_LINK_CONFIRM_EXPIRE_HOURS: int = 24
    PORTAL_FRONTEND_URL: str = "http://localhost:5501"

    # --- WhatsApp messages list (staff send by hand until Meta approval) ---
    # Fernet key that encrypts temporary passwords / codes kept in the messages table.
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # REQUIRED in production (the app refuses to start without it). Local dev derives a key from SECRET_KEY.
    WHATSAPP_MESSAGES_KEY: str = ""
    # After "Mark as sent" / "Cancel" the stored secret stays this long so Undo can restore it, then it is deleted.
    WHATSAPP_UNDO_WINDOW_SECONDS: int = 90

    # CORS. Bearer tokens live in localStorage (no cookies), so credentials are
    # never sent cross-origin. Allowed origins = PUBLIC_FRONTEND_URL + the two
    # below. Add more with CORS_EXTRA_ORIGINS (comma-separated exact origins).
    # To allow Vercel preview deploys, set CORS_ORIGIN_REGEX on Render, e.g.
    #   https://medical-s-ai-[a-z0-9-]+-<your-team>\.vercel\.app
    CORS_EXTRA_ORIGINS: str = ""
    CORS_ORIGIN_REGEX: str = ""

    # How many reverse-proxy hops sit in front of the app (Render's edge = 1).
    # Rate limiting reads the client IP from that many entries from the RIGHT
    # of X-Forwarded-For, so a client can't spoof its own IP. Set to 0 to use
    # the raw socket address (local dev).
    # Real values (check the chain, then confirm the startup log line "TRUSTED_PROXY_HOPS=..." shows the sample client IP):
    #   Render (its edge)              -> 1
    #   AWS: ALB only                  -> 1   (X-Forwarded-For = "client")
    #   AWS: CloudFront + ALB          -> 2   (X-Forwarded-For = "client, cloudfront-edge")
    #   Local dev, no proxy            -> 0
    TRUSTED_PROXY_HOPS: int = 1

    # How long an unpaid scheduled-slot booking holds its place before it's
    # treated as abandoned and the slot is released back for others to book.
    # Placeholder value pending real payment-gateway timing — easy to tune here.
    PORTAL_BOOKING_HOLD_MINUTES: int = 15

    # Pay-at-reception rule (no payment gateway yet): a patient may pay up to this many minutes
    # AFTER their booked slot time and still keep that slot. Later than that, reception must
    # choose a new slot or the walk-in queue. Same rule for online and phone bookings.
    PORTAL_PAYMENT_GRACE_MINUTES: int = 60

    # One portal account may not sit on more than this many unpaid, future slot holds at once.
    PORTAL_MAX_UNPAID_HOLDS_PER_ACCOUNT: int = 3

    # Refund tiers for patient-initiated cancellation — placeholder values
    # pending legal sign-off, kept as named constants so they're easy to
    # adjust later rather than scattered magic numbers.
    PORTAL_CANCEL_FULL_REFUND_HOURS: int = 24            # cancel within this many hours of booking -> 100% refund
    PORTAL_CANCEL_PARTIAL_REFUND_PERCENT: int = 30       # cancel after that (but still outside the block window) -> this %
    PORTAL_CANCEL_BLOCK_HOURS_BEFORE_CONSULT: int = 24   # inside this many hours of consultation time -> cancellation blocked

    # Hospital-side appointment review deadlines.
    PORTAL_REVIEW_RESPONSE_MINUTES: int = 60             # first review alert -> follow-up alert if unactioned this long
    PORTAL_REVIEW_AUTO_DECLINE_GRACE_MINUTES: int = 60    # follow-up -> auto-decline (full refund) after this much longer

    # Online booking day-of grace window (Phase 2 item 7).
    PORTAL_GRACE_WINDOW_MINUTES: int = 5   # patient can arrive up to this many minutes past their slot and still get priority

    # No-show / late handling (Phase 3 item 8).
    PORTAL_NO_SHOW_THRESHOLD_MINUTES: int = 60   # not consulted this long past slot time -> flagged as a possible no-show

    # Critical lab-value notification escalation (Lab Flow Phase 1).
    LAB_CRITICAL_ACK_MINUTES: int = 15               # ordering doctor unacknowledged this long -> escalate to nurse/ward
    LAB_CRITICAL_ESCALATION_GRACE_MINUTES: int = 15  # escalated but still unacknowledged this much longer -> notify admin directly

    # Critical IPD-vitals notification escalation — same shape as lab, tighter clock
    # since an abnormal vital is often faster-moving than a lab result.
    VITALS_CRITICAL_ACK_MINUTES: int = 10               # admitting doctor unacknowledged this long -> escalate to nurse/ward
    VITALS_CRITICAL_ESCALATION_GRACE_MINUTES: int = 10  # escalated but still unacknowledged this much longer -> notify admin directly

    # Admitted-patient sample collection (Lab Flow).
    ADMISSION_SAMPLE_OVERDUE_MINUTES: int = 120  # sample still not collected this long after a ward test was ordered -> notify lab staff

    # TAT tiers (Phase 5 item 17) — clock starts at accessioning (item 15), not order placement.
    # Send-out/referral tests (Phase 7, not yet built) will override this with the external lab's
    # own committed TAT once that exists, rather than ever padding a tier down to look routine.
    LAB_TAT_ROUTINE_HOURS: float = 24.0
    LAB_TAT_URGENT_HOURS: float = 4.0
    LAB_TAT_STAT_HOURS: float = 1.0

    # ------------------------------------------------------------------
    # Key separation. All optional: unset = today's behaviour + a startup warning.
    # Generate any Fernet key with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # ------------------------------------------------------------------
    # 2FA secrets. Comma-separated, newest first. Old SECRET_KEY-derived key is always still tried on read.
    TOTP_ENC_KEY: str = ""
    # Key for QR / verification hashes. Old SECRET_KEY hashes keep verifying.
    QR_HASH_KEY: str = ""
    # WhatsApp temp-secret keys, comma-separated, newest first. WHATSAPP_MESSAGES_KEY (single) is still read.
    WHATSAPP_MESSAGES_KEYS: str = ""
    # Field-level encryption keys (Fernet), comma-separated, newest first. Empty = no field encryption.
    DATA_ENC_KEYS: str = ""

    # ------------------------------------------------------------------
    # Boot behaviour (defaults = today's behaviour)
    # ------------------------------------------------------------------
    RUN_MIGRATIONS_ON_BOOT: bool = True
    RUNTIME_SCHEMA_SYNC: bool = True
    SCHEDULER_ENABLED: bool = True
    SEED_TUTORIAL_ON_BOOT: bool = True
    MASTER_CATALOG_AUTOLOAD_ON_BOOT: bool = True
    DAY_END_CATCHUP_ON_BOOT: bool = True

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    DB_REQUIRE_SSL: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 1800

    # ------------------------------------------------------------------
    # Requests and rate limits
    # ------------------------------------------------------------------
    MAX_BODY_BYTES: int = 12 * 1024 * 1024
    DEFAULT_RATE_LIMIT: str = "600/minute"
    REDIS_URL: str = ""

    # ------------------------------------------------------------------
    # Monitoring and logging
    # ------------------------------------------------------------------
    SENTRY_DSN: str = ""
    LOG_LEVEL: str = "INFO"
    LOGIN_FAILURE_ALERT_THRESHOLD: int = 20
    LOGIN_FAILURE_ALERT_WINDOW_SECONDS: int = 300

    # ------------------------------------------------------------------
    # Production readiness
    # ------------------------------------------------------------------
    HEALTH_DB_TIMEOUT_SECONDS: int = 3          # /health gives up on the database after this long and answers 503
    BOOT_LOCK_TIMEOUT_SECONDS: int = 600        # how long a starting instance waits for another one's migrations/seeding
    WS_PING_INTERVAL_SECONDS: int = 20          # scribe websocket keep-alive (AWS load balancer idle timeout is 60 s)
    SCHEDULER_LEADER_RETRY_SECONDS: int = 30    # a non-leader instance re-checks for leadership this often

    # ------------------------------------------------------------------
    # Consent notice version (put the lawyer-approved version here, no code change needed)
    # ------------------------------------------------------------------
    CONSENT_NOTICE_VERSION: str = "v0-PENDING-LEGAL-REVIEW"

    # ------------------------------------------------------------------
    # Retention. 0 = OFF (nothing is deleted). Medical records and audit rows are never auto-deleted.
    # ------------------------------------------------------------------
    RAW_TRANSCRIPT_RETENTION_DAYS: int = 0
    CHAT_UPLOAD_RETENTION_DAYS: int = 0
    WHATSAPP_MESSAGE_RETENTION_DAYS: int = 180

    # ------------------------------------------------------------------
    # File storage. local = files stay on this server's disk (today's behaviour).
    # s3 = S3-compatible bucket (AWS S3, Cloudflare R2, Backblaze B2). Leave the access keys empty on AWS to use the server's role.
    # ------------------------------------------------------------------
    STORAGE_BACKEND: str = "local"
    S3_BUCKET: str = ""
    S3_REGION: str = ""
    S3_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_PREFIX: str = ""
    S3_SSE: str = ""                  # "" , "AES256" or "aws:kms"
    ENCRYPT_CHAT_FILES: bool = False  # encrypt new chat attachments at rest (needs DATA_ENC_KEYS)

    # ------------------------------------------------------------------
    # Optional AWS Secrets Manager / SSM loader (off when empty)
    # ------------------------------------------------------------------
    AWS_SECRETS_ID: str = ""

    class Config:
        env_file = ".env"

# Optional: fills environment variables from AWS Secrets Manager BEFORE the settings are read.
# Off unless AWS_SECRETS_ID is set as a real environment variable.
from app.aws_secrets import load_aws_secrets
load_aws_secrets()

settings = Settings()


# ---------------------------------------------------------------------------
# Startup secret validation
# ---------------------------------------------------------------------------
import os
import warnings

_WEAK_SECRETS = {
    "", "changeme", "changeme-invite-secret", "your_secret_key_here",
    "secret", "password",
}
_MIN_SECRET_LEN = 32


def parse_key_list(*values) -> list:
    """Splits comma-separated key settings into one ordered list (first = newest), without
    blanks or duplicates. Earlier arguments come first."""
    out = []
    for value in values:
        for part in str(value or "").split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def _is_production(s) -> bool:
    # Render sets RENDER=true automatically. Any non-SQLite DB also counts.
    return (
        bool(os.getenv("RENDER"))
        or os.getenv("ENVIRONMENT", "").lower() == "production"
        or not s.DATABASE_URL.startswith("sqlite")
    )


def validate_startup_secrets(s) -> None:
    problems = []
    if s.DEV_SKIP_SUPERADMIN_2FA and _is_production(s):
        raise RuntimeError("Refusing to start: DEV_SKIP_SUPERADMIN_2FA must never be set in production")
    if s.DEV_CAPTCHA_ANSWER and _is_production(s):
        raise RuntimeError("Refusing to start: DEV_CAPTCHA_ANSWER must never be set in production")
    if _is_production(s):
        try:
            from cryptography.fernet import Fernet
            _wa_keys = parse_key_list(s.WHATSAPP_MESSAGES_KEYS, s.WHATSAPP_MESSAGES_KEY)
            if not _wa_keys:
                raise ValueError("no WhatsApp key")
            for _k in _wa_keys:
                Fernet(_k.encode())
        except Exception:
            problems.append("WHATSAPP_MESSAGES_KEY is missing or is not a valid Fernet key")
    for name in ("SECRET_KEY", "PORTAL_INVITE_SECRET"):
        value = getattr(s, name)
        if value in _WEAK_SECRETS or len(value) < _MIN_SECRET_LEN:
            problems.append(f"{name} is unset, default, or shorter than {_MIN_SECRET_LEN} chars")
    if not s.SUPER_ADMIN_KEY:
        # Not fatal: the key-protected endpoints reject every request while
        # this is empty (see verify_super_admin_key in admin.py).
        warnings.warn("SUPER_ADMIN_KEY is not set; create-superadmin is disabled.")
    if problems:
        msg = "Refusing to start: " + "; ".join(problems)
        if _is_production(s):
            raise RuntimeError(msg)
        warnings.warn("WARNING (dev only, would block production): " + msg)


def log_startup_warnings(s) -> None:
    """Clear startup warnings for the optional safety settings. Never prints a secret value.
    A key that is set but not a valid Fernet key stops the app in production (and warns in dev)."""
    import logging
    from cryptography.fernet import Fernet

    log = logging.getLogger("medscribe")
    prod = _is_production(s)

    bad = []
    for name in ("TOTP_ENC_KEY", "DATA_ENC_KEYS", "WHATSAPP_MESSAGES_KEYS"):
        for k in parse_key_list(getattr(s, name)):
            try:
                Fernet(k.encode())
            except Exception:
                bad.append(f"{name} contains a value that is not a valid Fernet key")
                break
    if (s.STORAGE_BACKEND or "local").strip().lower() not in ("local", "s3"):
        bad.append("STORAGE_BACKEND must be local or s3")
    if (s.STORAGE_BACKEND or "").strip().lower() == "s3" and not (s.S3_BUCKET or "").strip():
        bad.append("STORAGE_BACKEND is s3 but S3_BUCKET is not set")
    if s.ENCRYPT_CHAT_FILES and not parse_key_list(s.DATA_ENC_KEYS):
        log.warning("ENCRYPT_CHAT_FILES is on but DATA_ENC_KEYS is not set: chat files are stored unencrypted.")
    if s.QR_HASH_KEY and len(s.QR_HASH_KEY.strip()) < _MIN_SECRET_LEN:
        bad.append(f"QR_HASH_KEY is shorter than {_MIN_SECRET_LEN} chars")
    if bad:
        msg = "Refusing to start: " + "; ".join(bad)
        if prod:
            raise RuntimeError(msg)
        log.warning("WARNING (dev only, would block production): %s", msg)

    if not parse_key_list(s.TOTP_ENC_KEY):
        log.warning("TOTP_ENC_KEY is not set: 2FA secrets are still encrypted with a key derived from SECRET_KEY. "
                    "Set TOTP_ENC_KEY, then run scripts/rotate_totp_keys.py.")
    if not (s.QR_HASH_KEY or "").strip():
        log.warning("QR_HASH_KEY is not set: QR verification hashes still depend on SECRET_KEY. "
                    "Set QR_HASH_KEY (old printed QR codes keep working).")
    if prod and not parse_key_list(s.DATA_ENC_KEYS):
        log.warning("DATA_ENC_KEYS is not set: sensitive fields (transcripts, ABHA numbers, WhatsApp text) are stored unencrypted.")
    from urllib.parse import urlparse
    _front_host = (urlparse(s.PUBLIC_FRONTEND_URL or "").hostname or "").lower()
    if prod and (_front_host.endswith("vercel.app") or _front_host.endswith("onrender.com")
                 or _front_host in ("localhost", "127.0.0.1")):
        log.warning("PUBLIC_FRONTEND_URL points at %s, a platform host: every prescription and invoice QR code "
                    "carries this address. Set PUBLIC_FRONTEND_URL to your own domain before the AWS move.", _front_host)
    if "PENDING" in (s.CONSENT_NOTICE_VERSION or "").upper():
        log.warning("CONSENT_NOTICE_VERSION still contains PENDING: the consent notice text has not been approved by legal review.")
    if (s.CORS_ORIGIN_REGEX or "").strip():
        import re as _re
        log.warning("CORS_ORIGIN_REGEX is set to: %s", s.CORS_ORIGIN_REGEX)
        try:
            _rx = _re.compile(s.CORS_ORIGIN_REGEX)
            _outside = [o for o in ("https://example.com", "https://evil.example.com", "https://attacker.vercel.app",
                                    "https://medical-s-ai-x.attacker.vercel.app", "http://localhost:9999")
                        if _rx.fullmatch(o)]
            if _outside:
                log.warning("CORS_ORIGIN_REGEX can match origins outside your Vercel team (for example %s). "
                            "Tighten it to your own team name.", _outside[0])
        except _re.error:
            log.warning("CORS_ORIGIN_REGEX is not a valid regular expression.")