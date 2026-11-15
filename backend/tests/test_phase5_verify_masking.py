from types import SimpleNamespace

from app.utils.sensitive_tests import MASKED_TEST_NAME, is_sensitive_test, public_test_name


class FakeQuery:
    def __init__(self, item):
        self.item = item

    def filter(self, *a, **k):
        return self

    def first(self):
        return self.item


class FakeDB:
    def __init__(self, item=None):
        self.item = item

    def query(self, *a, **k):
        return FakeQuery(self.item)


def test_hiv_flag_is_masked():
    db = FakeDB(SimpleNamespace(is_hiv_test=True, category="Serology"))
    order = SimpleNamespace(test_id=5, test_name="Rapid Test 1")
    assert public_test_name(db, order) == MASKED_TEST_NAME


def test_hiv_name_is_masked_even_without_flag():
    db = FakeDB(SimpleNamespace(is_hiv_test=False, category="Serology"))
    order = SimpleNamespace(test_id=5, test_name="HIV 1 & 2 Antibody")
    assert public_test_name(db, order) == MASKED_TEST_NAME
    assert public_test_name(FakeDB(None), SimpleNamespace(test_id=None, test_name="HIV Duo")) == MASKED_TEST_NAME


def test_sensitive_category_is_masked():
    db = FakeDB(SimpleNamespace(is_hiv_test=False, category="Sexual Health"))
    assert public_test_name(db, SimpleNamespace(test_id=1, test_name="Panel A")) == MASKED_TEST_NAME


def test_ordinary_test_keeps_its_name():
    db = FakeDB(SimpleNamespace(is_hiv_test=False, category="Haematology"))
    order = SimpleNamespace(test_id=1, test_name="Complete Blood Count")
    assert public_test_name(db, order) == "Complete Blood Count"


def test_no_false_positive_on_words_containing_hiv():
    assert not is_sensitive_test(None, "Archive review")
    assert not is_sensitive_test(None, "Chivalry panel")


def test_prescription_verify_whitelists_medicine_fields():
    import json
    from app.routers import consultations
    src = open(consultations.__file__, encoding="utf-8").read()
    assert '("name", "brand_name", "dosage", "frequency", "duration", "schedule")' in src