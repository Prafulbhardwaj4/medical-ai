import httpx
from app.config import settings

FAST2SMS_URL = "https://www.fast2sms.com/dev/bulkV2"

def send_sms(to_phone: str, doctor_name: str, token_number: str, pdf_url: str, extra_line: str = None) -> dict:
    """Send prescription link via Fast2SMS. Optional extra_line (e.g. a
    one-time portal invite or link-confirmation prompt) rides this same
    message instead of triggering a separate SMS."""

    # Fast2SMS needs 10-digit number without country code
    phone = to_phone.replace("+91", "").replace("+", "").strip()

    message = (
        f"Prescription from {doctor_name}. "
        f"Token: {token_number}. "
        f"Download: {pdf_url}"
    )
    if extra_line:
        message += f" {extra_line}"

    headers = {
        "authorization": settings.FAST2SMS_API_KEY,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    payload = {
        "route": "q",  # quick transactional route
        "message": message,
        "language": "english",
        "flash": 0,
        "numbers": phone
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(FAST2SMS_URL, headers=headers, data=payload)

        result = response.json()
        if result.get("return") == True:
            return {"status": "sent", "details": result}
        else:
            return {"status": "failed", "error": result.get("message", "Unknown error")}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def send_otp_sms(to_phone: str, otp: str) -> dict:
    """Send a portal signup/login OTP via Fast2SMS."""
    phone = to_phone.replace("+91", "").replace("+", "").strip()
    message = f"Your MedScribe Health Portal OTP is {otp}. Valid for 10 minutes. Do not share this code."

    headers = {
        "authorization": settings.FAST2SMS_API_KEY,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "route": "q",
        "message": message,
        "language": "english",
        "flash": 0,
        "numbers": phone
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(FAST2SMS_URL, headers=headers, data=payload)
        result = response.json()
        if result.get("return") == True:
            return {"status": "sent", "details": result}
        else:
            return {"status": "failed", "error": result.get("message", "Unknown error")}
    except Exception as e:
        return {"status": "failed", "error": str(e)}