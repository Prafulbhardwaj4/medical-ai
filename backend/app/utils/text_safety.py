"""Server-side checks for free-text input (names, addresses, notes, reasons, messages).

Rule: text a person types must not contain < or > and must not contain control characters. The front
end also escapes everything it shows; this is the second line of defence. Nothing stored is changed;
only NEW input is refused, with a plain-words message.

Use SafeTextModel as the base class of a request (input) model: every field whose name looks like a name,
address, note, reason, message, description, remark or comment is checked automatically. Do not use it
for response models.
"""
import re
from typing import Any

from pydantic import BaseModel, model_validator

_ANGLE = ("<", ">")

# Control characters, DEL, C1 controls, line/paragraph separators and bidirectional override characters.
_CONTROL_SINGLE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
# Same, but a note or address may contain tab, line feed and carriage return.
_CONTROL_MULTI = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")

_SINGLE_EXACT = {
    "name", "title", "city", "state", "location", "owner", "allergen", "reaction", "specialization",
    "room_number", "clinic_name", "label", "ward", "bed_number",
}
_SINGLE_SUFFIX = ("_name",)
_MULTI_EXACT = {
    "address", "note", "notes", "reason", "message", "description", "remarks", "remark", "comment", "comments",
}
_MULTI_SUFFIX = ("_address", "_note", "_notes", "_reason", "_message", "_comment", "_comments", "_remarks", "_description")


def _label(key: str) -> str:
    text = str(key).replace("_", " ").strip()
    return (text[:1].upper() + text[1:]) if text else "This field"


def ensure_safe_text(value, label: str = "This field", multiline: bool = False):
    """Returns the value unchanged when it is fine; raises ValueError (plain words) when it is not."""
    if value is None or not isinstance(value, str):
        return value
    if any(ch in value for ch in _ANGLE):
        raise ValueError(f"{label} can't contain the < or > characters.")
    pattern = _CONTROL_MULTI if multiline else _CONTROL_SINGLE
    if pattern.search(value):
        raise ValueError(f"{label} contains characters that can't be used. Please type it again.")
    return value


def ensure_safe_text_or_400(value, label: str = "This field", multiline: bool = False):
    """Same check for values that do not come through a request model (query or form parameters)."""
    from fastapi import HTTPException
    try:
        return ensure_safe_text(value, label, multiline)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _kind(key: str):
    k = str(key).lower()
    if k in _MULTI_EXACT or k.endswith(_MULTI_SUFFIX):
        return "multi"
    if k in _SINGLE_EXACT or k.endswith(_SINGLE_SUFFIX):
        return "single"
    return None


def _scan(data: Any) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                kind = _kind(key)
                if kind:
                    ensure_safe_text(value, _label(key), multiline=(kind == "multi"))
            elif isinstance(value, (dict, list)):
                _scan(value)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                _scan(item)


class SafeTextModel(BaseModel):
    """Base class for request models: refuses < > and control characters in text-like fields."""

    @model_validator(mode="before")
    @classmethod
    def _refuse_unsafe_text(cls, data):
        _scan(data)  # only plain dicts (real request bodies) are checked; ORM objects pass through untouched
        return data