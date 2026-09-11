# VARTA architecture documentation manifest

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Version | `v1.0` |
| Date | `2026-08-25` |

## Approved C02 decision package

| File | Status | Purpose |
|---|---|---|
| `ADR-001-system-architecture.md` | `APPROVED` | local-first modular application, local web і dependency direction |
| `ADR-002-source-of-truth.md` | `APPROVED` | SQLite/managed-filesystem authority та projection roles |
| `ADR-003-migrations-backup-and-restore.md` | `APPROVED` | forward-only migrations і recovery model |
| `ADR-004-identity-and-cardinality.md` | `APPROVED` | opaque IDs, external references, many-to-many |
| `ADR-005-workspace-and-managed-storage.md` | `APPROVED` | multi-case workspace, zones і `.caseflow` transition |
| `ADR-006-local-http-security.md` | `APPROVED` | loopback Host/Origin/CSRF/CSP boundary |
| `ADR-007-sqlite-uow-and-workers.md` | `APPROVED` | per-operation UoW і isolated worker finalize |
| `technical-specification.md` | `APPROVED` | synchronized product/acceptance contract |
| `architecture-decision-log.md` | `ACTIVE` | ADR status registry |
| `open-questions.md` | `ACTIVE` | versioned owner/gate routing |
| `README.md` | `ACTIVE` | package entrypoint and priority |

## Active implementation contracts

| File | Status | Purpose |
|---|---|---|
| `local-api-v1.md` | `ACTIVE` | C03 `/api/v1`, application/UoW boundary, contacts contract і compatibility routes |
| `sqlite-lifecycle.md` | `ACTIVE` | C04 connection/UoW policy, schema range, migrations і DB-only recovery foundation |
| `managed-storage.md` | `ACTIVE` | C05 layout v1, immutable originals, streaming SHA-256 і reconciliation contract |
| `intake-v1.md` | `ACTIVE` | C06 file/folder/top-level-ZIP intake, idempotency, statuses та SQLite inventory contract |
| `workspace-v1.md` | `ACTIVE` | C07 multi-case workspace, temporary intake case, manual confirmation і active-case preference |
| `evidence-domain-v1.md` | `ACTIVE` | C08 evidence repositories/services, invariants, SQLite review authority, read DTO та compatibility sunset |

## Supporting legacy/target documents

| File | Purpose |
|---|---|
| `data-model.md` | Концептуальна модель даних SQLite |
| `external-integrations-schema.json` | Конфігурація optional integrations; Airtable disabled |
| `document-types.yaml` | Початковий класифікатор типів документів |
| `status-codes.yaml` | Канонічні машинні статуси та результати |
| `folder-structure.md` | Деталізація target managed zones |
| `naming-convention.md` | Правила назв файлів, каталогів та ідентифікаторів |
| `signature-verification-requirements.md` | Вимоги до КЕП та key boundaries |
| `matching-rules.md` | Рівні й результати document matching |
| `attachment-validation-rules.md` | Заявлені та фактичні додатки |
| `anonymized-example-packages.md` | Privacy-safe fixture policy |
| `expected-reports.md` | Мінімальний склад reports |
| `python-project-structure.md` | Target dependency/package direction |
| `integrations-api.md` | Optional adapter contracts |

## Пріоритет джерел

1. Поточна явна команда користувача та `AGENTS.md`.
2. `APPROVED` ADR.
3. `APPROVED` technical specification.
4. Versioned schema/API/profile/export contracts.
5. Канонічні VARTA status/roadmap documents.
6. Перевірений код і тести як implementation evidence.
7. Успадковані drafts і read-only migration materials.

## Governance

Архітектурну зміну оформлюють новим ADR; старе рішення отримує
`SUPERSEDED`. Implementation changes мають records у `docs/changes/`.
Open decisions зберігають stable ID, owner stage й closing gate у
`open-questions.md`; безвласних open questions бути не повинно.
