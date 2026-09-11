from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_domain_and_application_do_not_import_outward_adapters() -> None:
    forbidden = ("case_docket.repository", "case_docket.storage", "caseflow", "sqlite3")
    paths = [*((ROOT / "case_docket" / "application").glob("*.py"))]
    paths.extend((ROOT / "case_docket" / "models").glob("*.py"))

    for path in paths:
        for imported in _imports(path):
            assert not imported.startswith(forbidden), f"{path.relative_to(ROOT)} -> {imported}"


def test_http_contact_adapter_has_no_direct_repository_calls() -> None:
    path = ROOT / "caseflow" / "server.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    handler = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler"
    )
    names = {
        "handle_contacts",
        "handle_contact",
        "handle_contacts_context",
        "handle_contact_create",
        "handle_contact_update",
        "handle_contact_role",
    }
    methods = [
        node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name in names
    ]

    assert {method.name for method in methods} == names
    for method in methods:
        source = ast.get_source_segment(path.read_text(encoding="utf-8"), method) or ""
        assert ".repository" not in source, method.name
        assert "contact_service" in source, method.name


def test_contacts_ui_uses_versioned_routes_and_legacy_routes_are_server_only() -> None:
    javascript = (ROOT / "caseflow" / "static" / "app.js").read_text(encoding="utf-8")
    assert javascript.count("/api/v1/contacts") == 5
    assert 'api("/api/contacts' not in javascript

    transport = (ROOT / "caseflow" / "api_v1.py").read_text(encoding="utf-8")
    assert 'CONTACTS_COMPATIBILITY_PREFIX = "/api/contacts"' in transport
    assert not any(
        name.startswith("case_docket.repository")
        for name in _imports(ROOT / "caseflow" / "api_v1.py")
    )


def test_c03_contract_document_is_registered() -> None:
    contract = ROOT / "docs" / "architecture" / "local-api-v1.md"
    text = contract.read_text(encoding="utf-8")
    assert "| Status | `ACTIVE` |" in text
    assert "`/api/v1/contacts`" in text
    assert "request_validation_error" in text
    assert "compatibility adapter" in text

    manifest = (ROOT / "docs" / "architecture" / "MANIFEST.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")
    assert "`local-api-v1.md`" in manifest
    assert "architecture/local-api-v1.md" in index


def test_runtime_state_does_not_keep_a_shared_sqlite_connection() -> None:
    path = ROOT / "caseflow" / "server.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    state = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "CaseFlowState"
    )
    state_source = ast.get_source_segment(source, state) or ""

    assert "self._repository" not in state_source
    assert "check_same_thread=False" not in (
        ROOT / "case_docket" / "repository" / "sqlite_repository.py"
    ).read_text(encoding="utf-8")
    assert "self._database_factory.prepare()" in state_source
    assert "initialize=False" in state_source


def test_workers_have_no_direct_sqlite_or_repository_access() -> None:
    worker_paths = (
        ROOT / "caseflow" / "caseflow_process.py",
        ROOT / "caseflow" / "anomaly_detector.py",
    )
    forbidden_imports = ("sqlite3", "case_docket.repository")
    forbidden_source = ("SQLiteRepository", "varta.sqlite3", "schema_migrations")

    for path in worker_paths:
        imports = _imports(path)
        source = path.read_text(encoding="utf-8")
        assert not any(imported.startswith(forbidden_imports) for imported in imports), (
            path.relative_to(ROOT)
        )
        assert not any(marker in source for marker in forbidden_source), path.relative_to(ROOT)


def test_c04_sqlite_contract_is_registered_and_keeps_recovery_boundary() -> None:
    contract = ROOT / "docs" / "architecture" / "sqlite-lifecycle.md"
    text = contract.read_text(encoding="utf-8")
    manifest = (ROOT / "docs" / "architecture" / "MANIFEST.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")

    assert "| Status | `ACTIVE` |" in text
    assert "floor `2`, ceiling `6`" in text
    assert "DB-only" in text
    assert "filesystem originals" in text
    assert "`sqlite-lifecycle.md` | `ACTIVE`" in manifest
    assert "architecture/sqlite-lifecycle.md" in index


