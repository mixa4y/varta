# VARTA Python dependency structure

| Metadata | Value |
|---|---|
| Status | `APPROVED TARGET` |
| Version | `v1.0` |
| Date | `2026-08-18` |
| Decision | `ADR-001`, `ADR-007` |

## Layer responsibilities

### `domain`

Entities, value objects, invariants і domain result types. Не залежить від
SQLite, HTTP, UI, filesystem, processor SDK або зовнішніх adapters.

### `application`

Commands, queries, DTOs, service errors, orchestration, Unit of Work,
repository/storage/job ports. Не імпортує presentation framework або concrete
SQLite/filesystem adapters.

### `infrastructure`

SQLite repositories/UoW, managed storage, migration runner, hashing, parsers,
job supervisor, processors і optional external adapters. Реалізує application
ports.

### `presentation`

Local HTTP handlers, browser assets і CLI. Не містить domain rules, не
імпортує concrete repository і не читає workspace напряму.

## Dependency direction

```text
presentation -> application -> domain
infrastructure -> application/domain ports
workers -> serializable job/result contracts
```

Browser JavaScript використовує тільки `/api/v1`. Worker не отримує SQLite
connection/repository і не finalizes authoritative state.

## Current-to-target migration

Поточний repository зберігає `case_docket/` і `caseflow/`; C02 не перейменовує
packages і не створює application code. `C03` додає мінімальний application
package/ports і переносить один vertical slice. `C12` робить handlers thin.
Фізичний `src/` layout не є architecture requirement і не виправдовує mass
move.

## Engineering rules

- Python `3.12`, `pathlib`, type hints і explicit errors.
- Structured logs без secrets/private case payloads.
- Versioned SQL migrations; integration tests для SQLite/storage.
- Architecture tests забороняють presentation -> infrastructure/repository.
- Dependency/framework addition потребує measurable need і license review.

## Open decisions

| Question | Owner stage | Closing gate |
|---|---|---|
| Exact application package names, DI/config bootstrap і DTO layout | `C03` | `C03 PASS` |
| Exact infrastructure package split after first storage/job slices | `C05`, `C10` | respective PASS |

HTTP framework replacement не є open default: stdlib може залишатися; заміна
потребує нового ADR із measurable reason.
