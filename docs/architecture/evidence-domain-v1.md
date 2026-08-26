# VARTA evidence-domain services v1

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Contract version | `v1.0` |
| Owner package | `C08` |
| Dependencies | `C04`, `C07` |
| SQLite schema | `0010_evidence_services` over `0002_evidence_map_domain` |
| JSON read-model schema | `1.1.0` |
| API prefix | `/api/v1/evidence` |
| Decision basis | `ADR-002`, `ADR-004`, `ADR-007` |

## Межа C08

C08 завершує repository/application flow для actors, documents, events,
source references, claims, typed relations, findings і review decisions. Усі
HTTP mutations та reads проходять через `EvidenceService` і short-lived
SQLite UoW. Цей contract не генерує `map-data.json`, не змінює Evidence Map UI
і не реалізує наступні C09–C13 packages.

SQLite та managed filesystem лишаються authoritative. Evidence DTO —
application read model, який C11 зможе використати без direct SQL. JSON-файли
review status не є другою writable truth.

## Aggregates і repository boundary

Application ports описують такі операції:

- create/read actors, documents і events;
- create/read source references із перевіркою target entity, file identity та
  optional SHA-256;
- create/read claims і typed relations разом з evidence basis;
- record automatic finding observations окремо від user reviews;
- append user review decision з optimistic version check;
- read case evidence, timeline, source context і review history;
- transitional import/read/write legacy review state через SQLite compatibility
  tables.

Concrete `SQLiteEvidenceRepository` реалізує ці ports поверх existing DDL та
additive migration `0010`. HTTP adapter не імпортує repository і не виконує
SQL. Commit/rollback належать application UoW; audit row створюється у тій
самій transaction, що й domain mutation.

## Domain invariants

### Identity та cardinality

- `file` і `document` — різні identities. Document може мати zero/many files;
  file link не робить file ID document ID, а identity collision відхиляється.
- Case/proceeding membership зберігається link rows у
  `entity_memberships`; один entity може належати кільком contexts.
- Actor-to-event, document-to-event, claim assertor/basis/source та relation
  basis/source — explicit many-to-many links.
- Display names, source paths, case numbers, fingerprints і hashes не є
  primary domain identity.

### Referential integrity і evidence basis

- Subject/endpoints/source targets мусять існувати та мати дозволений type;
  orphan або unsupported polymorphic type відхиляється application service до
  commit.
- Claim/relation з `classification=confirmed_fact` або
  `reviewStatus=confirmed` мусить мати щонайменше один existing
  `basisDocumentId` або `sourceReferenceId`.
- Location `page`, `paragraph`, `timecode`, `bounding_box` або `whole_file`
  вимагає `sourceFileId`.
- Якщо command подає SHA-256 разом із source file, він не може суперечити
  authoritative `file_objects.sha256`.
- `limit` має бути integer `1..200`; `offset` — non-negative integer.

### Review history та optimistic concurrency

Core reviewable aggregates мають integer `version`, починаючи з `1`.
User review command передає `expectedVersion`; update виконується лише для
поточної version, збільшує її на один і додає immutable `review_decisions`
row. Stale command повертає conflict, не змінюючи aggregate, history чи audit.

Finding тримає дві незалежні осі:

- `automaticVersion` і append-only `finding_observations` — кожен processor
  observation із detector name/version, severity, confidence та details;
- `reviewVersion`, `reviewStatus` і append-only
  `finding_review_decisions` — лише explicit user/compatibility decisions.

Повторний automatic observation ніколи не скидає user review status/version.
SQL triggers забороняють update/delete automatic observations, finding review
decisions, compatibility decisions і existing core review decisions.

## Public DTO contract

DTOs використовують camelCase machine keys і opaque `id`:

| DTO | Мінімальні public fields |
|---|---|
| Actor | `id`, `actorType`, `displayName`, `roles`, `sourceReferenceIds`, `reviewStatus`, `version` |
| Document | `id`, `caseIds`, `memberships`, `title`, `fileIds`, linked IDs, `classification`, `reviewStatus`, `version` |
| Event | `id`, `caseIds`, `memberships`, `date`, actor/document/claim/relation/source IDs, statuses, `version` |
| Source reference | `id`, `sourceEntity`, `sourceFileId`, location, excerpt/hash/provenance, `reviewStatus`, `version` |
| Claim | `id`, `subject`, `text`, classification, assertors, basis/source/review IDs, memberships, `version` |
| Relation | `id`, `fromType/fromId`, `toType/toId`, `relationType`, basis/source/review IDs, classification, `version` |
| Finding | `id`, `fingerprint`, detector, automatic status/version, review status/version, subjects/source/review IDs |
| Review decision | `id`, `subject`, decision/status transition, actor/time, basis sources, `subjectVersion`, `origin` |

