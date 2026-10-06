from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SECRET_KEY: str = "changeme"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    SUPER_ADMIN_KEY: str = ""

    # LOCAL DEV ONLY. When set, this fixed text is accepted as the captcha answer on
    # login. It is ignored (and the app refuses to start) in production.
    DEV_CAPTCHA_ANSWER: str = ""
    DEV_SKIP_SUPERADMIN_2FA: bool = False  # local dev only; startup refuses to run with it in production

    DATABASE_URL: str = "sqlite:///./medscribe.db"

    SARVAM_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    BASE_URL: str = "http://localhost:8000"

    # Main staff-frontend deployment — used to build the verify.html QR
    # links on prescriptions and invoices. Single source of truth so it
    # can never drift from what verify.html's own "only valid at..." copy
    # says (item 6).
    PUBLIC_FRONTEND_URL: str = "https://medical-s-ai.vercel.app"

    # --- Patient Portal ---
    PORTAL_INVITE_SECRET: str = "changeme-invite-secret"
    PORTAL_INVITE_EXPIRE_DAYS: int = 30
    PORTAL_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    # TEMPORARY, until WhatsApp delivery is live. Set either to "" to switch it off.
    PORTAL_TEMP_PASSWORD: str = "Test1234"   # first-login password for patients; they must replace it
    PORTAL_FIXED_OTP: str = "1234"           # "" = real random 6-digit OTP
    PORTAL_LINK_CONFIRM_EXPIRE_HOURS: int = 24
    PORTAL_FRONTEND_URL: str = "http://localhost:5501"

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

    class Config:
        env_file = ".env"

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