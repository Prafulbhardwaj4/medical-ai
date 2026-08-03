from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SECRET_KEY: str = "changeme"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    SUPER_ADMIN_KEY: str = ""

    DATABASE_URL: str = "sqlite:///./medscribe.db"

    SARVAM_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    FAST2SMS_API_KEY: str = ""
    BASE_URL: str = "http://localhost:8000"

    # --- Patient Portal ---
    PORTAL_INVITE_SECRET: str = "changeme-invite-secret"
    PORTAL_INVITE_EXPIRE_DAYS: int = 30
    PORTAL_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    PORTAL_LINK_CONFIRM_EXPIRE_HOURS: int = 24
    PORTAL_FRONTEND_URL: str = "http://localhost:5501"

    # Temporary, pre-launch only: every hospital-registered phone number can
    # log in to the patient portal for the first time using this password.
    # Remove this entirely once real OTP delivery (WhatsApp/SMS) is wired up.
    PORTAL_DEFAULT_TEMP_PASSWORD: str = "Test1234"

    # How long an unpaid scheduled-slot booking holds its place before it's
    # treated as abandoned and the slot is released back for others to book.
    # Placeholder value pending real payment-gateway timing — easy to tune here.
    PORTAL_BOOKING_HOLD_MINUTES: int = 15

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

    # TAT tiers (Phase 5 item 17) — clock starts at accessioning (item 15), not order placement.
    # Send-out/referral tests (Phase 7, not yet built) will override this with the external lab's
    # own committed TAT once that exists, rather than ever padding a tier down to look routine.
    LAB_TAT_ROUTINE_HOURS: float = 24.0
    LAB_TAT_URGENT_HOURS: float = 4.0
    LAB_TAT_STAT_HOURS: float = 1.0

    class Config:
        env_file = ".env"

settings = Settings()