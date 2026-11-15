"""Hides the patient's saved name and phone number in a transcript before it is sent to the AI service."""
import re

NAME_MASK = "[patient]"
PHONE_MASK = "[phone]"


def _name_pieces(name: str):
    full = " ".join((name or "").split())
    pieces = {p for p in re.split(r"[^A-Za-z\u0900-\u097F]+", full) if len(p) >= 3}
    ordered = sorted(pieces, key=len, reverse=True)
    return ([full] if len(full) >= 3 else []) + ordered


def mask_identifiers(text: str, name: str, phone: str) -> str:
    if not text:
        return text
    out = text
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) >= 10:
        last10 = digits[-10:]
        spaced = r"[\s\-.]*".join(last10)
        out = re.sub(r"(?<!\d)(?:\+?91[\s\-.]*)?" + spaced + r"(?!\d)", PHONE_MASK, out)
    for piece in _name_pieces(name):
        out = re.sub(r"(?<!\w)" + re.escape(piece) + r"(?!\w)", NAME_MASK, out, flags=re.IGNORECASE)
    return out