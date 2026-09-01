# ADR-002: SQLite and managed filesystem authority

| Metadata | Value |
|---|---|
| Status | `APPROVED` |
| Version | `v1.0` |
| Decision date | `2026-08-18` |
| Owner | `C02` |

## Контекст

Legacy CaseFlow зберігає authoritative-looking стан у XLSX, JSON і
`.caseflow`, тоді як VARTA вже має versioned SQLite migrations. Без формальної
authority boundary імпорт, UI, Evidence Map і звіти можуть непомітно
редагувати різні копії одного стану.

Структуровані записи й бінарні оригінали мають різні властивості: SQLite дає
транзакції та relations, а filesystem зберігає великі незмінні байти. Тому
джерело істини є узгодженою парою, а не одним файлом-експортом.

## Рішення

Authoritative state VARTA складається з:

1. **SQLite** — єдиного writable structured source of truth для сутностей,
   relations, provenance, workflow/review state, audit, job і export records.
2. **Managed filesystem** — authoritative сховища байтів originals і
   зареєстрованих artifacts. SQLite зберігає їхні stable IDs, relative paths,
   hashes, статуси й provenance.

Усі authoritative mutations проходять через application service. Прямий
запис presentation adapters або workers до SQLite/managed storage не є
дозволеним application flow.

Класифікація інших форматів:

| Формат | Дозволена роль |
|---|---|
| XLSX | read-only legacy import input або явно сформований compatibility export |
| JSON | input contract, job/result envelope або відтворювана projection |
| HTML | presentation чи sealed read-only export |
| `map-data.json` | детермінований read-only snapshot із revision/hash |
| external SaaS records | optional import/export adapter data з provenance |
| caches/indexes | disposable й відтворювані artifacts, не authority |

Projection/export не приймає edits назад без окремого валідованого import
use case. Якщо SQLite record і projection суперечаться, projection
перегенеровується; якщо DB metadata і managed bytes суперечаться, система
фіксує integrity failure й не переписує originals.

## Відхилені альтернативи

1. **XLSX/JSON як паралельна writable база.** Немає transaction/cardinality
   guarantees і виникає dual authority.
2. **`map-data.json` як editable master.** Snapshot не містить повного audit,
   processing та integrity lifecycle.
3. **SQLite BLOB для всіх originals.** Ускладнює streaming, зовнішню перевірку,
   backup великих файлів і processor interoperability.
4. **Filesystem metadata/імена як database.** Path/name не є stable identity й
   не моделює relations.
5. **Cloud database як canonical mirror.** Суперечить local-first/offline і
   потребує окремого security/consistency ADR.

## Наслідки

Inventory, review state, timeline, jobs і exports після restart читаються з
SQLite. Оригінальні байти перевіряються у managed filesystem за hashes та
inventory. XLSX/JSON/HTML залишаються корисними, але їхня роль завжди явна.

SQLite + filesystem не мають спільної фізичної транзакції. Application
services повинні використовувати staged/finalized states, idempotency та
reconciliation; деталі реалізують `C04`–`C06`.

## Вплив на міграцію

- до `C09` legacy `.caseflow`/XLSX/JSON можуть залишатися робочими лише як
  compatibility implementation, але не визначають target authority;
- `C06` створює перший end-to-end authoritative intake read-back із SQLite;
- `C09` виконує read-only inventory/dry-run/idempotent import і reconciliation
  перед switchover, не змінюючи legacy sources;
- `C11`/`C14` генерують projections/exports лише з application queries;
- жодна міграція не видаляє legacy state до окремої перевіреної процедури.

## Пов'язані рішення

- [ADR-003](ADR-003-migrations-backup-and-restore.md)
- [ADR-005](ADR-005-workspace-and-managed-storage.md)
- [ADR-007](ADR-007-sqlite-uow-and-workers.md)
