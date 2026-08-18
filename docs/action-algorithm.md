# Алгоритм дій з розвитку VARTA

**Тип документа:** канонічний порядок аналізу, реалізації та приймання змін

**Версія:** 1.3

**Дата оцінки:** 18.08.2026

**Статус:** `ACTIVE` — рішення погоджуються й реалізуються покроково

**Сфера дії:** VARTA core, SQLite, intake, Evidence Map, local UI, автономні
експорти, Windows packaging і міграція сумісності з CaseFlow/CMSD

**Інтерактивне подання:**
[`interactive/varta-action-map.html`](interactive/varta-action-map.html) —
розкривна карта етапів `A0`–`A12` зі статусом, роботою, перевіркою та gate
переходу для кожного кроку.

## 1. Призначення

Цей документ перетворює розрізнені інструкції, blueprint, відкриті рішення
та успадкований план робіт на один виконуваний алгоритм. Він відповідає на
чотири питання:

1. що у VARTA вже підтверджено кодом і тестами;
2. які рішення треба погодити до наступної значної реалізації;
3. у якій послідовності змінювати модель, SQLite, intake, мапу та UI;
4. за якими доказами етап можна вважати завершеним.

План не є дозволом на масове переписування, видалення, commit, push або
публікацію. Кожен етап виконується лише в межах окремої погодженої задачі.

## 2. Джерела та їх пріоритет

Під час оцінки використано:

1. явні команди користувача;
2. `AGENTS.md` і privacy boundary VARTA;
3. `PROJECT_STATUS.md`;
4. `docs/blueprints/evidence-map-blueprint.md`;
5. JSON Schema профілю справи та snapshot Evidence Map;
6. успадковані архітектурні документи в `docs/architecture/`;
7. фактичний Python-код, тести, конфігурацію та Windows tooling;
8. загальні legacy-інструкції CSMD як read-only джерело міграції.

Успадкований документ зі статусом `DRAFT` не стає погодженим лише через
перенесення до репозиторію. За суперечності діє такий порядок:

1. поточна явна команда користувача;
2. `APPROVED` ADR;
3. канонічні документи VARTA;
4. перевірений код і тести;
5. успадковані чернетки;
6. історичні припущення.

## 3. Результат оцінки поточного стану

### 3.1. Перевірений baseline

На дату оцінки виконано:

```text
pytest       82 passed
ruff         All checks passed
mypy         Success: no issues found in 26 source files
compileall   passed
diff-check   whitespace errors not found
wheel        SQL migrations, Airtable schema, static UI і version manifest included
VARTA.exe    packaged API/SQLite smoke passed; 2 migrations applied
```

У tracked-файлах не знайдено PDF, DOC/DOCX, P7S, XLS/XLSX, SQLite/DB,
ZIP або RAR. Числові шаблони справ і проваджень у тестах є явно вигаданими
fixtures, а не матеріалами реальної справи.

Початковий P0 tree було розділено на предметні commits і перевірено з clean
checkout. C01 потім окремо стабілізував roadmap/controller scope та
repository-guidance scope. На старті C02 controller зафіксував чистий
`codex/stabilize-baseline` на
`c3a5b122894e81aff2d82078df7e38e5659d3733`: tracked/staged/untracked status
empty. `docs/chat-roadmap.md`, його interactive companion і controller тепер є
tracked C01 baseline, а не паралельними untracked файлами.

C01 evidence: 94 tests, Ruff, mypy, compileall, wheel/install proof,
synthetic HTTP/SQLite restart smoke і privacy scan passed. C02 змінює лише
architecture/spec/status/tests і не виконує product refactor.

### 3.2. Що вже реально існує

- канонічний репозиторій і privacy boundary;
- domain-моделі документів, файлів, учасників, подій і дат;
- контрольовані словники та статуси;
- транслітерація за КМУ №55 і Windows-safe керовані назви;
- versioned SQLite schema, migration runner, repository та append-only
  `audit_log`;
- повне відображення історичної Airtable-моделі: 9 таблиць, 127 полів,
  38 record-link зв'язків і 12 computed fields;
