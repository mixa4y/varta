from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "docs" / "architecture"

ADR_FILES = [
    "ADR-001-system-architecture.md",
    "ADR-002-source-of-truth.md",
    "ADR-003-migrations-backup-and-restore.md",
    "ADR-004-identity-and-cardinality.md",
    "ADR-005-workspace-and-managed-storage.md",
    "ADR-006-local-http-security.md",
    "ADR-007-sqlite-uow-and-workers.md",
]

REQUIRED_ADR_SECTIONS = (
    "## Контекст",
    "## Рішення",
    "## Відхилені альтернативи",
    "## Наслідки",
    "## Вплив на міграцію",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_c02_adrs_are_approved_and_complete() -> None:
    for filename in ADR_FILES:
        text = read(ARCH / filename)
        assert "| Status | `APPROVED` |" in text, filename
        for section in REQUIRED_ADR_SECTIONS:
            assert section in text, f"{filename}: missing {section}"


def test_c02_decision_log_registers_every_approved_adr() -> None:
    decision_log = read(ARCH / "architecture-decision-log.md")
    manifest = read(ARCH / "MANIFEST.md")

    for filename in ADR_FILES:
        adr_id = filename.split("-", maxsplit=2)[:2]
        label = "-".join(adr_id)
        assert f"[`{label}`]({filename})" in decision_log
        assert f"`{filename}`" in manifest


def test_c02_open_decisions_have_owner_and_closing_gate() -> None:
    text = read(ARCH / "open-questions.md")
    for number in range(1, 5):
        question_id = f"OQ-C02-{number:03d}"
        row = next(line for line in text.splitlines() if f"`{question_id}`" in line)
        assert re.search(r"`C\d{2}`", row), row
        assert "PASS`" in row, row

    for path in ARCH.glob("*.md"):
        document = read(path)
        for heading in ("## Open questions", "## Open decisions", "## Відкриті питання"):
            if heading not in document:
                continue
            section = document.split(heading, maxsplit=1)[1].split("\n## ", maxsplit=1)[0]
            assert "Owner stage" in section or "owner" in section.lower(), path.name


def test_c02_spec_has_no_hidden_foundation_choice() -> None:
    spec = read(ARCH / "technical-specification.md")
    normalized_spec = " ".join(spec.split())
    required = (
        "embedded browser UI",
        "SQLite як єдине writable structured source of truth",
        "managed filesystem",
        "application service",
        "short-lived connection/UoW per application operation",
        "Worker не має SQLite connection/repository",
        "Notion",
        "<workspace>/.varta/",
    )
    for marker in required:
        assert marker in normalized_spec

    rejected_legacy_questions = (
        "Вибір UI і механізму пакування",
        "UI потрібен у першому релізі: desktop",
        "UUID чи інший формат локальних ідентифікаторів?",
    )
    canonical = "\n".join(
        read(path)
        for path in (
            ARCH / "technical-specification.md",
            ARCH / "README.md",
            ROOT / "PROJECT_STATUS.md",
            ROOT / "docs" / "action-algorithm.md",
        )
    )
    for stale_text in rejected_legacy_questions:
        assert stale_text not in canonical


def test_browser_assets_do_not_import_repository_or_sqlite() -> None:
    forbidden = (
        "case_docket.repository",
        "SQLiteRepository",
        "import sqlite3",
        "from sqlite3",
    )
    static_root = ROOT / "caseflow" / "static"
    for path in static_root.rglob("*"):
        if path.suffix.lower() not in {".js", ".html"}:
            continue
        text = read(path)
        for marker in forbidden:
            assert marker not in text, f"{path.relative_to(ROOT)} imports {marker}"


def test_c02_local_markdown_links_resolve() -> None:
    documents = [ARCH / filename for filename in ADR_FILES]
    documents.extend(
        [
            ARCH / "architecture-decision-log.md",
            ARCH / "technical-specification.md",
            ARCH / "README.md",
            ARCH / "open-questions.md",
        ]
    )

    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for document in documents:
        for target in link_pattern.findall(read(document)):
            if target.startswith(("http://", "https://", "#")):
                continue
            relative_target = target.split("#", maxsplit=1)[0]
            assert (document.parent / relative_target).exists(), (
                f"{document.relative_to(ROOT)} -> {target}"
            )


def test_c02_markdown_static_lint() -> None:
    documents = [ARCH / filename for filename in ADR_FILES]
    documents.extend(
        [
            ARCH / "architecture-decision-log.md",
            ARCH / "technical-specification.md",
            ARCH / "README.md",
            ARCH / "MANIFEST.md",
            ARCH / "open-questions.md",
            ROOT / "PROJECT_STATUS.md",
            ROOT / "docs" / "chat-roadmap.md",
        ]
    )

    for document in documents:
        text = read(document)
        lines = text.splitlines()
        assert lines and lines[0].startswith("# "), document.name
        assert sum(line.startswith("# ") for line in lines) == 1, document.name
        assert "\t" not in text, document.name
        assert all(line == line.rstrip() for line in lines), document.name
        assert "\n\n\n" not in text, document.name
        assert sum(line.startswith("```") for line in lines) % 2 == 0, document.name


def test_c02_roadmap_planning_statuses_are_synchronized() -> None:
    catalog = json.loads(read(ROOT / "tools" / "roadmap_controller" / "stages.json"))
    statuses = {stage["id"]: stage["planningStatus"] for stage in catalog["stages"]}
    assert statuses["C01"] == "DONE"
    assert statuses["C02"] == "DONE"
    assert statuses["C03"] == "READY"

    roadmap = read(ROOT / "docs" / "chat-roadmap.md")
    assert "| `C02` | Затвердити цільову local-web архітектуру та ADR-пакет" in roadmap
    assert "**Статус:** `DONE` — architecture/spec/status package" in roadmap
    assert "**Статус:** `READY` після C02 architecture gate" in roadmap

    companion = read(ROOT / "docs" / "interactive" / "varta-chat-roadmap.html")
    expected_companion_status = {
        "C01": "done",
        "C02": "done",
        "C03": "ready",
    }
    for stage_id, status in expected_companion_status.items():
        assert (
            f'<article class="step" data-stage-id="{stage_id}" '
            f'data-status="{status}">' in companion
        )
