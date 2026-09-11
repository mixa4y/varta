# Durable processing jobs і plugin contract (C10)

## Призначення та межа

C10 визначає локальний, відновлюваний після crash/restart lifecycle для довгих
processor-задач поверх таблиці `processing_runs`. Контракт призначений для
майбутніх OCR, КЕП/P7S, STT і matching adapters, але C10 не містить жодного
реального алгоритму з цих категорій. Єдиний executable processor у цьому
package — synthetic reference worker для перевірки orchestration та integrity.

SQLite є джерелом істини для стану job/run і provenance. Файлова система під
managed `.varta` є джерелом істини для immutable originals, derived artifacts,
тимчасових attempt workspaces і quarantine. Operational JSON не є чергою або
authoritative state.

## Версійований processor contract

- Назва контракту: `varta.processor`.
- Версія контракту: `1`.
- Request і result серіалізуються canonical JSON з детермінованим SHA-256.
- Plugin оголошує `PLUGIN_VERSION` і `PLUGIN_CONTRACT_VERSION`.
- Невідома версія контракту, malformed JSON або невірний digest відхиляються до
  authoritative finalize.

### Request manifest

`ProcessorRequest` містить:

- `processor` — стабільне ім'я capability;
- `inputs[]` — `file_id`, очікуваний `sha256` та managed
  `storage_reference` кожного original;
- `parameters` — versionable JSON-параметри конкретного processor;
- `tool` — ім'я, версія та необов'язкові model name/version/hash;
- `limits` — wall-clock timeout, максимальний розмір result, artifact,
  stdout/stderr summaries і максимальна кількість artifacts;
- `contract` та `contract_version`.

SHA-256 усього canonical request є request fingerprint. Один
`idempotency_key` може відповідати лише одному fingerprint: повторна подача
повертає той самий job, а інший request з тим самим ключем завершується
conflict.

### Result manifest

`ProcessorResult` містить:

- `processing_run_id`, processor і terminal processor status;
- `request_sha256`, упорядковані `input_ids` та `input_hashes`;
- `parameters_sha256` і повний tool/model descriptor;
- timezone-aware `started_at` та `completed_at`;
- обмежені `stdout_summary` і `stderr_summary`;
- artifacts з role, relative path, hash, size, media type та source file IDs;
- structured findings з code, message, confidence і source file IDs;
- загальний confidence або явну відсутність;
- structured error з code, message, retryable і JSON details;
- `manifest_sha256`, обчислений без самого поля digest.

Finalize перевіряє digest, відповідність request/run, input order/hashes,
parameters/tool, source links і resource limits. Processor не може самостійно
записати authoritative success у SQLite.

## State machine

| Поточний стан | Дозволені наступні стани |
| --- | --- |
| `queued` | `running`, `cancelled`, `not_available` |
| `running` | `succeeded`, `failed`, `cancelled`, `interrupted`, `not_available` |
| `failed` | `queued` |
| `interrupted` | `queued` |
| `not_available` | `queued` |
| `succeeded` | немає |
| `cancelled` | немає |

Кожний перехід додає `processing_job_events`; update/delete history заборонені
SQLite triggers. `succeeded` і `cancelled` є terminal. Retry дозволений тільки
для `failed`, `interrupted` або `not_available`, лише якщо structured error має
`retryable=true` і не вичерпано `max_attempts`.

## Зв'язок із `processing_runs`

Створення `processing_runs`, `processing_jobs`, input links у
`processing_run_files` і першої event-записи відбувається однією SQLite
транзакцією. `processing_jobs.processing_run_id` має immutable foreign-key link
і unique index; job без відповідного run не створюється.

Таблиця `processing_jobs` зберігає повний C10 status. Історична таблиця
`processing_runs` має вужчий status constraint, тому `cancelled` відображається
там як `failed`, а `interrupted` як `partial`; точний стан і structured error
залишаються в job та event history. Success artifacts реєструються як
`file_objects(kind='derived', integrity_status='verified')` і як output links
`processing_run_files` у тій самій finalize-транзакції.

## Lease, restart і retry

1. Supervisor спочатку переводить expired `running` leases у `interrupted`.
2. Atomic claim переводить один `queued` job у `running`, збільшує attempt і
   видає opaque lease token з expiry.
3. Поки subprocess працює, supervisor поновлює lease heartbeat раніше expiry.
4. Після process crash job стає `interrupted`; після timeout — retryable
   `failed`; requested cancellation завершує його як `cancelled`.
5. Restart створює нові `SQLiteJobStore`/`JobService`, читає той самий стан з
   SQLite, recovery перериває протермінований lease, а явний retry повертає job
   у `queued` без створення другого processing run.

Lease token перевіряється при heartbeat, cancellation polling і finalize, тому
застарілий worker не може перезаписати результат нового attempt.

## Isolated worker lifecycle

Supervisor запускає processor окремим subprocess і не виконує довгу роботу в
HTTP thread. Перед запуском `ManagedProcessingWorkspace`:

1. перевіряє, що кожний input існує у managed originals, має очікуваний hash і
   не виходить за дозволену path boundary;
2. створює окремий attempt directory у processing working zone;
3. записує request envelope, де worker бачить лише дозволені absolute input
   paths і свій working output root;
4. повторно перевіряє original hashes до і після artifact finalize.

Worker пише тільки до attempt workspace. Після успішного subprocess exit
supervisor читає bounded result, перевіряє manifest та artifact hashes/sizes,
переміщує верифіковані artifacts у managed derived storage, робить їх read-only
і лише тоді виконує transactional application finalize. Invalid manifest,
digest/hash/path mismatch, timeout, cancellation і crash залишають attempt у
managed quarantine з opaque relative reference; originals не змінюються.

Synthetic worker не використовує мережу. Supervisor додатково передає
мінімальний allowlist системного environment, власний package path і
`VARTA_PROCESSOR_NETWORK=disabled`; credentials, OAuth/API tokens та довільні
parent-process variables не успадковуються. Network flag є декларативним test
invariant, а не заміною OS sandbox для майбутніх недовірених third-party
processors.

## Capability discovery та packaging

`discover_plugins()` повертає явний `PluginCapability` для кожного кандидата:

- `available` — module імпортується, version присутня, contract version
  підтримується;
- `unavailable_dependency` — module/dependency відсутні;
- `failed` — import або contract validation завершились іншою помилкою.

Silent import fallback заборонений. У source/installed Python supervisor
запускає `python -m case_docket.processing.synthetic_worker`. Для frozen
runtime потрібна конфігурація companion worker command через
`VARTA_PROCESSOR_WORKER` або явний `worker_command_prefix`; без неї capability
має стан `unavailable_dependency`, а не прихований in-process fallback.
Packaging script містить hidden import synthetic worker, а smoke test перевіряє
source capability, frozen unavailable state і configured frozen command path.

## Acceptance evidence

`tests/test_jobs_c10.py` використовує лише synthetic bytes та перевіряє state
transitions, atomic run/job link, append-only history, restart readback,
heartbeat, failure/retry, timeout, cancellation, crash/recovery, idempotency,
quarantine, unchanged original hash, server responsiveness, resource limits і
plugin/frozen capability states. Migration regression додатково доводить
послідовне оновлення існуючої SQLite schema до C10 integrity migration.