- SQLite API та інтегрована детальна картка контактів;
- локальний HTTP server, upload, preflight, processing і anomaly detector;
- успадкований XLSX-oriented processing pipeline;
- JSON Schema та порожні шаблони case profile і Evidence Map snapshot;
- versioned migration `0002_evidence_map_domain.sql` із DDL для case profile,
  file objects, processing runs, source references, claims, evidence relations,
  review decisions, amounts та export records;
- локальна Evidence Map HTML-в’юха з embedded JSON;
- Windows build/install/start/update tooling як матеріал міграції;
- 82 автоматизовані тести.

### 3.3. Рівні готовності SQLite/Evidence Map

Наявність таблиці не прирівнюється до наявності repository API, а наявність
API — до наскрізного application flow:

| Рівень | Фактичний стан | Статус |
|---|---|---|
| Versioned DDL | `0001_airtable_sql.sql` і `0002_evidence_map_domain.sql` застосовуються migration runner; checksum і rollback-on-error перевірені | `DONE` для поточного DDL contract |
| JSON contract | case profile і Evidence Map schema `1.1.0`, privacy-safe templates та negative tests синхронізовані | `DONE` |
| Repository API | CRUD/API існують для legacy-compatible core, Airtable import і контактів; окремих services для claims, evidence relations, source references, review decisions та exports ще немає | `PARTIAL` |
| Application flow | контакти працюють через SQLite/API/UI; intake та Evidence Map ще не проходять повний шлях SQLite → application service → projection/UI/export | `PARTIAL` |

Отже Evidence Map domain має точний статус: **`DDL/CONTRACT DONE`**, але
**`REPOSITORY API PARTIAL`** і **`APPLICATION FLOW PARTIAL`**.

### 3.4. Що ще не є завершеною системою

- `ADR-001`–`ADR-007` затверджені C02, але implementation boundaries ще не
  перенесено повністю в код;
- CaseFlow pipeline та SQLite repository ще не утворюють один application
  flow для intake та Evidence Map;
- XLSX/`.caseflow` ще потребують контрольованого read-only adapter до SQLite;
- migration `0002` створює `claims`, `evidence_relations`,
  `source_references`, `processing_runs` та інші Evidence Map tables, але
  repository/application services для них ще не реалізовані;
- DDL ще не охоплює повний intake batch flow, а наявні domain constraints не
  замінюють application-level invariants і наскрізні integration tests;
- немає інтегрованого immutable storage service для оригіналів;
- case number bootstrap і `manual_review_required` описані контрактом, але
  не реалізовані наскрізно;
- Evidence Map ще не генерується детерміновано із SQLite;
- sealed export не має повного generator/manifest/validation flow;
- немає перевіреного backup-and-restore release gate;
- `.caseflow` залишається compatibility runtime; target `.varta` затверджено,
  але safe migration ще не реалізовано.

### 3.5. Головний архітектурний ризик

Найбільший ризик — не окремий відсутній модуль, а роздвоєння стану:

```text
CaseFlow UI/process -> XLSX + .caseflow

case_docket core    -> draft SQLite repository
```

До появи одного application flow не можна вважати SQLite фактичним джерелом
істини всього продукту. Генератор мапи, новий UI або packaging, побудовані
раніше за узгоджену модель і міграції, лише закріплять це роздвоєння.

## 4. Мова статусів

Кожен етап і deliverable отримує один статус:

| Статус | Значення |
|---|---|
| `DONE` | Реалізація, тести, документація та критерії приймання підтверджені |
| `VERIFY` | Реалізація існує, але потрібна повторна або ширша перевірка |
| `PARTIAL` | Є робоча частина, але немає повного наскрізного контракту |
| `READY` | Вимоги й залежності достатні для початку окремої задачі |
| `BLOCKED_BY_DECISION` | Реалізація передчасна до погодження ADR або варіанта |
| `PLANNED` | Етап визначено, але його залежності ще не завершені |
| `SUPERSEDED` | Артефакт замінений новою версією та зберігається для історії |

Наявність файла, класу, кнопки або тестового fixture сама по собі не означає
`DONE`.

## 5. Рішення перед значною реалізацією

### 5.1. Уже встановлені межі

Наступні положення вже закріплені `AGENTS.md` і blueprint:

