"""Which lab tests are sensitive, and the neutral name shown instead of them on public pages.

The public /lab/verify pages are open to anyone who holds the report link (it is printed on the report and
sits inside its QR code), so a sensitive test must never be named there.
"""
import re

MASKED_TEST_NAME = "Laboratory test (details withheld)"

# Catalogue categories that are treated as sensitive (compared in lower case).
SENSITIVE_TEST_CATEGORIES = {"hiv", "sexual health", "sti", "std"}

_SENSITIVE_NAME_RE = re.compile(r"\bhiv\b|human immunodeficiency", re.IGNORECASE)


def is_sensitive_test(catalog_item, test_name) -> bool:
    """True for an HIV test (flagged in the catalogue, or recognisable by its name) and for any catalogue
    category listed in SENSITIVE_TEST_CATEGORIES."""
    if catalog_item is not None:
        if getattr(catalog_item, "is_hiv_test", False):
            return True
        category = (getattr(catalog_item, "category", None) or "").strip().lower()
        if category in SENSITIVE_TEST_CATEGORIES:
            return True
    return bool(_SENSITIVE_NAME_RE.search(test_name or ""))


def public_test_name(db, order) -> str:
    """The test name that may be shown on a public page: the real name, or MASKED_TEST_NAME when sensitive."""
    item = None
    if getattr(order, "test_id", None):
        from app.models.test_catalog import TestCatalogItem
        item = db.query(TestCatalogItem).filter(TestCatalogItem.id == order.test_id).first()
    return MASKED_TEST_NAME if is_sensitive_test(item, order.test_name) else order.test_name