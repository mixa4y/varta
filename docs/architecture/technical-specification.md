# VARTA technical specification

| Metadata | Value |
|---|---|
| Status | `APPROVED` |
| Version | `v1.0` |
| Decision date | `2026-08-18` |
| Architecture gate | `C02 PASS`; implementation remains staged in `C03`–`C16` |

## Мета

Створити універсальний local-first Windows-застосунок для керованого
приймання, незмінного збереження, аналізу, review та візуалізації матеріалів
судових справ без SaaS dependency і без hardcode конкретної справи.

## Scope

- Імпорт окремих файлів, каталогів і ZIP через application service.
- Створення intake context, `import_batch` та authoritative file inventory.
- Streaming SHA-256, provenance і незмінна managed copy оригіналу.
- Виявлення дублів без автоматичного видалення або злиття provenance.
- Case bootstrap, multi-case workspace й explicit active-case context.
- Documents/events/claims/sources/relations із many-to-many cardinalities.
- Durable processing jobs, isolated local workers і versioned results.
- Manual review окремо від automatic findings.
- Детерміновані Evidence Map/report projections і sealed exports.
- Consistent SQLite + managed-filesystem backup/restore й Windows delivery.

## Out of scope для першого release path

- Автоматична юридична кваліфікація доказів або твердження про фальсифікацію.
- Багатокористувацький, LAN, cloud або remote server mode.
- Notion як документація, інтеграція, runtime або source of truth.
- Обов'язковий Airtable чи інший зовнішній сервіс.
- Передавання приватних ключів зовнішнім сервісам.
- Приховане application-level encryption claim до закриття `OQ-C02-002`.
- Destructive down migrations або in-place restore поверх active workspace.

## Target architecture

```text
browser on explicit loopback
  -> versioned local HTTP adapter
  -> application commands/queries + Unit of Work
  -> domain + ports
  -> SQLite + managed filesystem
  -> durable supervisor -> isolated workers -> result manifest -> finalize
```

Dependencies і migration impact визначають `ADR-001` та `ADR-007`. Поточна
legacy реалізація ще не повністю відповідає цій схемі; C02 не змінює код і не
проголошує application layer завершеним.

## Source of truth

Authoritative system state — узгоджена пара:

- SQLite як єдине writable structured source of truth;
- managed filesystem як authoritative сховище registered bytes.

XLSX/JSON/HTML, `map-data.json`, reports і exports є import/export/projection
artifacts. Вони не стають другою editable database. Усі mutations проходять
через application service; детальний контракт — `ADR-002`.

## Workspace and storage

Один workspace містить одну DB і багато справ. UI має нуль або одну active
case за раз, але кожен command/query/job отримує context ID явно. Цільовий
runtime root — `<workspace>/.varta/` із versioned `layout.json` та zones
`database`, `originals`, `staging`, `working`, `derived`, `reports`, `exports`,
`logs`, `backups`, `quarantine`, `temp`.

Originals не перезаписуються й не перейменовуються. Literal source name/path,
managed display name і physical storage key є різними полями. `.caseflow`
залишається read-only compatibility source до контрольованого import,
reconciliation і switchover за `ADR-005`.

## Identity and data model

- internal IDs — opaque canonical UUID strings, незалежні від names/paths;
- external references та raw values зберігаються окремо з provenance;
- same hash не означає same provenance record;
- many-to-many membership/relations використовують link tables/entities;
- automatic result і user decision зберігаються окремо;
- unknown не підмінюється порожнім рядком або вигаданим фактом.

Повний контракт — `ADR-004`; domain implementation/cardinality gate належить
`C07`/`C08`.

## SQLite lifecycle

- numbered forward-only SQL migrations;
- LF-normalized checksum й immutable applied migration;
- transactional apply та supported-schema preflight;
- short-lived connection/UoW per application operation;
- жодного shared connection для HTTP threads/workers;
- no long DB transaction навколо file/processor work;
- rollback data/schema change — consistent verified restore, не down SQL.

