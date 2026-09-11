# VARTA architecture decision log

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Version | `v1.0` |
| Date | `2026-08-18` |

## Правила журналу

Кожне архітектурно значуще рішення має окремий ADR. Журнал не замінює ADR,
а показує чинний статус. Зміна `APPROVED` рішення створює новий ADR;
попередній отримує `SUPERSEDED`, але не видаляється.

Статус `APPROVED` у цьому пакеті означає, що рішення затверджено явним scope
work package `C02`. Це не означає, що описаний refactor уже реалізовано.

## Статуси

- `DRAFT`: рішення запропоноване й потребує окремого затвердження.
- `APPROVED`: рішення чинне та є обов'язковою межею реалізації.
- `REJECTED`: варіант розглянуто й відхилено.
- `SUPERSEDED`: рішення замінене новішим ADR.
- `ARCHIVED`: файл зберігається лише для історії.

## Реєстр

| ADR | Title | Status | Date | Replaces | Implementation owner |
|---|---|---|---|---|---|
| [`ADR-001`](ADR-001-system-architecture.md) | Local-first system architecture | `APPROVED` | `2026-08-18` | draft v0.1 | `C03`, `C10`, `C12` |
| [`ADR-002`](ADR-002-source-of-truth.md) | SQLite and managed filesystem authority | `APPROVED` | `2026-08-18` | — | `C04`–`C06`, `C09`, `C11` |
| [`ADR-003`](ADR-003-migrations-backup-and-restore.md) | Forward-only migrations and consistent recovery | `APPROVED` | `2026-08-18` | — | `C04`, `C15` |
| [`ADR-004`](ADR-004-identity-and-cardinality.md) | Opaque identity, external references and cardinality | `APPROVED` | `2026-08-18` | — | `C03`, `C07`–`C09` |
| [`ADR-005`](ADR-005-workspace-and-managed-storage.md) | Multi-case workspace and managed storage | `APPROVED` | `2026-08-18` | — | `C05`, `C07`, `C09`, `C15` |
| [`ADR-006`](ADR-006-local-http-security.md) | Local HTTP security boundary | `APPROVED` | `2026-08-18` | — | `C03`, `C12`, `C15`, `C16` |
| [`ADR-007`](ADR-007-sqlite-uow-and-workers.md) | SQLite Unit of Work and isolated workers | `APPROVED` | `2026-08-18` | — | `C03`, `C04`, `C10`, `C12` |

## Versioned open decisions

Відкриті archive/encryption/scale/recovery рішення та routed legacy questions
мають ID, owner і closing gate у
[`open-questions.md`](open-questions.md). Вони не змінюють approved UI, source
of truth, identity, workspace, storage або connection boundaries і не блокують
створення application contracts у `C03`.

## Заплановані окремі рішення

Ці теми не змінюються реалізаційним рішенням без ADR/owner package:

| Тема | Owner |
|---|---|
| OCR/text extraction capability | `P01` після `C10` |
| КЕП/signature tooling and retention | `P02` після `C10` |
| document matching thresholds | `P04` після `C10` |
| network/multi-user mode | поза поточною roadmap; тільки новий ADR |
| server framework replacement | тільки measurable need + новий ADR |

Неархітектурні implementation changes фіксуються у `docs/changes/`; окремий
другий architecture changelog не потрібен.

## Change proposal format

```text
change_id:
document:
section:
current_text:
proposed_text:
reason:
status:
decision_date:
```
