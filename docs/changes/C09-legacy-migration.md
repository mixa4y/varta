# C09 — read-only XLSX/.caseflow migration adapter

## Boundary

C09 inventories legacy CaseFlow XLSX registers and `.caseflow` JSON state without
writing to their source paths. Import state is persisted in auxiliary SQLite tables;
authoritative domain reads are not switched by this adapter. Promotion remains a
separate reconciliation/configuration gate.

Only synthetic fixtures are committed. Runtime secrets, tokens, OAuth state,
databases, document files, generated maps and case material are excluded.

## Versioned source inventory

- `caseflow-register-v1`: sheets `Партії`, `Документи`, `Хронологія`, `Файли`,
  `Провадження` and `Довідники`, with the headers declared by
  `LEGACY_XLSX_HEADERS`;
- `caseflow-runtime-json-v1`: a `.caseflow` JSON file or a `.caseflow` directory
  containing JSON objects/arrays. Sensitive runtime files are inventoried by hash
  but their content is not imported.

Each source file receives SHA-256 and size evidence. The directory tree receives a
deterministic aggregate hash. The default source key is an opaque hash of source
kind and local name hints; callers may supply a stable opaque `source_key`.

## Field mapping contract

`field_mapping_catalog()` returns one entry for every known XLSX v1 header. Each
entry is classified as:

- `mapped`: maps directly to an application command/DTO field;
- `lossy`: maps only after controlled vocabulary normalization;
- `ambiguous`: needs manual interpretation before domain promotion;
- `derived`: target services must recompute or verify the value;
- `unsupported`: retained in raw provenance, never silently discarded.

Representative mappings:

| Legacy field | Application target | Classification |
| --- | --- | --- |
| `Документи.ID документа` | `ExternalReferenceInput.value` | mapped |
| `Документи.Назва документа` | `CreateEvidenceDocumentCommand.title` | mapped |
| `Документи.Провадження` | `EvidenceMembershipInput.context_id` | mapped link |
| `Хронологія.Дата / час` | `CreateEvidenceEventCommand.event_at` | mapped |
| `Файли.SHA-256` | `ManagedFileRecord.sha256` | mapped |
| `Провадження.Номер провадження` | `CreateWorkspaceProceedingCommand.proceeding_number` | mapped |
| computed counts, MIME and normalized names | target recomputation | derived |
| free-form notes, combined description/event fields and local paths | none | ambiguous |
| fields without a v1 target | raw migration payload | unsupported |

The complete executable matrix is authoritative; this document summarizes it.

## Dry-run and reconciliation

Dry-run does not open or mutate SQLite. Its report contains source/tree hashes,
format version, per-kind counts, proposed actions, field classifications,
duplicate conflicts, resolved/unresolved links and exactly one `record_results`
entry for each source record. `read_path_switch_allowed` is always `false`.

Duplicate external references, broken links, lossy/ambiguous values and unsupported
fields remain explicit. Conflicting occurrences are quarantined; records that can
be retained safely are marked `manual_review_required` rather than promoted.

## Import and transaction behavior

Import requires a verified writable backup destination outside the source tree.
It uses two passes:

1. upsert records by `(source_key, external_ref)` and payload hash;
2. resolve and upsert snapshot-local links.

An unchanged second import is skipped without duplicates. A changed payload with
the same stable external reference updates the migration row instead of creating a
second identity. Runs, issues and links are persisted for reconciliation.

All schema provisioning and writes run inside a SQLite savepoint. Any failure rolls
back the whole import. Source hashes are compared before release; a source change
during import also rolls back the transaction.

## Verification

`tests/test_legacy_import_c09.py` covers the frozen golden dry-run report,
zero-write behavior, field-catalog completeness, first/reimport/update scenarios,
resolved and broken links, duplicate quarantine, `.caseflow` sensitive-state skip,
read-only hash tree, backup gate, transaction rollback and fixture privacy scan.
