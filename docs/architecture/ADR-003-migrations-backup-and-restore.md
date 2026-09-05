# ADR-003: Forward-only migrations and consistent recovery

| Metadata | Value |
|---|---|
| Status | `APPROVED` |
| Version | `v1.0` |
| Decision date | `2026-08-18` |
| Owner | `C02` |

## Контекст

VARTA вже має numbered SQL migrations, transactional apply та checksum
verification. Зміна або destructive rollback уже застосованої схеми може
знищити provenance й зробити DB несумісною з managed files. Окреме копіювання
живої SQLite або тільки файлової зони не створює узгодженої backup-копії.

## Рішення

Schema evolution є **forward-only**:

- кожна зміна — новий versioned `.sql` migration із монотонним номером;
- migration застосовується транзакційно й реєструється в
  `schema_migrations`;
- checksum обчислюється з UTF-8 SQL після нормалізації `CRLF`/`CR` до `LF`;
- вже застосований migration є immutable; checksum mismatch блокує запуск;
- застосунок перевіряє supported schema range до відкриття writable mode;
- destructive down migrations не є rollback mechanism.

Rollback data/schema change означає відновлення **узгодженої завершеної
backup-копії** у новий або порожній target. Цільовий backup contract:

1. припинити нові authoritative finalizations і дочекатися/зафіксувати стан
   активних jobs;
2. створити consistent SQLite snapshot через SQLite backup API;
3. скопіювати зареєстровані managed files за DB inventory;
4. записати schema/app versions, hashes, inventory і exclusions у manifest;
5. додати completion marker тільки після повної перевірки;
6. під час restore перевірити manifest, DB integrity, migrations, file hashes,
   provenance links і sample read-back до activation.

Application binary можна повернути на попередню версію лише якщо вона явно
підтримує поточну schema. Інакше потрібне відновлення всієї узгодженої
backup-копії, а не частковий downgrade.

## Відхилені альтернативи

1. **Редагувати застосований SQL migration.** Порушує відтворюваність.
2. **Автоматичні destructive down migrations.** Можуть втратити дані та
   provenance, які старіша schema не представляє.
3. **Копіювати live `.sqlite3` звичайною filesystem copy.** Може не включити
   WAL/узгоджений стан.
4. **Backup лише DB або лише originals.** Не відновлює authoritative пару.
5. **Restore поверх активного workspace.** Ризикує змішати revisions і байти.

## Наслідки

Міграції можуть потребувати additive/transitional schema та двофазного
backfill. Будь-яка ризикова зміна вимагає preflight і backup. Backup займає
додатковий простір та потребує quiesce/finalize protocol.

Числові RPO/RTO й retention ще не вигадуються; це versioned open question
`OQ-C02-004` із owner `C15`.

## Вплив на міграцію

- поточні migrations `0001`/`0002` залишаються immutable;
- `C04` завершує lifecycle, busy policy, compatibility checks і SQLite online
  backup primitive;
- `C15` реалізує coordinated SQLite + filesystem backup/restore, retention і
  recovery evidence;
- upgrade tooling не видаляє user workspace й не підміняє recovery down SQL.

## Пов'язані рішення

- [ADR-002](ADR-002-source-of-truth.md)
- [Open decisions](open-questions.md)
