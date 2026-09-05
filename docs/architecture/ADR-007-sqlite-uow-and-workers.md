# ADR-007: SQLite Unit of Work and isolated workers

| Metadata | Value |
|---|---|
| Status | `APPROVED` |
| Version | `v1.0` |
| Decision date | `2026-08-18` |
| Owner | `C02` |

## Контекст

Embedded HTTP server може обробляти кілька запитів, а OCR/КЕП/STT/archive
processing може тривати довго або падати. Shared SQLite connection між
threads/processes, DB transaction на час processor run або прямий worker
write створюють lock, crash і audit risks. До `C03`/`C04` треба вибрати одну
connection boundary.

## Рішення

VARTA використовує **Unit of Work / connection per application operation**:

- кожен command або query відкриває власний short-lived SQLite connection/UoW
  і гарантовано закриває його;
- write UoW має одну явну transaction boundary; external process/file-heavy
  work не виконується всередині transaction;
- connection, cursor, repository instance або request context не передаються
  між HTTP threads, application operations чи worker processes;
- SQLite foreign keys, WAL/busy policy, transaction start mode й retry/error
  semantics централізує infrastructure/UoW implementation у `C04`;
- lock/busy не приховується як success і не запускає необмежені retries;
- read/query DTO від'єднується від connection до повернення presentation.

Heavy processing використовує двофазну boundary:

1. application service короткою транзакцією створює durable job/
   `processing_run` і immutable input references;
2. supervisor передає isolated worker serializable job envelope з IDs,
   versioned params і allowlisted read-only inputs;
3. worker не отримує SQLite connection/repository, не змінює `originals` і
   пише лише у виділений per-run staging/working target;
4. worker повертає versioned result manifest, hashes, warnings/errors і
   provenance;
5. application service в новій UoW валідує result і atomically finalizes
   authoritative DB state/managed artifact registration або фіксує failure.

Worker crash/timeout не залишає completed authoritative record без validated
result. Durable leasing, heartbeat, retry й orphan recovery деталізує `C10`,
не змінюючи цю boundary.

## Відхилені альтернативи

1. **Одна global SQLite connection для server і workers.** Небезпечно між
   threads/processes і приховує lifecycle.
2. **Long transaction навколо processor.** Блокує writes і робить crash
   recovery складним.
3. **Worker напряму змінює domain tables/files.** Обходить application
   validation, audit і atomic finalize.
4. **Окремий single-writer daemon/queue як mandatory v1 architecture.**
   Додає процесну складність без виміряної потреби; SQLite вже серіалізує
   writes, а short UoW достатній як стартова модель.
5. **Необмежений automatic retry.** Може дублювати effects і приховувати
   contention.

## Наслідки

Application ports мають включати Unit of Work, job supervisor й managed
storage. DTO/result manifests повинні бути serializable/versioned. Довгі
operations стають resumable/auditable, але потребують explicit state machine
та cleanup/reconciliation.

Якщо вимірювання покаже системний write contention, serialized writer можна
розглянути новим ADR; це не змінюється прихованим implementation detail.

## Вплив на міграцію

- `C03` створює UoW/job/storage ports і переносить один vertical slice;
- `C04` реалізує connection factory, transactions, busy/error policy та
  concurrency tests;
- `C10` реалізує durable jobs і isolated worker lifecycle;
- `C12` не тримає DB connection у HTTP handler/session;
- C02 не змінює чинний singleton-like repository у `caseflow/server.py` і
  явно залишає цей refactor наступним packages.

## Пов'язані рішення

- [ADR-001](ADR-001-system-architecture.md)
- [ADR-002](ADR-002-source-of-truth.md)
- [ADR-003](ADR-003-migrations-backup-and-restore.md)