- VARTA є local-first системою;
- SQLite і файлове сховище є джерелом істини;
- оригінали незмінні;
- `map-data.json` є відтворюваним snapshot, а не другою БД;
- case-specific значення не потрапляють до універсального core;
- зовнішні інтеграції є необов’язковими adapters;
- автоматичний результат не підміняє ручне рішення;
- невизначеність не заповнюється вигаданими фактами.

### 5.2. Рекомендовані рішення для окремих ADR

| ID | Питання | Рекомендований варіант | Статус |
|---|---|---|---|
| `D-01` | Repository authority | SQLite є єдиним writable source of truth; XLSX — import/export compatibility adapter | `ESTABLISHED` |
| `D-02` | Міграції | Явні versioned `.sql` files, checksum, transaction і Python migration runner; без ORM у першому vertical slice | `ESTABLISHED` |
| `D-03` | Workspace | Одна локальна БД може містити багато справ; UI працює з нулем/однією active case за раз | `APPROVED` (`ADR-005`) |
| `D-04` | Ідентичність | Внутрішні opaque IDs не залежать від номера справи, імені чи шляху; external references зберігаються окремо | `ESTABLISHED` |
| `D-05` | Фізичне сховище | Оригінал адресується через `file_id`; користувацька назва є metadata/managed view | `ESTABLISHED` |
| `D-06` | Legacy state | Спочатку read-only importer `.caseflow`/XLSX, потім контрольована міграція до `.varta`; без мовчазного перейменування | `APPROVED` (`ADR-005`) |
| `D-07` | UI boundary | Local UI викликає application services; не читає SQLite та не реалізує domain rules напряму | `ESTABLISHED` |
| `D-08` | Rollback | Для data migrations rollback означає перевірене відновлення узгодженої backup-копії, а не destructive down migration | `APPROVED` (`ADR-003`) |
| `D-09` | Primary UI | Embedded browser UI працює тільки на explicit loopback; CLI є adapter | `APPROVED` (`ADR-001`) |
| `D-10` | Local HTTP security | Host/Origin/CSRF/CSP, no remote assets, no LAN без нового ADR | `APPROVED` (`ADR-006`) |
| `D-11` | SQLite/worker lifecycle | Short-lived UoW/connection per operation; workers без shared/direct repository connection | `APPROVED` (`ADR-007`) |
| `D-12` | Notion | Поза runtime, docs workflow, integrations і source of truth | `APPROVED` (`ADR-001`) |

`APPROVED` позначає чинну architecture boundary, але не проголошує її
реалізованою. `ESTABLISHED` позначає рішення, яке також має current
implementation evidence. Versioned archive/encryption/scale/recovery details
мають owner/gate у `architecture/open-questions.md`.

## 6. Алгоритм виконання кожної окремої зміни

Цей цикл є обов’язковим для кожної суттєвої функції або міграції.

### Крок 1. Сформулювати результат

Зафіксувати:

- проблему користувача;
- очікуваний результат;
- `scope` і `out of scope`;
- що не можна змінювати;
- видимий критерій успіху.

**Вихід:** короткий task contract без прихованого розширення scope.

### Крок 2. Перевірити фактичний baseline

Переглянути:

- `git status` і релевантний diff;
- чинний код, тести, конфігурацію, схеми та документацію;
- активний Python interpreter і editable install;
- реальні формати входу та виходу;
- наявні compatibility contracts.

Не починати з припущення, що README або roadmap актуальніший за код.

**Вихід:** перелік `confirmed`, `assumption`, `unknown`, `conflict`.

### Крок 3. Перевірити privacy та незмінність оригіналів

Визначити:

- чи торкається зміна матеріалів справи;
- чи створює копії, exports, logs або caches;
- чи може змінити/перемістити оригінал;
- чи містить приклад реальні реквізити;
- що має бути виключено з Git.

**Gate:** якщо безпечну межу не визначено, реалізація не починається.

### Крок 4. Застосувати decision gate

Перевірити, чи змінюється:

- джерело істини;
- схема БД або cardinality;
- публічний API/JSON contract;
- workspace layout;
- спосіб зберігання оригіналів;
- формат release/update/backup;
- зовнішня інтеграція.

Якщо так — створити або оновити ADR зі структурою:

```text
problem
context
options
decision
consequences
risks
migration
rollback
status
```

**Gate:** фізична реалізація не випереджає критичне рішення.

