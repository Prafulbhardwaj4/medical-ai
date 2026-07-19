import re


def normalize_phone(phone: str) -> str:
    """Returns the last 10 digits of a phone number, stripping any country
    code, spaces, dashes, or plus signs. Hospital check-in doesn't normalize
    phone entry, so portal matching has to account for that instead."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else digits