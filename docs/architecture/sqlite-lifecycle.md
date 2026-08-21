# SQLite lifecycle, schema compatibility and DB recovery foundation

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Version | `v1.0` |
| Owner package | `C04` |
| Decision basis | `ADR-003`, `ADR-007` |

## Межа C04

C04 реалізує connection/UoW lifecycle, migration gates, schema compatibility
та consistent **DB-only** snapshot. SQLite разом із managed filesystem є
authoritative pair, але filesystem originals, coordinated bundle, retention,
RPO/RTO й activation restored workspace належать `C05`/`C15` і тут не
реалізуються.

## Connection policy

Кожна application operation отримує нове thread-owned SQLite connection.
Connection, cursor або repository instance не зберігаються у HTTP state і не
передаються worker thread/process. Для кожного connection infrastructure
застосовує та перевіряє:

| Setting | C04 policy |
|---|---|
| `foreign_keys` | `ON` |
| `journal_mode` | `WAL` для file database |
| `busy_timeout` | `5000 ms` default; bounded і configurable для tests/runtime |
| `synchronous` | `NORMAL` |
| `wal_autocheckpoint` | `1000` pages default |
| thread ownership | Python SQLite default `check_same_thread=True` |

`busy`/`locked` не маскується як success і не має необмеженого retry. Після
вичерпання policy виникає `SQLiteBusyError` із фактичним timeout. Explicit
`PASSIVE`/`FULL`/`RESTART`/`TRUNCATE` checkpoint primitive доступний
infrastructure; default lifecycle спирається на WAL autocheckpoint.

## Unit of Work

- application command викликає factory з `write=True` і відкриває
  `BEGIN IMMEDIATE`;
- application query відкриває `BEGIN DEFERRED`;
- успішний command явно викликає `commit()`;
- exception, незакомічений context або downstream failure виконує rollback;
- context завжди закриває connection і є single-use;
- repository auto-commit compatibility methods також обгортають write та audit
  в одну explicit transaction.

Це дає WAL readers committed snapshot під час одного writer і переносить
bounded writer contention на початок command transaction.

## Forward-only schema contract

Application schema range C04: floor `2`, ceiling `6`. Fresh/upgrade bootstrap
завжди доводить DB до ceiling до writable application operation. Valid known
prefix нижче floor може бути migration input, але не normal application mode.

C05 additive migration `0007_intake_managed_storage` підняла поточний
application ceiling до `7`. C06 additive migration `0008_intake_batches`
підняла current ceiling до `8`; обидві не змінюють byte-for-byte migrations
`0001`–`0006` або C04 transaction/compatibility policy.

Застосовані `0001`/`0002` залишаються byte-for-byte immutable. C04 додає лише
forward-only indexes із явним logical scope:

| Version | Scope | Purpose |
|---|---|---|
| `0001_airtable_sql` | historical mixed baseline | system/case/Airtable compatibility schema |
| `0002_evidence_map_domain` | evidence/domain baseline | intake, case profile та evidence DDL |
| `0003_system_indexes` | system | audit/recovery lookup indexes |
| `0004_intake_indexes` | intake | processing/file/signature lookup indexes |
| `0005_case_indexes` | case | profile/candidate/membership lookup indexes |
| `0006_evidence_indexes` | evidence | reverse evidence-basis/review indexes |
| `0007_intake_managed_storage` | intake | immutable original metadata/recovery state |
| `0008_intake_batches` | intake | intake contexts, batches, entries та append-only status histories |

Runner вимагає безперервний packaged catalog, canonical UTF-8/LF checksum,
transaction на одну migration та scope prefix для additive tail. Перед apply
він перевіряє структуру й послідовність `schema_migrations`, recorded name і
checksum. DB із version вище ceiling, gap, malformed history, missing packaged
SQL або checksum mismatch отримує керовану помилку до application writable
mode. Concurrent startup повторно перевіряє history вже після отримання
`BEGIN IMMEDIATE` lock.

## Online backup and restore primitive

`create_online_backup()` використовує SQLite backup API, тому snapshot включає
consistent committed DB state навіть при WAL і не копіює live `.sqlite3`
звичайною filesystem copy. Primitive:

1. перевіряє current supported schema;
2. пише в окремий partial target;
3. має bounded busy handling;
4. закриває connections;
5. виконує `integrity_check`, `foreign_key_check` і schema check;
6. лише після success перейменовує partial target та повертає bytes/SHA-256.

`restore_sqlite_snapshot()` відтворює DB через той самий SQLite API лише у
новий target і повторює verification. Existing target та source=destination
відхиляються. Це foundation для `C15`, а не твердження про повний
SQLite+filesystem recovery bundle.

## Worker boundary

Legacy processing workers не імпортують `sqlite3` або
`case_docket.repository`, не отримують shared connection і не finalizes
authoritative DB state. Durable versioned job/result manifest та application
finalize реалізує `C10` без зміни цієї connection boundary.

## Acceptance evidence

C04 tests покривають fresh DB, upgrade із попереднього v2 fixture, однакову
fresh/upgraded schema, checksum mismatch, failed migration rollback,
newer/invalid DB, concurrent startup, per-connection PRAGMA, FK та append-only
negative cases, reader/single-writer contention, application rollback,
online backup, restore, integrity і committed read-back. Installed-wheel smoke
має повторити schema ceiling та backup/restore поведінку поза source checkout.