### Крок 5. Визначити контракти

До коду описати:

- вхідні та вихідні дані;
- domain invariants;
- ID і external references;
- статуси та помилки;
- provenance і audit events;
- schema/API version;
- backward compatibility;
- поведінку для `unknown`, conflict і повторного запуску.

**Вихід:** schema, typed interface або testable contract.

### Крок 6. Спроєктувати міграцію та відновлення

Для data/storage change визначити:

- поточний і цільовий стан;
- read path під час переходу;
- одноразовість або idempotency;
- backup до зміни;
- перевірку backup;
- rollback через restore;
- reconciliation report;
- заборону прихованого видалення.

**Gate:** migration без перевіреного відновлення не приймається.

### Крок 7. Скласти тестову матрицю

Перед реалізацією визначити мінімум:

- happy path;
- empty input;
- duplicate/retry;
- malformed input;
- Unicode і довгі Windows paths;
- interrupted operation;
- transaction rollback;
- restart/persistence;
- privacy-negative case;
- legacy compatibility, якщо вона заявлена.

### Крок 8. Реалізувати найменший наскрізний vertical slice

Перевага надається одному завершеному шляху:

```text
input -> application service -> SQLite/filesystem -> read-back -> UI/report
```

Не створювати багато паралельних scaffolds без перевіреного наскрізного
результату.

### Крок 9. Виконати технічну перевірку

