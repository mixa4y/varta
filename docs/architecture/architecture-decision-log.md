# Architecture Decision Log

| Metadata | Value |
|---|---|
| Status | `DRAFT` |
| Version | `v0.1` |
| Date | `2026-07-24` |

## Правила журналу

Кожне архітектурно значуще рішення має окремий ADR. Журнал не замінює текст ADR, а показує його стан. Зміна затвердженого рішення створює новий ADR; попередній отримує `SUPERSEDED`, але не видаляється.

## Статуси

- `DRAFT`: рішення запропоноване й потребує затвердження.
- `APPROVED`: рішення чинне.
- `REJECTED`: варіант розглянуто й відхилено.
- `SUPERSEDED`: замінене новішим ADR.
- `ARCHIVED`: зберігається лише для історії.

## Реєстр

| ADR | Title | Status | Date | Replaces | Notes |
|---|---|---|---|---|---|
| `ADR-001` | System Architecture | `DRAFT` | `2026-07-24` | — | Local-first: Python + SQLite + filesystem; Airtable outside core |

## Заплановані рішення

Наступні теми ще не є рішеннями та не мають номера до створення ADR:

- identifier strategy;
- SQLite schema and migrations;
- immutable evidence storage and backup;
- UI technology;
- OCR engine;
- signature verification tooling;
- document parsing and matching engines;
- encryption and access control;
- packaging and updates for Windows.

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

## Open questions

- Хто має право переводити ADR у `APPROVED`?
- Чи потрібен окремий changelog для неархітектурних змін?
