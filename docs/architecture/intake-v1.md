# VARTA authoritative intake v1

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Contract version | `v1.0` |
| Owner package | `C06` |
| SQLite schema | `0008_intake_batches` |
| API prefix | `/api/v1/intake` |
| Decision basis | `ADR-002`, `ADR-004`, `ADR-005`, `ADR-007` |

## Межа C06

C06 реалізує один authoritative vertical slice:

```text
file / folder / top-level ZIP
  -> IntakeService
  -> C05 immutable OriginalStorageService
  -> SQLite import batch + per-entry history
  -> SQLite-only inventory query after restart
```

Case detection, temporary `intake_case_id`, document roles, legacy
`.caseflow`/XLSX import, durable processors і повний intake UI не належать
C06. Legacy XLSX/JSON indexes не читаються inventory query і не є authority.

## SQLite model і lifecycle

`0008_intake_batches` додає:

- `intake_contexts` — opaque context, створений до enumeration;
- `import_batches` — idempotency key, request fingerprint, source URI,
  requested/detected kind, terminal summary/error і timestamps;
- `intake_entries` — literal provenance, status, size/timestamp/media hints,
  optional accepted `file_id`, duplicate references, warning/error;
- `import_batch_status_history` та `intake_entry_status_history` — append-only
  transitions;
- indexes для batch/status/source read-back і triggers, що забороняють
  invalid transition, provenance rewrite та видалення inventory/history.

Batch створюється в окремій короткій write UoW зі status `enumerating` до
читання input tree/archive. Enumeration не тримає SQLite transaction.
Discovered entries записуються, batch переходить у `processing`, а кожен
entry finalizes окремо. Тому failure одного entry не rollback-ить уже
verified originals або їхні committed provenance records.

## Status contract

| Entry status | Meaning |
|---|---|
| `discovered` | provenance metadata persisted; acceptance ще не завершено |
| `accepted` | новий verified managed original зареєстрований |
| `duplicate` | bytes збігаються з раніше відомим SHA-256, але створено окремий `file_id`, object і provenance |
| `failed` | entry не прийнято; stable error збережено |
| `skipped` | entry свідомо не materialized; причина збережена |

Batch `succeeded`, коли є accepted/duplicate entries і немає hard failures.
Benign ZIP directory members лишаються видимими `skipped`, але самі не роблять
batch partial. Failed entry або unsafe/duplicate/special skip поруч з
успішними entries дає `partial`; відсутність accepted/duplicate дає `failed`.

Warnings не підмінюють failure. Наприклад, verified original із recovery
manifest, який не вдалося прибрати, лишається accepted з
`storage_cleanup_pending` і потребує C05 reconciliation.

## Idempotency і retry policy

- Caller передає non-secret `Idempotency-Key`/CLI key.
- Fingerprint v1 складається з contract version, requested mode `auto` і
  caller-visible source URI; bytes не читаються до створення batch.
- Повтор того самого key/fingerprint повертає persisted batch з
  `replayed: true` і не enumerates input, не створює нових `file_id` та не
  копіює bytes повторно.
- Той самий key з іншим source URI дає `conflict`.
- Interrupted `enumerating`/`processing` batch також повертається як фактичний
  non-terminal record; C06 v1 не виконує небезпечний silent resume.
- Новий фізичний retry після виправлення source використовує новий key. Same
  bytes при цьому стають explicit `duplicate`, а попередня provenance/history
  не видаляється.

## File, folder та archive capability

### File

Приймається regular file. Source root/path chain, symlink і Windows reparse
point перевіряє той самий C05 path policy. Source відкривається read-only;
C05 повторно перевіряє size/SHA-256/modified timestamp до finalize.

### Folder

Traversal детермінований і не follow-ить symlink/reparse directories.
Unreadable, unsafe та special entries мають explicit failed/skipped records.
ZIP усередині folder у v1 є звичайним immutable file і не запускає recursive
archive expansion.

### Top-level ZIP

Закрите рішення `OQ-C02-001` для v1:

- підтримується лише top-level `.zip`;
- member bytes stream-яться в opaque per-entry temp, а не через
  `ZipFile.extract`; до materialization застосовується C05 Windows/archive
  path validator;
- absolute, drive/UNC, `..`, ADS, reserved name, invalid character, trailing
  dot/space і overlong component дають `unsafe_archive_path` без filesystem
  write за member path;