Обов’язковий baseline:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy case_docket caseflow
.\.venv\Scripts\python.exe -m compileall -q case_docket caseflow scripts
git diff --check
```

Додатково виконуються integration, migration, restore, schema, UI або package
checks, які випливають зі scope.

### Крок 10. Перевірити результат як користувач

Статичний аналіз не замінює результат-state перевірку. Для UI, installer,
export або portable package перевірити фактичний запуск і видимий результат.

**Вихід:** доказ, який може повторити інша людина.

### Крок 11. Оновити документацію та статус

Оновити лише ті документи, факти в яких справді змінилися:

- ADR/change record;
- schema/API contract;
- `PROJECT_STATUS.md`;
- цей алгоритм або roadmap status;
- команди запуску;
- migration/rollback notes.

Не позначати етап `DONE` лише тому, що код написано.

### Крок 12. Виконати privacy/release gate і передати результат

Перед commit або push окремо перевірити:

- staged filenames і diff;
- заборонені типи файлів;
- case-specific номери, ПІБ, контакти, суми та абсолютні приватні шляхи;
- secrets, tokens, OAuth/DPAPI blobs;
- generated maps, DB, runtime state і logs;
- спосіб відновлення після зміни.

Commit, push, release або зовнішня публікація виконуються лише за явним
дорученням.

## 7. Послідовність розвитку продукту

### 7.1. Зведена карта

| Етап | Результат | Поточний стан | Залежність |
|---|---|---|---|
| `A0` | Підтверджений консолідований baseline | `DONE` | — |
| `A1` | Погоджені ADR для local web, repository, IDs, workspace, migrations і workers | `DONE` | `A0` |
| `A2` | Versioned SQLite schema та migration runner | `DDL/RUNNER DONE`, delivery gate `PARTIAL` | `A1` |
| `A3` | Immutable storage та intake vertical slice | `PARTIAL` | `A2` |
| `A4` | Визначення/підтвердження справи з першого документа | `READY` після `A3` | `A3` |
| `A5` | Domain-модель справ, документів, подій, claims і relations | `DDL/CONTRACT DONE`; repository/application flow `PARTIAL` | `A2`, `A4` |
| `A6` | Контрольований імпорт legacy XLSX/`.caseflow` | `PLANNED` | `A2`, `A5` |
| `A7` | Детермінована Evidence Map projection із SQLite | `BLOCKED_BY_DECISION` до repository API A5 | `A5` |
| `A8` | Integrated local UI поверх application services | `PARTIAL` | `A3`, `A5`, `A7` |
| `A9` | Sealed standalone export і validation package | `PARTIAL` | `A7` |
| `A10` | OCR, КЕП, matching, attachments, STT plugins | `PARTIAL`/scaffold | `A3`, `A5` |
| `A11` | Backup, restore, Windows package та update path | `PARTIAL` | `A2`, `A3`, `A8` |
| `A12` | Release gate і відтворюваний baseline | `PLANNED` | `A0`–`A11` |

### 7.2. Етап A0 — стабілізація baseline

**Мета:** відділити вже перевірений стан від незавершених локальних змін.

Дії:

1. інвентаризувати кожен змінений tracked-файл;
2. зіставити зміни з конкретною задачею;
3. повторити test/lint/type/compile checks;
4. перевірити runtime smoke test local server;
5. перевірити privacy scan;
6. не відкидати й не перезаписувати невідомі зміни;
7. за окремим дорученням створити контрольну Git-точку.

**Критерій завершення:** є однозначний перелік включених змін, усі gates
проходять, а стан можна відтворити без матеріалів реальної справи.

### 7.3. Етап A1 — рішення

**Мета:** перетворити критичні open questions на версійовані рішення.

Затверджений набір C02:

- `ADR-001`: local-first modular architecture, embedded local web, no Notion;
- `ADR-002`: SQLite authority і роль XLSX adapter;
- `ADR-003`: schema migrations, backup та restore;
- `ADR-004`: identifier strategy і cardinalities;
- `ADR-005`: workspace, immutable storage та `.caseflow`/`.varta` transition;
- `ADR-006`: loopback Host/Origin/CSRF/CSP security boundary;
- `ADR-007`: per-operation SQLite UoW та isolated workers.

Archive variants, encryption, target corpus scale і numeric recovery
objectives мають stable IDs, owner stages і closing gates у
`architecture/open-questions.md`; вони не блокують C03 contracts.

**Критерій завершення:** `DONE` — усі сім ADR мають `APPROVED`, context,
decision, rejected alternatives, consequences і migration impact;
technical spec/status/roadmap синхронізовані, а C03 не мусить приховано
обирати UI, DB, IDs, workspace, storage, connection або worker boundary.

### 7.4. Етап A2 — SQLite schema та migrations

**Мета:** замінити `_SCHEMA`-prototype контрольованою еволюцією БД.

**Поточний факт:** migration runner, checksums, транзакційне застосування,
заборона мовчазної зміни застосованої migration, fresh/failure tests і два
versioned SQL-файли вже існують. Етап залишається `PARTIAL`, бо ще немає
перевіреного backup/restore gate, а логічне розділення system/intake/case/
evidence migrations не доведене до цільової структури.

Checksum обчислюється з UTF-8 SQL після канонічного перетворення `CRLF`/`CR`
на `LF`. Тому Git line-ending policy або wheel build на Windows не змінюють
ідентичність уже застосованої migration; зміна самого SQL і далі блокується.

Рекомендована структура:

```text
migrations/
├── 0001_system.sql
├── 0002_intake.sql
├── 0003_case_model.sql
└── 0004_evidence_model.sql
```

Логічний склад:

- `0001_system`: `schema_migrations`, `audit_log`, `processing_runs`;
- `0002_intake`: intake context, `import_batches`, `files`, file hashes і
  provenance;
- `0003_case_model`: `cases`, `proceedings`, `documents`, `document_files`,
  actors та many-to-many membership;
- `0004_evidence_model`: `events`, `claims`, `relations`,
  `source_references`, review decisions і findings.

Обов’язково:

- checksum кожної застосованої migration;
- `PRAGMA foreign_keys = ON`;
- транзакція на одну migration;
- заборона редагування вже застосованої migration;
- fresh-database test;
- upgrade test із попередньої версії;
- failure rollback test;
- backup/restore test;
- жодного прихованого drop/delete.

**Критерій завершення:** нова й оновлена БД дають однакову schema version,
constraints реально спрацьовують, audit append-only, restore перевірено.

### 7.5. Етап A3 — immutable storage та intake

**Мета:** реалізувати перший справжній source-of-truth vertical slice.

Потік:

```text
file/folder/archive
  -> intake context
  -> streaming SHA-256
  -> immutable original storage
  -> SQLite file + provenance records
  -> duplicate signal
  -> inventory read-back