`C04` реалізує connection, concurrency й online-backup details. `C15` доводить
coordinated SQLite + filesystem recovery за `ADR-003`/`ADR-007`.

## Local HTTP interface and security

Primary UI — embedded browser UI, який віддає локальний застосунок. Server
bind-иться лише на explicit loopback; browser UI не імпортує repository й не
читає workspace напряму. Mutations потребують allowlisted Host, exact Origin
і per-launch CSRF header. CORS/remote assets/LAN mode вимкнені; CSP та security
headers обов'язкові. Повний target contract — `ADR-006`.

CLI, HTTP і майбутні adapters викликають однакові application services. API v1
має stable DTO/error envelope; його реалізує `C03`.

## Intake and integrity

Система створює intake context і `import_batch` до enumeration. Для кожного
entry зберігаються source reference, literal name, size/timestamps, status і
error. Помилка одного entry не приховує успішні. Original копіюється streaming
у managed storage без зміни source bytes; SHA-256 перевіряється повторно без
модифікації файла.

Перший required contract: file, folder і ZIP. Інші/nested/encrypted archive
capabilities закриває `OQ-C02-001` у `C06`.

## Processing and review

Application service створює durable job/`processing_run`; isolated worker
отримує serializable envelope та працює лише у per-run staging. Worker не має
SQLite connection/repository й не змінює originals. Versioned result manifest
валідується й finalizes новою Unit of Work. Crash/timeout/retry не маскується
як success.

Невизначені/конфліктні результати отримують `manual_review_required`.
Automatic finding і підтверджене/відхилене user decision мають окрему history.

## Projections and exports

Evidence Map, inventory, timeline й reports генеруються з application queries
та мають schema/tool/source revision. Sealed export є read-only, має manifest
і hashes, не робить network requests і не повертає edits у source of truth.

## Functional acceptance gates

- Source input hash/bytes/timestamps не змінюються після intake.
- Кожен accepted original має SHA-256, provenance і registered storage record.
- Після restart inventory читається із SQLite без XLSX authority.
- Same name/different bytes і same bytes/different source не overwrite-яться.
- UI mutation проходить HTTP -> application service, не repository напряму.
- Worker crash не створює completed authoritative result.
- Projection відтворюється з DB revision й не є editable truth.
- Restore у new/empty target перевіряє DB integrity та registered file hashes.
- Host/Origin/CSRF/CSP/path/archive negative cases керовано відхиляються.

## Non-functional requirements

- Python `3.12`, Windows, Unicode/кирилиця, long-path і case-insensitive
  collision tests.
- Offline operation без обов'язкової мережі або SaaS.
- Type hints, unit/integration/contract/architecture/browser tests.
- Structured local logs без secrets/case data leakage.
- Forward-compatible versioning для DB/API/profile/projection/export/job.
- Performance targets не вигадуються; `C16` версіонує corpus profile й вимірює
  його до release gate (`OQ-C02-003`).

## Versioned open decisions

| ID | Owner | Closing gate | Current constraint |
|---|---|---|---|
| `OQ-C02-001` archive variants | `C06` | `C06 PASS` | required file/folder/ZIP only; extra capability explicit |
| `OQ-C02-002` encryption at rest | `C15` | `C15 PASS` | no encryption claim; Windows account/ACL boundary |
| `OQ-C02-003` target corpus scale | `C16` | `C16 TECH PASS` | version acceptance profile before measuring |
| `OQ-C02-004` RPO/RTO/retention | `C15` | `C15 PASS` | consistent completed backup/restore contract only |

Повний routing legacy questions: [`open-questions.md`](open-questions.md).

## Architecture references

- [`ADR-001`](ADR-001-system-architecture.md)
- [`ADR-002`](ADR-002-source-of-truth.md)
- [`ADR-003`](ADR-003-migrations-backup-and-restore.md)
- [`ADR-004`](ADR-004-identity-and-cardinality.md)
- [`ADR-005`](ADR-005-workspace-and-managed-storage.md)
- [`ADR-006`](ADR-006-local-http-security.md)
- [`ADR-007`](ADR-007-sqlite-uow-and-workers.md)