- case-insensitive duplicate member path не overwrite-иться: перший entry
  обробляється, повторний має `skipped/duplicate_archive_member`;
- zero-byte member приймається й отримує SHA-256 порожніх bytes;
- directory member є visible benign `skipped/archive_directory`;
- encrypted member має `failed/encrypted_archive_member`; password handling
  не входить у v1;
- nested ZIP зберігається як ordinary immutable member із type hint
  `nested_zip_not_expanded` і не розпаковується рекурсивно;
- corrupt central directory дає explicit failed batch/entry;
- `.7z`, `.rar`, `.tar`, `.gz`, `.bz2`, `.xz`, `.cab` та інші archive
  capabilities потребують окремого adapter/contract і не маскуються як ZIP.

Source ZIP fingerprint (bytes, size, modified timestamp) звіряється до/після
operation. Folder snapshot і C05 per-file checks підтверджують, що intake path
не змінює source tree.

## Provenance та inventory

Для кожного entry SQLite зберігає:

- source URI та literal validated relative path/name;
- `file`, `zip_member`, `directory`, `archive` або `special` kind;
- byte size і source created/modified hints, якщо вони наявні;
- extension, media type і versioned type hint;
- final status, warning/error і duplicate file IDs;
- accepted `file_id`, SHA-256 та managed `storage_reference` через join до C05
  tables.

ZIP DOS timestamp зберігається як timezone-less hint; він не видається за
trusted UTC time. HTTP upload використовує stable local `upload://request/...`
URI без workspace absolute path. CLI/local filesystem intake зберігає
`file://` URI у приватній local DB відповідно до provenance contract.

`IntakeService.inventory()` читає `import_batches`, `intake_entries`,
`file_objects` і `managed_storage_records` через read UoW. Він не scans source,
managed filesystem, XLSX, JSON index або legacy register. Response явно має
`authority: "sqlite"`.

## HTTP adapter

| Method | Path | Operation |
|---|---|---|
| `POST` | `/api/v1/intake` | multipart upload -> `IntakeCommand` |
| `GET` | `/api/v1/intake/inventory` | all batches або `?batchId=` |
| `GET` | `/api/v1/intake/batches/{batch_id}` | один persisted batch |

Mutation потребує чинний `X-Caseflow-Token` і `Idempotency-Key`.
`multipart/form-data` приймає лише file parts із field `files`; literal
relative filenames проходять archive/path policy. Один flat upload є file/ZIP
input; multiple files або browser relative folder стають folder input.
Transport temp видаляється після того, як C05 verified managed original, і не
створює legacy `00_INBOX`/XLSX authority.

HTTP handler виконує лише transport validation і викликає application service;
SQLite repository/storage layout у handler відсутні. Full intake workflow UI
належить C12/C13.

## CLI adapter

```text
varta-intake --workspace <path> add <file-or-folder-or-zip> --idempotency-key <key>
varta-intake --workspace <path> inventory [--batch-id <id>]
```

CLI друкує JSON. `succeeded` повертає exit `0`; persisted `partial`/`failed`
повертає exit `2`; unexpected adapter failure — exit `1`. CLI і HTTP
використовують той самий `IntakeService` та SQLite inventory query.

## Runtime DB compatibility

Fresh workspace використовує target `.varta/database/varta.sqlite3`. Якщо
існує legacy `.caseflow/varta.sqlite3`, а target DB ще не створена, C06
additively upgrades і використовує чинну DB in place, не копіює, не
перейменовує й не створює дві writable authorities. Read-only legacy
inventory/reconciliation і контрольований switchover залишаються C09/C15.
Якщо обидві DB уже існують, runtime fail-иться explicit
`WorkspaceDatabaseConflictError`, а не обирає authority мовчки.

## C06 acceptance

- file/folder/ZIP проходять input -> immutable storage -> SQLite -> restart
  read-back;
- source bytes/tree/timestamps не змінюються;
- accepted originals мають SHA-256, provenance, unique `file_id` і verified
  storage record;
- partial failure, duplicate content/member, zero-byte, corrupt ZIP,
  traversal, unsupported/encrypted/nested archive policy видимі;
- same-key retry не дублює, new-key same bytes створює окрему duplicate
  provenance;
- API/CLI adapters не читають repository напряму, а inventory не залежить від
  XLSX/JSON/legacy source.