`CaseEvidenceDTO` має `schemaVersion: "1.1.0"`, `caseId`, page metadata,
domain arrays та `authority: "sqlite"`. Він є read model; це ще не
`map-data.json` export.

## Ordering і pagination

Ordering є explicit і стабільним:

- membership-backed actors/documents/events/claims — first membership
  `created_at`, потім opaque ID;
- sources і relations — `created_at`, ID;
- findings — `last_observed_at DESC`, ID;
- timeline — `occurredAt`, entity type, entity ID;
- review history — `decidedAt`, decision ID;
- linked ID arrays — machine-key/ID order.

Case read застосовує однакові `limit`/`offset` окремо до кожного aggregate
array. Timeline і review history мають власну page. Default — `limit=100`,
`offset=0`; maximum limit — `200`.

## Versioned HTTP routes

| Method | Path | Operation |
|---|---|---|
| `POST` | `/api/v1/evidence/actors` | create actor |
| `POST` | `/api/v1/evidence/documents` | create logical document |
| `POST` | `/api/v1/evidence/events` | create event + actor/document links |
| `POST` | `/api/v1/evidence/source-references` | create validated source reference |
| `POST` | `/api/v1/evidence/claims` | create claim + basis/source/membership links |
| `POST` | `/api/v1/evidence/relations` | create typed relation + evidence basis |
| `POST` | `/api/v1/evidence/findings` | append automatic finding observation |
| `POST` | `/api/v1/evidence/reviews` | append core aggregate review decision |
| `POST` | `/api/v1/evidence/findings/{id}/reviews` | append finding user decision |
| `GET` | `/api/v1/evidence/cases/{caseId}` | paged case evidence read model |
| `GET` | `/api/v1/evidence/timeline?caseId=...` | paged timeline |
| `GET` | `/api/v1/evidence/source-references/{id}` | source plus linked claim/relation/finding IDs |
| `GET` | `/api/v1/evidence/reviews?subjectType=...&subjectId=...` | paged append-only history |

Mutations require launch token. Unknown request fields are rejected. Success
uses the existing v1 envelope; creates return `201`, reads `200`. Stable errors
are:

- `request_validation_error` / `validation_error`, HTTP `422` — malformed
  payload/query, unsupported type, invalid membership/page або missing basis;
- `not_found`, HTTP `404` — referenced aggregate/source/context is absent;
- `conflict`, HTTP `409` — stale version, duplicate/identity collision або hash
  contradiction;
- storage/unexpected errors, HTTP `500`, without silently hiding the failure.

## Legacy review compatibility і sunset

At startup, existing `.caseflow/document_status.json` and
`.caseflow/anomaly_status.json` may be imported once by a typed content token
(`subjectType` + content SHA-256 semantics). Import creates only missing
external IDs, records `origin=compatibility_import`, and never overwrites a
newer SQLite row. All subsequent user mutations write SQLite
`compatibility_review_states` plus append-only decisions.

`anomaly_status.json` may temporarily be regenerated from SQLite immediately
before/after the isolated legacy anomaly worker. It is a disposable projection,
not authority. `document_status.json` is no longer a write target.

Sunset plan:

1. C09 inventories/reconciles all remaining legacy `.caseflow` review inputs
   and proves idempotent import.
2. C10 replaces the legacy anomaly worker hand-off with the durable processor
   result contract; the anomaly JSON projection can then be removed.
3. C12/C13 move the remaining web review consumers to `/api/v1/evidence`.
   No later than C13 PASS, remove the startup JSON import and compatibility
   review routes after an upgrade/reconciliation test proves there are no
   unresolved legacy-only rows.

Legacy source files remain read-only migration evidence; sunset removes
adapters, not source materials.

## C08 acceptance

- every listed aggregate has repository/application create/read coverage;
- orphan/type/source/basis/file-document invariants fail before commit;
- user decisions and automatic observations have separate append-only history;
- stale version conflicts and late audit failure rollback the whole mutation;
- synthetic case reads through services and thin HTTP routes after restart;
- query ordering, pagination and error mappings are deterministic;
- review authority is SQLite, with a bounded compatibility import sunset;
- no map-data generation or UI rebuild is part of C08.
