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
    forbidden = ("case_docket.repository", "caseflow", "sqlite3")
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
    assert not any(name.startswith("case_docket.repository") for name in _imports(ROOT / "caseflow" / "api_v1.py"))


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