```

Обов’язкові властивості:

- джерело не змінюється;
- partial failure не приховує успішно прийняті файли;
- archive traversal і unsafe names блокуються;
- повторний запуск не створює мовчазних дублів;
- однаковий SHA-256 не означає автоматичне злиття ролей;
- оригінальна назва та source-relative path збережені;
- inventory відтворюється із SQLite після restart;
- UI/process не записує авторитетні дані лише в XLSX.

**Критерій завершення:** synthetic package прийнято, байти source й stored
original збігаються, provenance читається з БД, retry і failure paths
перевірені тестами.

### 7.6. Етап A4 — case bootstrap

**Мета:** приймати перший документ до відомого номера справи.

Алгоритм:

```text
first document
  -> temporary intake_case_id
  -> hash + provenance
  -> extraction
  -> case-number candidates
  -> normalization
  -> automatic confidence or manual_review_required
  -> locate/create case
  -> activate versioned case profile
```

Система зберігає raw value, normalized value, source location, confidence,
decision і actor/time. Назва файла або папки не є достатнім підтвердженням.

**Критерій завершення:** zero/one/multiple candidate tests, жоден документ не
втрачається через відсутність номера, неоднозначність не вирішується мовчки.

### 7.7. Етап A5 — domain та evidence model

**Мета:** реалізувати модель, достатню для timeline і доказової мапи.

**Поточний факт:** DDL і JSON contracts для claims, typed evidence relations,
source references, review decisions, amounts, processing runs та export records
створені й покриті schema/constraint tests. Це `DDL/CONTRACT DONE`, але не
означає завершений repository API або application flow.

Ключові правила:

- `file` і `document` є різними сутностями;
- документ/подія можуть належати кільком справам і провадженням;
- роль membership зберігається у linking record;
- `claim` не підміняється статусом цілого документа;
- relation має type, direction, evidence basis, classification і review;
- automatic classification і user decision зберігаються окремо;
- confirmed relation без source reference не допускається.

**Критерій завершення:** constraints і integration tests покривають
many-to-many, claims, typed relations, source references та audit history;
repository/application services читають і змінюють ці сутності без прямого
SQL у handlers, а один synthetic case проходить до Evidence Map projection.

### 7.8. Етап A6 — legacy compatibility adapter

**Мета:** перенести корисний стан без проголошення XLSX другою БД.

Дії:

1. read-only inventory legacy XLSX/`.caseflow`;
2. schema mapping із явними unsupported/conflict полями;
3. dry-run report без запису;
4. backup;
5. idempotent import до SQLite;
6. reconciliation counts і hashes;
7. quarantine/manual review для конфліктів;
8. лише після перевірки — переключення authoritative read path.

**Критерій завершення:** повторний import не дублює записи, reconciliation
пояснює кожне пропущене/конфліктне значення, legacy source не змінено.

### 7.9. Етап A7 — Evidence Map projection

**Мета:** формувати `map-data.json` тільки з авторитетного стану.

Projection service:

1. приймає `case_id` і profile version;
2. читає пов’язані proceedings/documents/events/claims/relations;
3. застосовує правила key-node selection;
4. перевіряє referential integrity;
5. детерміновано сортує масиви й поля;
6. формує inventory і exclusions;
7. валідує JSON Schema;
8. обчислює snapshot SHA-256;
9. не записує результат назад як ручний реєстр.

**Критерій завершення:** однаковий input revision дає однаковий canonical
snapshot hash; broken references і unsupported classifications блокують
позначення export як valid.

### 7.10. Етап A8 — integrated local UI

**Мета:** під’єднати наявну в’юху до application services без domain logic у
handler або JavaScript.

Мінімальні поверхні:

- intake/inventory;
- case selection і manual review queue;
- documents/tree;
- timeline;
- Evidence Map;
- source details/provenance;
- findings і review decisions;
- export status.

Навігація зберігає `case_id`, за наявності `proceeding_id`, `document_id`,
`event_id` і `returnTo`.

**Критерій завершення:** browser/runtime smoke tests доводять upload,
persistence після restart, відкриття source context і збереження review.

### 7.11. Етап A9 — sealed standalone export

**Мета:** створити перевірюваний read-only пакет без сервера й мережі.

Склад:

```text
exports/<export_id>/
├── index.html
├── map-data.json
├── manifest.json
└── validation-report.json
```

Вимоги:

- без CDN, external fonts, `fetch`, XHR, WebSocket і service worker;
- export ID, versions, profile, generated time і snapshot hash;
- `full_local`, `redacted`, `metadata_only` як явні режими;
- `full_local` лише після явного вибору та попередження;
- export не створює ілюзію запису до VARTA;
- offline browser test і network-request assertion.

### 7.12. Етап A10 — processors

OCR, КЕП, matching, attachment validation і STT реалізуються після стабільного
intake/files/processing-run contract. Кожен processor:

- є adapter/plugin;
- має versioned parameters;
- не змінює original;
- створює derived artifact або structured finding;
- зберігає provenance, confidence і error;
- підтримує `not_available`/`not_verifiable` без маскування;
- має synthetic fixtures і failure tests.

### 7.13. Етап A11 — backup, restore і Windows delivery

Packaging не приймається без перевіреного data lifecycle:

1. consistent SQLite + filesystem backup;
2. checksum manifest;
3. restore у новий каталог;
4. integrity verification;
5. migration preflight;
6. rollback instructions;
7. offline dependency check;
8. packaged runtime smoke test;
9. install/update/uninstall без видалення user data.

### 7.14. Етап A12 — release gate

Release candidate допускається лише коли:

- усі включені етапи мають `DONE` або явно задокументований partial scope;
- schema і product versions узгоджені;
- tests/lint/types/compile проходять;
- fresh install, restart, backup/restore і upgrade перевірені;
- privacy scan і staged diff чисті;
- release archive створено з контрольованого staging з нуля;
- фактичні archive entries перевірені;
- відомі обмеження не приховані;
- commit/push/release явно дозволені.

## 8. Черговість найближчих робіт

Безпечний порядок після реалізації Airtable-to-SQL baseline:

1. зафіксувати окремим ADR уже встановлені SQLite authority та migrations;
2. погодити workspace і backup/restore decisions, що залишилися;
3. імпортувати контрольований synthetic або авторизований snapshot і звірити
   counts, unresolved links та read-back після restart;
4. реалізувати `A3` як один intake vertical slice;
5. після цього під’єднувати case bootstrap і Evidence Map generator до SQLite.

Реалізований у цьому baseline foundation patch:

```text
SQLite migration runner
  + 0001_airtable_sql.sql
  + 0002_evidence_map_domain.sql
  + fresh/upgrade/failure/checksum tests
  + Airtable catalog та two-pass importer
  + Evidence Map schema 1.1.0 contracts
