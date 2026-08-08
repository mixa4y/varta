"""
Тести Repository Layer (ADR-001, Рек.8).
Запуск: python3 tests/test_repository.py (без pytest — див. README)
"""

import sys
import sqlite3
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from case_docket.repository import SQLiteRepository


def _fresh_repo() -> SQLiteRepository:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    return SQLiteRepository(tmp.name)


def test_insert_and_get_roundtrip():
    repo = _fresh_repo()
    doc_id = repo.insert("documents", {"title": "Позовна заява", "category": "main"})
    fetched = repo.get("documents", doc_id)
    assert fetched["title"] == "Позовна заява"
    assert fetched["category"] == "main"
    repo.close()


def test_update_preserves_other_fields():
    repo = _fresh_repo()
    doc_id = repo.insert("documents", {"title": "Ухвала", "category": "main"})
    repo.update("documents", doc_id, {"category": "atch"})
    fetched = repo.get("documents", doc_id)
    assert fetched["title"] == "Ухвала"       # не зникло
    assert fetched["category"] == "atch"        # оновилось
    repo.close()


def test_update_missing_record_raises():
    repo = _fresh_repo()
    try:
        repo.update("documents", "no-such-id", {"title": "x"})
        assert False, "мало кинути KeyError"
    except KeyError:
        pass
    repo.close()


def test_unknown_table_rejected():
    repo = _fresh_repo()
    try:
        repo.insert("not_a_real_table", {"x": 1})
        assert False, "мало кинути ValueError"
    except ValueError:
        pass
    repo.close()


def test_document_files_requires_document_id():
    repo = _fresh_repo()
    try:
        repo.insert("document_files", {"kind": "content"})
        assert False, "мало кинути ValueError (document_id обов'язковий, Рек.1)"
    except ValueError:
        pass
    repo.close()


def test_audit_log_records_every_insert_and_update():
    repo = _fresh_repo()
    doc_id = repo.insert("documents", {"title": "Клопотання"})
    repo.update("documents", doc_id, {"title": "Клопотання (уточнене)"})

    log = list(repo.get_audit_log(entity_table="documents", entity_id=doc_id))
    actions = [entry["action"] for entry in log]
    assert actions == ["insert", "update"]
    repo.close()


def test_audit_log_is_append_only_no_public_delete_method():
    # Repository не має жодного методу delete/remove — Audit Log не можна
    # видалити чи відредагувати через публічний інтерфейс (п.11 CSMD).
    repo = _fresh_repo()
    public_methods = [m for m in dir(repo) if not m.startswith("_")]
    assert not any("delete" in m or "remove" in m for m in public_methods)
    repo.close()


def test_audit_log_is_append_only_in_database():
    repo = _fresh_repo()
    doc_id = repo.insert("documents", {"title": "Ухвала"})

    try:
        repo._conn.execute("DELETE FROM audit_log WHERE entity_id = ?", (doc_id,))
        assert False, "SQLite мав заборонити видалення audit_log"
    except sqlite3.IntegrityError:
        pass

    assert len(list(repo.get_audit_log(entity_id=doc_id))) == 1
    repo.close()


def test_insert_rolls_back_when_audit_fails():
    repo = _fresh_repo()
    repo._conn.executescript(
        """
        CREATE TRIGGER fail_audit_insert
        BEFORE INSERT ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'forced audit failure');
        END;
        """
    )

    try:
        repo.insert("documents", {"id": "doc1", "title": "Ухвала"})
        assert False, "Вставка мала завершитися помилкою audit log"
    except sqlite3.IntegrityError:
        pass

    assert repo.get("documents", "doc1") is None
    repo.close()


def test_document_file_update_keeps_foreign_key_in_sync():
    repo = _fresh_repo()
    first_doc_id = repo.insert("documents", {"title": "Перший документ"})
    second_doc_id = repo.insert("documents", {"title": "Другий документ"})
    file_id = repo.insert(
        "document_files",
        {"document_id": first_doc_id, "kind": "content"},
    )

    repo.update("document_files", file_id, {"document_id": second_doc_id})

    stored_document_id = repo._conn.execute(
        "SELECT document_id FROM document_files WHERE id = ?", (file_id,)
    ).fetchone()["document_id"]
    assert stored_document_id == second_doc_id
    assert repo.get("document_files", file_id)["document_id"] == second_doc_id
    repo.close()


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
