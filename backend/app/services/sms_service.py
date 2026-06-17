import httpx
from app.config import settings

FAST2SMS_URL = "https://www.fast2sms.com/dev/bulkV2"

def send_sms(to_phone: str, doctor_name: str, token_number: str, pdf_url: str) -> dict:
    """Send prescription link via Fast2SMS."""

    # Fast2SMS needs 10-digit number without country code
    phone = to_phone.replace("+91", "").replace("+", "").strip()

    message = (
        f"Prescription from {doctor_name}. "
        f"Token: {token_number}. "
        f"Download: {pdf_url}"
    )

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