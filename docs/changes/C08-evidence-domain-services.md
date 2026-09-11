# C08 — evidence-domain repositories, services і review authority

| Field | Value |
|---|---|
| Task | `C08` |
| Dependencies | `C04`, `C07` |
| Baseline HEAD | `1becdce36e8393de713531e4d8fce8baa137e9be` |
| Branch | `codex/stabilize-baseline` |
| Scope | actors/documents/events/sources/claims/relations/findings/reviews, SQLite authority, read DTO/API |
| Originals impact | none; immutable originals and managed file bytes were not modified |
| Case data | none; fixtures and documentation are explicitly synthetic |
| Map/UI impact | none; no map-data generation and no product UI rebuild |
| Remote actions | none |

## Реалізовано

- additive schema `0010_evidence_services` і application schema ceiling `10`;
- typed evidence repository/application ports і concrete SQLite adapter;
- commands/queries/DTOs для actors, documents, events, source references,
  claims, typed relations, findings і review decisions;
- application invariants для orphan/type/source, confirmed evidence basis,
  file/document identity та many-to-many memberships;
- optimistic aggregate/review versions і append-only decision history;
- окремі automatic finding observations та user review history;
- transaction-scoped mutation + audit rollback;
- case evidence, timeline, source-context і review-history read models зі
  stable ordering/pagination;
- thin `/api/v1/evidence` transport без direct repository/SQLite calls;
- one-time typed legacy review import, authoritative SQLite state і bounded
  JSON compatibility sunset plan.

## Межі

- C09 legacy reconciliation/importer не розпочато;
- C10 durable processor lifecycle не розпочато;
- C11 Evidence Map projection і `map-data.json` не генеруються;
- C12/C13 UI/review workflow не перебудовуються;
- commit, push, publication, release та remote changes не виконуються.

## Verification evidence

| Gate | Current result |
|---|---|
| C08 required matrix | `28 passed in 7.02s` — aggregates, negative invariants, append-only/conflict, rollback, API/restart, v9 upgrade, schema/architecture |
| Full pytest | `201 passed in 42.44s` |
| Ruff | `All checks passed!` for `case_docket`, `caseflow`, `tests` |
| mypy | `Success: no issues found in 56 source files` for `case_docket caseflow` |
| compileall | passed for `case_docket`, `caseflow` (broader pre-final run also covered `tests`, `tools`) |
| JSON Schema | Draft 2020-12 schema check + empty example validation passed for case profile and map-data `1.1.0` |
| SQLite | schema ceiling/current `10`, required C08 tables present, `integrity_check=ok`, zero foreign-key violations |
| Upgrade/restart | v2 -> v10 additive fingerprint matches fresh DB; service/API and legacy compatibility state persist after restart |
| Review authority | both legacy review JSON types import once; user version `2` remains authoritative in SQLite and source JSON bytes stay unchanged |
| Privacy | only explicitly synthetic case-number fixtures and pre-existing OAuth identifiers were matched; no secret, personal, banking, protected-case or user-path finding |
| Diff/ownership | worktree/cached whitespace checks passed; C08 owns only the listed code/schema/tests/docs, while roadmap-controller files remain unrelated baseline changes |

Optional repository-wide `ruff format --check .` still reports 52 pre-existing
formatting candidates outside this package. C08 did not bulk-reformat those
files; required Ruff lint is green and new C08 modules are formatted.
