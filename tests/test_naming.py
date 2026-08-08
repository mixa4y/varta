from datetime import date

import pytest

from case_docket.naming import (
    ExportFilenameParts,
    ManagedFilenameParts,
    build_export_filename,
    build_managed_filename,
    resolve_collision,
    sanitize_component,
    transliterate_kmu55,
)


def test_transliteration_context_and_zgh_rule():
    assert transliterate_kmu55("Юрій Єнакієве Згурський") == "Yurii Yenakiieve Zghurskyi"


def test_sanitize_component_is_windows_safe():
    assert sanitize_component('  Позов: заява / № 5?.pdf  ') == "pozov_zaiava_no_5_pdf"


@pytest.mark.parametrize("reserved", ["CON", "nul", "Lpt1"])
def test_sanitize_component_escapes_windows_reserved_names(reserved):
    assert sanitize_component(reserved).startswith("_")


def test_build_export_filename_does_not_repeat_folder_context():
    parts = ExportFilenameParts(
        document_date=date(2026, 8, 7),
        proceeding="111/2222/33",
        category="main",
        doc_type="claim",
        name="Позовна заява",
        sequence=2,
        extension=".PDF",
    )
    assert build_export_filename(parts) == "20260807_pozovna_zaiava.pdf"


def test_build_managed_filename_for_main_document():
    parts = ManagedFilenameParts(
        document_date=date(2024, 3, 14),
        name="Позовна заява",
        extension="pdf",
    )
    assert build_managed_filename(parts) == "20240314_pozovna_zaiava.pdf"


def test_build_managed_filename_for_attachment():
    parts = ManagedFilenameParts(
        document_date=date(2024, 3, 14),
        name="Позовна заява",
        role="додаток",
        sequence=2,
        extension="pdf",
    )
    assert build_managed_filename(parts) == "20240314_pozovna_zaiava_dodatok_002.pdf"


def test_managed_sequence_requires_role():
    with pytest.raises(ValueError, match="ролі"):
        ManagedFilenameParts(date(2024, 3, 14), "Позов", "pdf", sequence=1)


def test_build_export_filename_rejects_unknown_template_field():
    parts = ExportFilenameParts(
        date(2026, 8, 7), "p1", "main", "claim", "Позов", 1, "pdf"
    )
    with pytest.raises(ValueError, match="Непідтримувані"):
        build_export_filename(parts, template="{date}_{unknown}")


def test_build_export_filename_is_bounded_and_deterministic():
    parts = ExportFilenameParts(
        date(2026, 8, 7), "p1", "main", "claim", "Дуже довга назва " * 60, 1, "pdf"
    )
    first = build_export_filename(parts, max_length=120)
    second = build_export_filename(parts, max_length=120)
    assert first == second
    assert len(first) <= 120
    assert first.endswith(".pdf")


def test_resolve_collision_is_case_insensitive_and_stable():
    original = "20260807_p1_main_claim_pozov_001.pdf"
    existing = {original.upper()}
    first = resolve_collision(original, existing, stable_id="file-123")
    second = resolve_collision(original, existing, stable_id="file-123")
    assert first == second
    assert first != original
    assert first.endswith(".pdf")


def test_resolve_collision_returns_original_when_free():
    filename = "20260807_p1_main_claim_pozov_001.pdf"
    assert resolve_collision(filename, set(), stable_id="file-123") == filename
