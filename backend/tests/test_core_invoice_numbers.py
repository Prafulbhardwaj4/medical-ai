"""Invoice / note numbering must never hand out the same number twice.

The sequential test runs everywhere. The concurrent test needs a real PostgreSQL (row locks do not exist
in SQLite); it runs when MEDSCRIBE_TEST_PG_URL is set (the CI workflow sets it) and is skipped otherwise.
"""
import os
import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.hospital import Hospital
from app.models.invoice_sequence import InvoiceSequence
from app.utils.receipts import next_note_number, next_receipt_number

PG_URL = os.environ.get("MEDSCRIBE_TEST_PG_URL", "")


def test_numbers_are_sequential_unique_and_per_hospital(db, make_hospital):
    h1, h2 = make_hospital("A"), make_hospital("B")
    first = [next_receipt_number(db, h1) for _ in range(5)]
    db.commit()
    assert len(set(first)) == 5
    assert [n.rsplit("-", 1)[1] for n in first] == ["00001", "00002", "00003", "00004", "00005"]
    other = next_receipt_number(db, h2)
    db.commit()
    assert other.rsplit("-", 1)[1] == "00001" and other.startswith(h2.hospital_code)
    cn, dn = next_note_number(db, h1, "credit"), next_note_number(db, h1, "debit")
    db.commit()
    assert "-CN-" in cn and "-DN-" in dn and cn.endswith("00001") and dn.endswith("00001")


@pytest.mark.skipif(not PG_URL, reason="needs PostgreSQL (set MEDSCRIBE_TEST_PG_URL)")
def test_concurrent_requests_never_get_the_same_number():
    # Everything happens inside its own throw-away schema, so no other table is ever touched.
    admin_engine = create_engine(PG_URL)
    with admin_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS conc_test CASCADE"))
        conn.execute(text("CREATE SCHEMA conc_test"))
    engine = create_engine(PG_URL, pool_size=20, max_overflow=20, connect_args={"options": "-csearch_path=conc_test"})
    tables = [Hospital.__table__, InvoiceSequence.__table__]
    Base.metadata.create_all(engine, tables=tables)
    Session = sessionmaker(bind=engine)
    setup = Session()
    hospital = Hospital(name="Concurrency Hospital", hospital_code="CONC")
    setup.add(hospital)
    setup.commit()
    hospital_id = hospital.id
    setup.close()

    workers, per_worker = 12, 8
    results, errors = [], []
    barrier = threading.Barrier(workers)

    def worker():
        s = Session()
        try:
            h = s.query(Hospital).filter(Hospital.id == hospital_id).first()
            barrier.wait(timeout=30)
            for _ in range(per_worker):
                results.append(next_receipt_number(s, h))
                s.commit()  # each number is committed on its own, like separate requests
        except Exception as exc:  # pragma: no cover - reported by the assertion below
            errors.append(repr(exc))
            s.rollback()
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    try:
        assert not errors, errors
        assert len(results) == workers * per_worker
        assert len(set(results)) == len(results), "duplicate invoice numbers were handed out"
        numbers = sorted(int(r.rsplit("-", 1)[1]) for r in results)
        assert numbers == list(range(1, workers * per_worker + 1)), "numbers must have no gaps"
    finally:
        engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS conc_test CASCADE"))
        admin_engine.dispose()