```

Він створює основу для наступних змін, але не переносить матеріали справи,
не містить Airtable credentials і не змінює legacy sources. Backup/restore
proof, Evidence Map repository services і SQLite-to-map projection залишаються
окремими gates.

### 8.1. Exact scope логічних P0 patches

Наведені scopes є послідовними: кожен наступний patch перевіряється поверх
попередніх. Файли з кількома незалежними змінами не можна додавати цілим
`git add`; для них потрібен hunk-level staging і перевірка наведених anchors.

| Patch | Exact scope | Мінімальна перевірка staged snapshot |
|---|---|---|
| `P0-1 migrations + repository` | `case_docket/repository/migrations.py`; `case_docket/repository/migrations/0001_airtable_sql.sql`; `case_docket/repository/__init__.py`; у `sqlite_repository.py` — `MigrationRunner`, constructor/bootstrap, legacy-table preservation і generic compatibility CRUD | наявні 59 tests, `tests/test_repository.py`, fresh DB, migration checksum/scheme smoke, `git diff --cached --check` |
| `P0-2 Airtable mapping/import` | `case_docket/airtable.py`; `config/airtable_schema.json`; `docs/airtable-sql-migration.md`; у `sqlite_repository.py` — catalog install, `import_airtable_snapshot()` і `airtable_catalog_counts()`; `tests/test_airtable_sql.py` з migration/import/catalog/legacy tests | 67 tests, schema counts `9/127/38/12`, repeated import, unresolved-link report, rollback та LF/CRLF checksum identity |
| `P0-3 contacts model/API/UI` | `case_docket/models/contact.py`; `case_docket/models/__init__.py`; у `sqlite_repository.py` — contact CRUD/context/roles/validation; у `caseflow/server.py` — repository property, contact routes/handlers і status counts; contact hunks у `caseflow/static/index.html`, `app.js`, `app.css`; contact hunks у `tests/test_models.py` і Airtable integration test | model/repository tests, API smoke, browser/runtime contact create-edit-role-readback |
| `P0-4 Evidence Map domain schema` | `case_docket/repository/migrations/0002_evidence_map_domain.sql`; `config/schemas/case-profile.schema.json`; `config/schemas/map-data.schema.json`; case/Evidence Map templates; `caseflow/static/legal-case-map.html`; `docs/blueprints/evidence-map-blueprint.md`; `docs/changes/VARTA-001-evidence-map-schema-1.1.md`; `tests/test_evidence_map_domain.py`; Evidence Map hunks у `tests/test_templates.py` та migration-count hunk у `tests/test_airtable_sql.py` | 77 tests, DDL/constraint tests, JSON Schema meta-validation, template/embedded-payload validation; статус не вище `DDL/CONTRACT DONE` |
| `P0-5 documentation + statuses` | `AGENTS.md`; `README.md`; `PROJECT_STATUS.md`; `docs/INDEX.md`; `docs/action-algorithm.md`; `docs/interactive/varta-action-map.html`; `docs/source-inventory.md` | відсутні застарілі test-count claims і хибна теза про відсутні Evidence tables; Markdown/HTML markers синхронні; privacy/network-asset scan |
| `P0-6 Windows packaging + typing gate` | package-data/dev-type hunks у `pyproject.toml`; `tools/windows/build_caseflow_exe.ps1`; frozen-worker/type hunks у `caseflow/server.py`, `caseflow/caseflow_process.py`, `caseflow/anomaly_detector.py`; відповідні typing regression hunks у `tests/test_server_helpers.py` | mypy, Ruff, compileall, PowerShell parser, clean PyInstaller build; archive/EXE містить SQL migrations, Airtable schema і hidden worker modules |

Окремо зафіксовано **`HOLD-1 multipart upload`**: `MultipartStream`,
`multipart_boundary()`, `parse_multipart_form()`, streaming `handle_upload()` у
`caseflow/server.py` та `MultipartFormTests` у `tests/test_server_helpers.py`.
Це корисна, але стороння до шести P0 scopes зміна: вона має власний
двофайловий commit, окремий staged diff і два targeted tests; після неї повний
baseline має 82 tests. Вона не домішана до contacts, repository або packaging.

Окремо виключені з P0 як зовнішня пара: `docs/chat-roadmap.md` і
`docs/interactive/varta-chat-roadmap.html`. Їхній зміст та статус визначаються
іншою задачею; цей baseline їх не змінює і не включає до staging.

Для кожного patch exact scope підтверджено щонайменше командами
`git diff --cached --name-status`, `git diff --cached --stat`,
`git diff --cached --check` і переглядом `git diff --cached`. Повний acceptance
виконано з clean checkout, а не з ширшого working tree.

## 9. Картка зміни

Для кожної наступної задачі створюється коротка картка:

```yaml
change_id: VARTA-XXX
title:
status: PROPOSED
objective:
scope: []
out_of_scope: []
source_of_truth:
affected_contracts: []
privacy_impact:
originals_impact: none
decision_dependencies: []
migration:
rollback:
tests: []
acceptance: []
evidence: []
known_limits: []
```

Картка не повинна містити реальні матеріали справи, ПІБ, контакти, суми,
секрети або приватні абсолютні шляхи.

## 10. Умова затвердження документа

Документ можна перевести з `PROPOSED` до `APPROVED`, коли погоджено:

1. пріоритет SQLite над XLSX як writable source of truth;
2. versioned SQL migrations без ORM у першому vertical slice або інший
   обґрунтований варіант;
3. multi-case database з однією active case у UI або іншу workspace model;
4. internal ID strategy;
5. backup/restore як обов’язковий migration gate;
6. наведений порядок `A0 -> A1 -> A2 -> A3` до робіт над повним generator/UI.

До погодження документ уже може використовуватися для аудиту й підготовки
ADR, але не як автоматичний дозвіл на всю програму змін.

Інтерактивна карта є companion view цього документа, а не окремим джерелом
істини. Статуси, порядок або gate змінюються в Markdown і HTML одним patch;
за розбіжності канонічним є цей Markdown-документ.
