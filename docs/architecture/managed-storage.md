# Managed storage та immutable originals

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Contract version | `v1.0` |
| Layout version | `1` |
| Owner package | `C05` |
| Decision basis | `ADR-002`, `ADR-004`, `ADR-005`, `ADR-007` |
| SQLite schema | `0007_intake_managed_storage` |

## Межа C05

C05 реалізує filesystem transaction boundary для одного source file: safe
path validation, streaming copy до staging, SHA-256/size verification,
no-overwrite finalize, SQLite metadata, duplicate signal та reconciliation.
Повний file/folder/ZIP intake, `import_batch`, HTTP/UI і document-role workflow
належать C06. Coordinated SQLite + filesystem backup/restore належить C15.

## Versioned workspace layout

`<workspace>/.varta/layout.json` фіксує contract, layout version і повний
перелік zones. Staging та originals створюються на одному volume.

```text
<workspace>/.varta/
├── layout.json
├── database/
│   └── varta.sqlite3
├── originals/
│   └── v1/<file_id[0:2]>/<file_id>/original.bin
├── staging/
│   └── v1/<file_id>.part + <file_id>.json
├── working/
├── derived/
├── reports/
├── exports/
├── logs/
├── backups/
├── quarantine/
└── temp/
```

Zone boundaries:

- `originals` містить лише finalized registered bytes; application code не
  overwrite/rename/delete-ить їх;
- `staging` містить same-volume partial bytes і versioned recovery manifests;
- `working` призначений для per-run processor state, не evidence/source of truth;
- `derived` містить лише зареєстровані відтворювані artifacts із provenance;
- `reports`/`exports` є projections, не writable authority;
- `logs` мінімізовані й не містять secrets;
- `backups` зарезервований для C15 coordinated snapshots і не є чинним
  backup assertion C05;
- `quarantine`/`temp` не стають прихованим місцем прийнятих originals.

## Identity, literal names і managed names

Native `file_id` — canonical lowercase UUIDv4. Він є opaque entity identity та
physical storage key. Partition береться лише з перших двох hexadecimal
символів UUID; source filename, case number, ПІБ, display name або SHA-256 не
потрапляють до physical path.

SQLite зберігає окремо:

- `original_name` — буквальний останній component source name без rename;
- `source_relative_path` — буквальний validated relative path;
- `managed_name` — optional presentation metadata, яке не адресується на disk;
- `storage_reference` — relative managed path від `.varta/`;
- byte length, lowercase SHA-256 та source modified/created timestamps;
- state/integrity state і recovery timestamps.

Транслітероване людиночитне ім'я може формувати presentation/export adapter за
КМУ №55, але зміна такого імені не змінює `file_id`, stored bytes або literal
provenance.

## Accept/finalize protocol

1. Перевірити canonical `file_id`, Windows-safe relative path, regular source
   file та відсутність symlink/reparse point у кожному traversed component.
2. Streaming chunks скопіювати до `staging/v1/<file_id>.part`, одночасно
   порахувати source SHA-256 і bytes; source відкривається лише для читання.
3. `fsync` staging, повторно прочитати staged bytes і звірити size/hash;
   повторно прочитати source й перевірити, що його hash/size/modified timestamp
   не змінилися під час copy.
4. Атомарно записати recovery manifest без абсолютного source path.
5. Короткою write UoW створити `file_objects` і `managed_storage_records` у
   state `prepared`; довге копіювання не виконується всередині DB transaction.
6. Ексклюзивно створити opaque target directory й same-volume `os.rename`
   staged object до відсутнього `original.bin`. Existing target ніколи не
   перезаписується.
7. Позначити finalized object read-only, повторно звірити bytes/hash/size і
   короткою UoW змінити state/integrity на `verified`.
8. Лише після verified DB state прибрати recovery manifest/staging residue.

SQLite triggers забороняють зміну identity/storage/source provenance після
registration та update/delete verified original metadata. Це
application/database defense-in-depth;
цілісність bytes усе одно перевіряється streaming SHA-256.

## Duplicate та collision policy

- Same SHA-256 повертає `duplicate_of_file_ids`, але нове приймання отримує
  окремий `file_id`, provenance record і physical object.
- V1 навмисно не робить content-addressed dedup: content identity не дорівнює
  document/entity identity, а ролі не зливаються автоматично.
- Same name/different bytes, same bytes/different names і case-insensitive
  managed-name collision не впливають на physical path.
- Uppercase/noncanonical UUID, повторний storage key, unexpected directory
  content або existing different bytes дають explicit collision/error без
  overwrite.

## Windows та archive path contract

Відхиляються absolute/drive-relative/UNC paths, empty/`.`/`..` components,
NUL/control/Windows-invalid characters, ADS colon, trailing dot/space,
reserved device names (`CON`, `NUL`, `COM1` тощо) та component понад 255 UTF-16
code units. Backslash і slash перевіряються однаково, тому archive traversal не
обходить policy. Загальний path може бути довшим за legacy `MAX_PATH`;
filesystem adapter використовує Windows extended paths і не переносить довге
literal name до managed target.

Source root, кожен source component, managed root і registered object
перевіряються через `lstat`; symlink/reparse-point escape не follow-иться.
Archive extraction тут не реалізовано: C06 мусить викликати той самий validator
до створення будь-якого entry.

## Crash recovery і reconciliation

Recovery manifest містить лише versioned metadata, relative references,
literal source provenance, timestamps, bytes/hash і state. Reconciliation:

| Стан після interruption | Дія |
|---|---|
| complete staging + manifest, DB row відсутній | відтворити DB link, finalize, verify |
| DB `prepared` + staged bytes | finalize, verify, mark `verified` |
| finalized bytes + manifest, DB не verified | verify/readonly, mark `verified` |
| DB record + bytes без manifest | verify registered reference |
| missing/different bytes | `reference_unavailable`/`mismatch`; originals не repair/overwrite |
| `.part` без manifest | report orphan; не приймати без provenance |
| finalized bytes без DB/manifest | report orphan; не adopt автоматично |

Locked/read failure, disk-full/short-write, manifest error і finalize collision є
explicit failures. Помилка одного operation не видаляє й не модифікує source.
Cleanup/reconciliation ніколи не вважає malformed or orphan bytes accepted
original лише через ім'я або розташування.

## Поточні обмеження

- C05 service не підключений до upload/HTTP UI; це свідома межа до C06/C12.
- V1 зберігає окремі bytes для duplicate provenance records; retention/dedup
  потребує окремого ADR і migration gate.
- Read-only attribute не замінює Windows ACL, BitLocker або threat model;
  VARTA додатково перевіряє hash і DB invariants.
- `backups` zone створюється, але C05 не проголошує coordinated backup complete.
