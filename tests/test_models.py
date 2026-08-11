"""
Тести моделей (ADR-001, Рек.1/3/4/6).
Запуск: python3 tests/test_models.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from case_docket.models import Actor, Contact, Document, DocumentDates, DocumentFile, Event


def test_document_accepts_valid_codes():
    d = Document(
        id="doc1", case_id="c1", proceeding_id="p1",
        category="main", doc_type="claim", title="Позовна заява",
        source="user_original",
    )
    assert d.category == "main"


def test_document_rejects_doc_type_from_wrong_category():
    # "claim" належить doc_type_main, не doc_type_attachment
    try:
        Document(
            id="doc1", case_id="c1", proceeding_id="p1",
            category="atch", doc_type="claim", title="x", source="user_original",
        )
        assert False, "мало кинути ValueError"
    except ValueError:
        pass


def test_document_file_content_requires_hash():
    try:
        DocumentFile(id="f1", document_id="doc1", kind="content", path="/x.pdf")
        assert False, "мало кинути ValueError (content без hash)"
    except ValueError:
        pass

    # OK з hash:
    f = DocumentFile(id="f1", document_id="doc1", kind="content", path="/x.pdf", file_hash="abc123")
    assert f.file_hash == "abc123"


def test_document_file_confidence_bounds():
    try:
        DocumentFile(id="f1", document_id="doc1", kind="ocr_text", path="/x.txt", confidence=1.5)
        assert False, "мало кинути ValueError (confidence поза [0,1])"
    except ValueError:
        pass

    ok = DocumentFile(id="f1", document_id="doc1", kind="ocr_text", path="/x.txt", confidence=0.92)
    assert ok.confidence == 0.92

    # None — допустимо (немає вимірюваного алгоритму, Рек.3: не вигадувати число)
    ok2 = DocumentFile(id="f2", document_id="doc1", kind="ocr_text", path="/y.txt")
    assert ok2.confidence is None


def test_actor_rejects_invalid_role():
    try:
        Actor(id="a1", name="Іванов", role="bogus_role")
        assert False, "мало кинути ValueError"
    except ValueError:
        pass


def test_contact_roundtrip_and_validation():
    contact = Contact(
        id="contact-1",
        full_name="  Тестова Особа  ",
        participant_type="person",
        email="test@example.invalid",
    )
    assert contact.full_name == "Тестова Особа"
    assert contact.to_record()["email"] == "test@example.invalid"

    try:
        Contact(id="contact-2", full_name="", participant_type="person")
        assert False, "порожній full_name мав бути відхилений"
    except ValueError:
        pass


def test_event_produces_documents_rec4():
    ev = Event(
        id="ev1", case_id="c1", proceeding_id="p1",
        workflow_status="registered",
        produced_document_ids=["doc1", "doc2"],
    )
    assert ev.produced_document_ids == ["doc1", "doc2"]


def test_dates_sequence_violation_detected():
    dd = DocumentDates(
        date_sent=date(2026, 2, 1),
        date_delivered=date(2026, 1, 20),  # раніше за sent -> порушення
    )
    assert dd.sequence_violation() is not None


def test_dates_no_violation_when_consistent():
    dd = DocumentDates(
        date_sent=date(2026, 1, 1),
        date_delivered=date(2026, 1, 5),
        date_registered=date(2026, 1, 10),
    )
    assert dd.sequence_violation() is None
    assert dd.filename_date() == date(2026, 1, 10)


def test_dates_filename_date_fallback():
    dd = DocumentDates(date_sent=date(2026, 1, 1))  # без date_registered
    assert dd.filename_date() == date(2026, 1, 1)


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed, failed = 0, 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL  {fn.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"---\n{passed} passed, {failed} failed")