def test_c05_managed_storage_contract_is_registered_and_keeps_intake_boundary() -> None:
    contract = ROOT / "docs" / "architecture" / "managed-storage.md"
    text = contract.read_text(encoding="utf-8")
    manifest = (ROOT / "docs" / "architecture" / "MANIFEST.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")

    assert "| Status | `ACTIVE` |" in text
    assert "Layout version | `1`" in text
    assert "literal source provenance" in text
    assert "duplicate_of_file_ids" in text
    assert "C06 підключає service до versioned multipart API" in text
    assert "legacy `/api/upload` лишається compatibility path" in text
    assert "`managed-storage.md` | `ACTIVE`" in manifest
    assert "architecture/managed-storage.md" in index


def test_c06_intake_contract_is_registered_and_http_adapter_stays_thin() -> None:
    contract = ROOT / "docs" / "architecture" / "intake-v1.md"
    text = contract.read_text(encoding="utf-8")
    manifest = (ROOT / "docs" / "architecture" / "MANIFEST.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")

    assert "| Status | `ACTIVE` |" in text
    assert "`0008_intake_batches`" in text
    assert "top-level ZIP" in text
    assert "encrypted_archive_member" in text
    assert 'authority: "sqlite"' in text
    assert "`intake-v1.md` | `ACTIVE`" in manifest
    assert "architecture/intake-v1.md" in index

    path = ROOT / "caseflow" / "server.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    handler = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler"
    )
    names = {"handle_intake_upload", "handle_intake_inventory", "handle_intake_batch"}
    methods = [
        node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {method.name for method in methods} == names
    for method in methods:
        method_source = ast.get_source_segment(source, method) or ""
        assert "intake_service" in method_source
        assert ".repository" not in method_source
        assert "SQLite" not in method_source
        assert ".xlsx" not in method_source.casefold()

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'varta-intake = "case_docket.intake_cli:main"' in pyproject


def test_c07_workspace_contract_is_registered_and_http_adapter_stays_thin() -> None:
    contract = ROOT / "docs" / "architecture" / "workspace-v1.md"
    text = contract.read_text(encoding="utf-8")
    manifest = (ROOT / "docs" / "architecture" / "MANIFEST.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")

    assert "| Status | `ACTIVE` |" in text
    assert "`0009_case_workspace_bootstrap`" in text
    assert "filename/folder-only" in text
    assert "presentation_preference" in text
    assert "zero/one/multiple" in text
    assert "`workspace-v1.md` | `ACTIVE`" in manifest
    assert "architecture/workspace-v1.md" in index

    path = ROOT / "caseflow" / "server.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    handler = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler"
    )
    names = {
        "handle_workspace_cases",
        "handle_active_case",
        "handle_bootstrap_reviews",
        "handle_workspace_case_create",
        "handle_workspace_proceeding_create",
        "handle_active_case_select",
        "handle_bootstrap_candidates",
        "handle_bootstrap_confirm",
        "handle_workspace_memberships",
        "handle_document_memberships",
    }
    methods = [
        node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {method.name for method in methods} == names
    for method in methods:
        method_source = ast.get_source_segment(source, method) or ""
        assert "workspace_service" in method_source
        assert ".repository" not in method_source
        assert "SQLite" not in method_source


def test_c08_evidence_contract_is_registered_and_http_adapter_stays_thin() -> None:
    contract = ROOT / "docs" / "architecture" / "evidence-domain-v1.md"
    text = contract.read_text(encoding="utf-8")
    manifest = (ROOT / "docs" / "architecture" / "MANIFEST.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")

    assert "| Status | `ACTIVE` |" in text
    assert "`0010_evidence_services`" in text
    assert "automaticVersion" in text
    assert "expectedVersion" in text
    assert 'authority: "sqlite"' in text
    assert "No later than C13 PASS" in text
    assert "`evidence-domain-v1.md` | `ACTIVE`" in manifest
    assert "architecture/evidence-domain-v1.md" in index

    path = ROOT / "caseflow" / "server.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    handler = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler"
    )
    names = {
        "handle_evidence_actor_create",
        "handle_evidence_document_create",
        "handle_evidence_event_create",
        "handle_source_reference_create",
        "handle_claim_create",
        "handle_evidence_relation_create",
        "handle_finding_record",
        "handle_evidence_review",
        "handle_finding_review",
        "handle_evidence_case",
        "handle_evidence_timeline",
        "handle_source_context",
        "handle_evidence_review_history",
    }
    methods = [
        node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {method.name for method in methods} == names
    for method in methods:
        method_source = ast.get_source_segment(source, method) or ""
        assert "evidence_service" in method_source
        assert ".repository" not in method_source
        assert "SQLite" not in method_source
