"""Common-password and personal-detail checks used by check_password_strength.

The word list is a plain text file (app/data/common_passwords.txt, one lowercase word per line,
lines starting with # ignored). A password is rejected when it, or its base word after removing
trailing digits/symbols and swapping look-alike characters (@ for a, 0 for o ...), is in the list.
If the file is missing the common-password check is skipped (the other rules still apply)."""
import logging
import os
import re
from functools import lru_cache

_LEET_I = str.maketrans({"@": "a", "0": "o", "3": "e", "4": "a", "5": "s", "7": "t", "$": "s", "!": "i", "1": "i"})
_LEET_L = str.maketrans({"@": "a", "0": "o", "3": "e", "4": "a", "5": "s", "7": "t", "$": "s", "!": "i", "1": "l"})
_TRAILING = re.compile(r"[^a-z]+$")


@lru_cache(maxsize=1)
def _words() -> frozenset:
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "common_passwords.txt")
    try:
        with open(path, encoding="utf-8") as f:
            return frozenset(line.strip().lower() for line in f if line.strip() and not line.startswith("#"))
    except OSError:
        logging.getLogger("medscribe").warning("common_passwords.txt not found: common-password check skipped")
        return frozenset()


def is_common_password(password: str) -> bool:
    words = _words()
    if not words:
        return False
    low = (password or "").lower()
    bases = {low, _TRAILING.sub("", low)}
    forms = set()
    for base in bases:
        forms.update({base, base.translate(_LEET_I), base.translate(_LEET_L)})
        forms.add(_TRAILING.sub("", base.translate(_LEET_I)))
    return any(f and f in words for f in forms)


def contains_personal_info(password: str, email=None, name=None, extras=()) -> bool:
    """True if the password contains the user's email, name parts (3+ letters) or phone number."""
    low = (password or "").lower()
    tokens = set()
    if email:
        e = str(email).lower().strip()
        tokens.add(e)
        local = e.split("@")[0]
        if len(local) >= 4:
            tokens.add(local)
        for part in re.split(r"[^a-z0-9]+", local):
            if len(part) >= 4:
                tokens.add(part)
    for part in re.split(r"[^A-Za-z]+", str(name or "")):
        if len(part) >= 3 and part.lower() not in ("mrs", "miss"):
            tokens.add(part.lower())
    if any(t and t in low for t in tokens):
        return True
    digits = re.sub(r"\D", "", low)
    for x in extras or ():
        phone = re.sub(r"\D", "", str(x or ""))[-10:]
        if len(phone) >= 8 and phone in digits:
            return True
    return False