"""
Тести Патча 1 — словники.
Запуск: pytest tests/test_dictionaries.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from case_docket import dictionaries as dct


def test_all_dictionaries_load_without_error():
    dct.validate_all()


def test_expected_dictionary_names_present():
    expected = {
        "category", "doc_type_main", "doc_type_attachment", "doc_type_tech",
        "actor_role", "workflow_status", "link_type", "signature_status",
        "compliance_flag_type", "detection_source", "document_source",
        "origin_format", "compliance_severity", "version_mismatch_type",
        "graph_node_type", "graph_edge_type",  # ADR-001, Рек.5
    }
    assert set(dct.list_dictionaries()) == expected


def test_version_mismatch_type_extended_per_adr001_rec2():
    # ADR-001 Рек.2: розширений Diff-словник (paragraph/page/metadata/signature/ocr)
    extended = {
        "paragraph_added", "paragraph_removed", "page_added", "page_removed",
        "page_reordered", "metadata_difference", "signature_difference", "ocr_difference",
    }
    assert extended.issubset(set(dct.codes("version_mismatch_type")))


def test_graph_dictionaries_per_adr001_rec5():
    assert "court" in dct.codes("graph_node_type")
    assert "person" in dct.codes("graph_node_type")
    assert "sent" in dct.codes("graph_edge_type")
    assert "signed_by" in dct.codes("graph_edge_type")


def test_category_codes():
    assert dct.codes("category") == ["main", "atch", "tech"]


def test_label_lookup():
    assert dct.label("doc_type_main", "ruling") == "Ухвала"
    assert dct.label("category", "atch") == "Додаток"


def test_is_valid():
    assert dct.is_valid("category", "main") is True
    assert dct.is_valid("category", "bogus") is False


def test_unknown_dictionary_raises():
    try:
        dct.codes("no_such_dictionary")
        assert False, "мало кинути UnknownDictionaryError"
    except dct.UnknownDictionaryError:
        pass


def test_unknown_code_raises():
    try:
        dct.label("category", "bogus")
        assert False, "мало кинути UnknownCodeError"
    except dct.UnknownCodeError:
        pass


def test_compliance_severity_mapping_matches_agreed_spec():
    # falsification_risk — найвищий рівень: саме ці 4 коди
    falsification = {
        "undeclared_attachment",
        "late_addition",
        "retroactive_registration",
        "unlisted_in_registry_snapshot",
    }
    for code in falsification:
        assert dct.default_severity(code) == "falsification_risk", code

    assert dct.default_severity("type_mismatch") == "critical"

    warning = {"missing_attachment", "count_mismatch"}
    for code in warning:
        assert dct.default_severity(code) == "warning", code


def test_no_duplicate_codes_within_any_dictionary():
    for name in dct.list_dictionaries():
        codes_list = dct.codes(name)
        assert len(codes_list) == len(set(codes_list)), f"дублікати кодів у {name}"


def test_workflow_status_count():
    # 15 стадій руху документа, зафіксованих у специфікації
    assert len(dct.codes("workflow_status")) == 15


if __name__ == "__main__":
    import subprocess
    subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"])
