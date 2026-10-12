"""Shared helpers for the platform-wide master lists (tests and medicines).
No database access in this file."""


def norm_name(value) -> str:
    """Trim, collapse repeated spaces, lowercase. Used for matching and uniqueness."""
    return " ".join(str(value or "").split()).lower()


def clean_text(value) -> str:
    """Trim and collapse repeated spaces, keeping the original case."""
    return " ".join(str(value or "").split())


def medicine_display_name(generic, strength, form) -> str:
    """Canonical display name: 'generic strength form', e.g. 'Paracetamol 500mg Tablet'."""
    parts = [clean_text(generic), clean_text(strength), clean_text(form)]
    return " ".join(p for p in parts if p)