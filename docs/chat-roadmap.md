# Roadmap виконання VARTA окремими чатами

**Тип документа:** канонічна декомпозиція робіт на самодостатні задачі для
окремих чатів Codex у проєкті VARTA

**Версія:** 1.2

**Дата базової оцінки:** 18.08.2026

**Статус:** `ACTIVE`

**Продуктова основа:** [`action-algorithm.md`](action-algorithm.md) залишається
джерелом продуктових етапів `A0`–`A12`. Цей документ не замінює його, а
перетворює на послідовність окремих chat work packages `C01`–`C16`.

**Розкривна карта:**
[`interactive/varta-chat-roadmap.html`](interactive/varta-chat-roadmap.html).
Markdown є авторитетним у разі розбіжності.

## 1. Зафіксована цільова межа

VARTA є локальним Windows-застосунком із таким основним контуром:

```text
browser на 127.0.0.1
  -> versioned local HTTP API
  -> application services
  -> SQLite + контрольоване файлове сховище
  -> ізольовані локальні workers для важкої обробки
  -> відтворювані projections, reports і sealed exports
```

Notion не входить до runtime, core, інтеграцій або джерел істини. Канонічні
вимоги й рішення зберігаються в Markdown/ADR у `D:\VARTA`. Зовнішні сервіси,
якщо вони залишаються, є лише вимкненими за замовчуванням optional adapters.

Локальний web UI:

- слухає тільки loopback;
- не читає SQLite або матеріали справи напряму;
- не містить domain rules у JavaScript;
- викликає ті самі application services, що CLI, workers і майбутні adapters;
- не перетворює JSON, XLSX або HTML snapshot на другу редаговану базу даних.

## 2. Точка старту: що є зараз

### 2.1. Перевірений живий baseline

На старті C02 controller підтвердив:

```text
branch                  codex/stabilize-baseline
HEAD                    c3a5b122894e81aff2d82078df7e38e5659d3733
tracked working changes 0
staged diff files       0
untracked files         0
pytest                  94 passed (C01 evidence)
roadmap tests           12 passed (Git checkpoint state-machine subset)
local index             HTTP 200, text/html, VARTA marker present
SQLite runtime          database created in a synthetic workspace
restart persistence     synthetic contact survived a full server restart
temporary smoke data    removed after verification
```

Commit `c3a5b12` є відтворюваним C01 baseline: roadmap/controller і два
класифіковані `.github` guidance-файли tracked, working tree чистий. C02
почався тільки після окремого `GITHUB SYNCED`. C02 не виконує `git add`,
commit, push, publication, release або remote changes.

### 2.2. Реально наявні компоненти

- Python 3.12 package `varta` з CLI entry point `caseflow.server:main`;
- локальний `ThreadingHTTPServer`, статичний HTML/CSS/JavaScript і loopback
  restriction;
- CSRF-like token для mutating HTTP requests, CSP та path traversal checks;
- versioned SQLite migration runner із checksum і транзакційним застосуванням;
- migrations `0001_airtable_sql.sql` і `0002_evidence_map_domain.sql`;
- `PRAGMA foreign_keys = ON`, WAL, append-only audit triggers;
- repository/API/UI vertical slice для контактів;
- DDL та JSON contracts для case profile, files, processing runs, claims,
  evidence relations, source references, review decisions і exports;
- upload, preflight, legacy XLSX-oriented processing та anomaly detector;
- Evidence Map HTML view із snapshot/embedded JSON;
- scaffolds для OCR, КЕП і STT plugins;
- Windows build/install/start/update tooling;
- privacy-safe synthetic tests і шаблони.

### 2.3. Головні незавершені межі

- `caseflow` pipeline продовжує записувати authoritative-looking XLSX/JSON/
  `.caseflow` state, тоді як новий core декларує SQLite джерелом істини;
- окремого `application` layer ще немає;
- `caseflow/server.py` одночасно виконує HTTP routing, validation, filesystem
  operations, integrations і частину business rules;
- upload до `00_INBOX` ще не є immutable intake з `import_batch`, SHA-256,
  provenance та read-back із SQLite;
- немає повних repository/application services для evidence domain;
- немає детермінованого SQLite -> Evidence Map generator;
- manual review і частина operational state зберігаються в JSON;
- немає доведеного consistent backup/restore для SQLite разом із файлами;
- Windows package/update path ще не доведений на clean controlled snapshot;
- `ADR-001`–`ADR-007` і technical specification тепер approved, але target
  application/storage/security/worker boundaries ще не перенесено в код.

## 3. Як використовувати roadmap

### 3.1. Один work package — один постійний чат

Для кожного package `Cxx` controller створює рівно один постійний Codex
task/chat. Повторний запуск після blocker, помилки або interruption, а також
GitHub checkpoint є новими turns у цьому самому чаті й не створюють дублікати.
Чат не починає наступний package через те, що залишився час або контекст. Якщо
виявлено blocker, він документує його, виконує всі безпечні перевірки у своєму
scope і передає handoff, не маскуючи `PARTIAL` як `DONE`.

### 3.2. Обов'язковий старт кожного чату

1. Прочитати `AGENTS.md`, `PROJECT_STATUS.md`, `docs/action-algorithm.md` і цей
   roadmap.
2. Виконати `git status --short --branch` і зафіксувати, які зміни існували до
   початку чату.
3. Перевірити prerequisite/gate свого package за фактичним кодом, а не лише за
   статусом у документації.
4. Назвати exact scope, файли й тести, які планується змінити.
5. Не змінювати read-only джерела міграції, матеріали справ і
   `D:\CMSD\offline_bundle`.

### 3.3. Обов'язкове завершення кожного чату

Кожен чат передає:

- короткий outcome-first підсумок;
- список реально змінених файлів;
- окремо: що реалізовано, що лише спроєктовано, що не виконано;
- точні команди й результати tests/lint/types/runtime checks;
- відомі ризики та open questions;
- поточний `git status`;
- transition gate: `PASS`, `PARTIAL` або `BLOCKED`;
- готовий handoff для наступного package.

Звичайний stage task не виконує commit, push, PR, release або remote changes.
Після технічного `PASS` користувач окремо натискає **GitHub checkpoint**; саме
ця підтверджена дія є вузькою прямою командою на audit, exact staging, commit,
push у приватну `codex/*` branch і створення/оновлення Draft PR. Merge, tag,
release, force-push і зміна visibility цим не дозволяються.

### 3.4. Двофазний stage gate

Кожний package проходить дві незалежно доказові фази:

```text
TECH RUN
  -> structured VARTA_STAGE_RESULT
  -> TECH PASS
  -> очікування окремого підтвердження користувача
  -> GIT AUDIT
  -> exact staging
  -> local commit
  -> push origin/codex/*
  -> Draft PR до main
  -> GITHUB SYNCED
  -> розблокування залежного package
```

`TECH PASS` означає, що scope і тести етапу пройдені, але GitHub ще не
оновлено. `GITHUB SYNCED` означає, що controller отримав валідний
`VARTA_GIT_RESULT`: repository повторно підтверджено як `PRIVATE`, commit є на
`origin`, branch має префікс `codex/`, а Draft PR існує. Локальний commit без
push, push без перевірки remote або PR без підтвердженого commit не є synced.
Controller не покладається лише на звіт Git turn: він read-only повторно
звіряє local HEAD, `ls-remote`, private repository metadata і Draft PR head SHA.

### 3.5. Статуси

| Статус                | Значення                                                   |
| --------------------- | ---------------------------------------------------------- |
| `READY`               | package можна починати з поточного підтвердженого стану    |
| `PARTIAL`             | частина реалізації є, але end-to-end gate не пройдено      |
| `PLANNED`             | scope визначено, але prerequisite ще не завершено          |
| `BLOCKED_BY_DECISION` | код передчасний до формального ADR/вибору                  |
| `DONE`                | scope, tests, runtime evidence і документація підтверджені |

### 3.6. Керовані кнопки й автоматичний status

Для живого режиму запустити `START_ROADMAP.cmd` у корені `D:\VARTA` і
відкрити `http://127.0.0.1:8766/`. У кожному package з'являються кнопки:

- **Створити чат і почати Cxx** — для першої спроби створити єдиний Codex
  thread package; якщо Task ID вже існує, **Продовжити в цьому чаті** запускає
  новий turn у ньому без нового чату;
- **Зупинити turn** — штатно перервати активне виконання;
- **Скопіювати повний prompt** — отримати canonical machine prompt;
- **Скопіювати Task ID** — звірити створений task у Codex project history.
- **GitHub checkpoint у цьому чаті** — після `TECH PASS` запустити новий turn у
  постійному package chat для privacy/ownership audit, exact staging, commit,
  push і Draft PR;
- **Зупинити Git turn** — штатно перервати Git checkpoint без підміни status.

Над картками постійно показуються активний package, повний Task ID, поточна
фаза, повідомлення, журнал контрольних подій та відсоток. Відсоток означає
підтверджені checkpoints, а не прогноз часу: agent може звітувати лише `1`–`99`
у package-scoped `VARTA_PROGRESS`, а `100%` controller виставляє тільки після
валідного `VARTA_STAGE_RESULT` або `VARTA_GIT_RESULT`. Loopback UI оновлює ці
дані щосекунди.

Planning status (`READY/PARTIAL/PLANNED/BLOCKED_BY_DECISION`) не
перезаписується execution status. Окремо відображаються `not_started`,
`starting`, `running`, `waiting`, `completed`, `blocked`, `failed`,
`interrupted` і `needs_review`. Git lifecycle відображається окремо:
`not_ready`, `awaiting_approval`, `starting`, `running`, `waiting`, `synced`,
`blocked`, `failed`, `interrupted`, `needs_review`.

Залежності повторно перевіряє localhost server. Наступний package не
розблоковується лише тому, що Codex завершив генерацію: потрібен валідний
structured result, фактичні tests і `outcome=passed`; після цього prerequisite
вважається виконаним лише за `GITHUB SYNCED`. Одночасно в спільному `D:\VARTA`
запускається лише один stage або Git turn. Детальний operation/security
contract: `docs/roadmap-controller.md`.

## 4. Карта чатів і залежностей

| ID    | Тема нового чату                                             | Product stage          | Поточний стан         | Prerequisite                          |
| ----- | ------------------------------------------------------------ | ---------------------- | --------------------- | ------------------------------------- |
| `C01` | Підготувати поточні напрацювання до контрольованого baseline | `A0`                   | `DONE`                | —                                     |
| `C02` | Затвердити цільову local-web архітектуру та ADR-пакет        | `A1`                   | `DONE`                | `C01`                                 |
| `C03` | Створити application layer і versioned API boundary          | `A1` , foundation `A8` | `READY`               | `C02`                                 |
| `C04` | Завершити SQLite lifecycle, Unit of Work і migration gates   | `A2`                   | `PARTIAL`             | `C03`                                 |
| `C05` | Реалізувати managed storage та immutable originals           | `A3`                   | `PARTIAL`             | `C02` , `C04`                         |
| `C06` | Реалізувати intake vertical slice до SQLite                  | `A3`                   | `PARTIAL`             | `C05`                                 |
| `C07` | Реалізувати workspace, case bootstrap та active case         | `A4`                   | `PLANNED`             | `C06`                                 |
| `C08` | Завершити evidence-domain services і invariants              | `A5`                   | `PARTIAL`             | `C04` , `C07`                         |
| `C09` | Побудувати read-only legacy XLSX/.caseflow adapter           | `A6`                   | `PLANNED`             | `C08`                                 |
| `C10` | Запровадити durable processing jobs і plugin contract        | foundation `A10`       | `PARTIAL`             | `C06` , `C08`                         |
| `C11` | Побудувати детерміновану Evidence Map projection             | `A7`                   | `BLOCKED_BY_DECISION` | `C08`                                 |
| `C12` | Перевести local web UI на application services               | `A8`                   | `PARTIAL`             | `C03` , `C06` , `C07` , `C08` , `C11` |
| `C13` | Завершити review, timeline і source-context workflow         | `A8`                   | `PLANNED`             | `C12`                                 |
| `C14` | Створити sealed standalone export і validator                | `A9`                   | `PARTIAL`             | `C11` , `C13`                         |
| `C15` | Довести backup/restore, Windows package та update path       | `A11`                  | `PARTIAL`             | `C04` , `C05` , `C12` , `C14`         |
| `C16` | Провести acceptance, privacy та release gate                 | `A12`                  | `PLANNED`             | `C01` –`C15`                          |

Основний критичний шлях:

```text
C01 -> C02 -> C03 -> C04 -> C05 -> C06 -> C07 -> C08
     -> C11 -> C12 -> C13 -> C14 -> C15 -> C16
```

`C09` і `C10` починаються лише після своїх gates. Спеціалізовані processor
чати `P01`–`P04` можуть виконуватися паралельно після `C10`, якщо вони не
редагують спільні контракти без координації.

## 5. Детальні chat work packages

## Stage 1 / C01 — Підготувати поточні напрацювання до контрольованого baseline

**Тема нового чату:** `VARTA C01 — стабілізація поточного working baseline`

**Статус:** `DONE` — C01 Git baseline `c3a5b12` синхронізовано до старту C02.

**Мета:** перетворити працездатний, але змішаний working tree на повністю
інвентаризований набір логічних patches, не втративши жодної наявної зміни.

### Що є на цей момент

- `codex/stabilize-baseline`, HEAD
  `bc51a0095adb664c9bebd98764c101976f75e575`;
- 0 tracked working changes, 0 staged files і 14 untracked files, включно з
  roadmap/controller та окремим `.github/` scope;
- попередній staging intent не припускається; `.github/` не приписується
  roadmap без окремої ownership-класифікації;
- migration runner, SQL migrations, Airtable catalog/importer, contacts flow,
  Evidence Map contracts і UI changes існують в одному незавершеному стані;
- 12 targeted roadmap-controller tests і повний suite `94 passed` пройдено
  після додавання Git state machine; gates повторюються перед checkpoint;
- commit/push цього стану не виконано й цим package не дозволяється.

### Що треба зробити

1. Зняти повний inventory `git status`, `git diff --stat`,
   `git diff --cached --stat`, untracked file list, index metadata і поточні
   hashes важливих документів.
2. Для кожного зміненого файла визначити власника логічного patch:
   baseline/docs, typing/runtime, Airtable-to-SQL, Evidence Map contracts,
   contacts/API/UI, Windows packaging або інше.
3. Виявити файли з кількома незалежними змінами; реконструювати логічний, а не
   історично припущений staging plan і не виконувати масове `git add .`.
4. Перевірити, що всі runtime loaders мають відповідні package-data files,
   особливо versioned SQL і `config/airtable_schema.json`.
5. Запустити повні gates: pytest, Ruff, mypy, compileall, `git diff --check` і
   `git diff --cached --check`.
6. Виконати privacy scan tracked, staged і untracked text: case materials,
   реальні номери, персональні/банківські дані, OAuth, DPAPI, private keys,
   SQLite/XLSX/PDF/DOCX/P7S/archives.
7. Повторити synthetic local-server smoke: page 200, API ready, SQLite create,
   write/read після restart, cleanup temp workspace.
8. Створити або оновити change records для кожного логічного patch і таблицю
   exact files/tests/evidence.
9. Після технічного `PASS` зупинитися на перевіреному staging plan. Лише окреме
   натискання **GitHub checkpoint** запускає новий turn у цьому самому C01
   task; він має показати exact staged snapshot, виконати commit/push у
   `codex/*` і створити Draft PR.

### Який результат отримаємо

- жодна наявна зміна не втрачена й не приписана неправильному patch;
- є точний порядок інтеграції поточних напрацювань;
- SQL migrations, loaders, tests і docs входять до узгоджених logical sets;
- baseline можна повторно перевірити без матеріалів справи;
- `C02` отримує стабільний і зрозумілий вхід.

### Як перевірити

- `python -m pytest -q`;
- `python -m ruff check case_docket caseflow tests`;
- `python -m mypy case_docket caseflow`;
- `python -m compileall -q case_docket caseflow`;
- `git diff --check` і `git diff --cached --check`;
- staged/untracked privacy scan із записаними patterns та zero/triaged findings;
- synthetic HTTP/SQLite restart smoke;
- ручна звірка: кожен status path присутній рівно в одному patch manifest.

**Transition gate:** `TECH PASS`, коли inventory повний, gates зелені, privacy
findings пояснені, а Git turn не мусить вгадувати походження змін. `C02`
розблоковується тільки після окремого `GITHUB SYNCED` для C01.

**Стартовий запит для нового чату:**

> Виконай тільки package C01 з `docs/chat-roadmap.md`. Інвентаризуй і
> стабілізуй поточний dirty working tree VARTA без видалення, reset, commit або
> push. Результат — точні logical patch manifests, повні quality/privacy gates,
> runtime smoke і handoff для C02.

## Stage 2 / C02 — Затвердити цільову local-web архітектуру та ADR-пакет

**Тема нового чату:** `VARTA C02 — local web, source of truth і ключові ADR`

**Статус:** `DONE` — architecture/spec/status package синхронізовано
18.08.2026; product code у C02 не рефакторився.

### Що підтверджено C02

- `ADR-001`–`ADR-007` мають `APPROVED` і повний decision format;
- embedded local web UI працює лише на explicit loopback; Notion поза
  продуктом/documentation workflow/source of truth;
- SQLite є єдиним writable structured source of truth, managed filesystem —
  authority для registered bytes;
- UI/HTTP/CLI/workers спрямовані через application services;
- one multi-case DB, zero/one active UI case і `.varta` target затверджені;
- connection model — short-lived UoW per operation, без shared worker DB;
- поточний код ще має legacy direct paths; це чесно залишено C03+.

### Виконаний scope

1. Оновлено/затверджено `ADR-001`: modular local-first Python application,
   embedded local HTTP API, browser UI, SQLite, managed filesystem і isolated
   workers; Notion не входить до системи.
2. Зафіксовано `ADR-002`: SQLite — єдине writable structured source of truth;
   XLSX/JSON/HTML — import/export/projection artifacts.
3. Зафіксовано `ADR-003`: forward-only versioned migrations, checksum,
   consistent backup/restore замість destructive down migrations.
4. Зафіксовано `ADR-004`: opaque internal IDs, external references окремо,
   many-to-many cardinalities і stable identity незалежно від шляхів/імен.
5. Зафіксовано `ADR-005`: одна локальна БД може містити багато справ; UI має
   одну active case; managed storage zones; контрольований `.caseflow` ->
   `.varta` transition.
6. Додано `ADR-006` local HTTP security boundary: loopback only, Host/Origin checks,
   CSRF token, CSP, no remote assets by default, no LAN mode без нового ADR.
7. `ADR-007` затвердив Unit of Work/connection per operation; global shared
   connection і direct worker repository відхилені.
8. `OQ-C02-001`–`004` версіонують archive/encryption/scale/recovery details із
   owner `C06`/`C15`/`C16` і concrete closing gates.
9. Синхронізовано technical specification, architecture decision log,
   `PROJECT_STATUS.md`, action algorithm і обидва roadmap companion без
   проголошення коду завершеним.

### Який результат отримаємо

- одна несуперечлива target architecture;
- формальна відповідь, де закінчується UI і починаються application services;
- відсутність Notion і роль optional integrations однозначні;
- усі наступні чати отримують стабільні dependency directions;
- framework choice не підміняє архітектуру: stdlib HTTP можна зберегти, доки
  measurable need не обґрунтує FastAPI/іншу заміну.

### Як перевірити

- ADR мають status, context, decision, rejected alternatives, consequences і
  migration impact;
- terminology/source-of-truth scan не знаходить суперечливих тверджень;
- architecture dependency test/scan підтверджує, що planned UI не імпортує
  repository напряму;
- усі open questions мають owner stage, а не залишаються безстроковими;
- docs links і Markdown lint/static checks проходять.

**Transition gate:** `PASS` — `C03` може створити application contracts без
прихованих рішень про UI, DB, IDs, workspace, storage, connection чи workers.
Controller dependency переходить далі лише після окремого `GITHUB SYNCED`.

**Стартовий запит:**

> Виконай тільки C02. Формалізуй обрану архітектуру VARTA: без Notion,
> local web UI на loopback, SQLite + managed filesystem як source of truth,
> application-service boundary і isolated workers. Підготуй/синхронізуй ADR та
> покажи всі рішення, альтернативи й open questions. Не починай refactor коду.

## Stage 3 / C03 — Створити application layer і versioned API boundary

**Тема нового чату:** `VARTA C03 — application services, ports і local API v1`

**Статус:** `READY` після C02 architecture gate; controller ще вимагає
окремий C02 `GITHUB SYNCED`.

### Що є на цей момент

- contacts уже проходять SQLite -> repository -> HTTP API -> UI;
- `caseflow/server.py` має близько 1750 рядків і поєднує routing, validation,
  file operations, workers, OAuth та domain-adjacent rules;
- окремого `case_docket/application` package немає;
- JavaScript викликає unversioned `/api/...` і містить presentation state;
- repository та plugins уже дають основу для ports/adapters.

### Що треба зробити

1. Додати `case_docket/application/` із чіткими commands, queries, DTOs,
   service errors і ports.
2. Визначити Unit of Work contract, repository ports, storage port, job port,
   clock/ID providers і transaction boundary.
3. Обрати один малий proof slice — contacts або status — і перенести business
   operation з handler до application service без зміни поведінки UI.
4. Запровадити versioned `/api/v1` contract і стабільний error envelope;
   тимчасові compatibility routes мають бути явними adapters.
5. Відокремити request validation від domain validation; не передавати raw JSON
   у repository.
6. Заборонити прямі імпорти infrastructure з domain/application за допомогою
   architecture test.
7. Зберегти stdlib local HTTP server на цьому етапі, якщо немає окремого ADR на
   replatforming; спочатку виправити boundaries.
8. Описати contract/versioning policy та приклади privacy-safe payloads.

### Який результат отримаємо

- HTTP, CLI й workers мають єдині use cases;
- handlers стають transport adapters;
- domain rules тестуються без запуску браузера/сервера;
- наступні intake/evidence/UI зміни не прив'язуються до legacy handler code.

### Як перевірити

- unit tests commands/queries із fake ports;
- integration test application service + real temporary SQLite;
- HTTP contract tests status/success/validation/conflict/not-found;
- architecture test на заборонені imports;
- existing contacts UI/API regression і restart persistence smoke;
- full pytest/Ruff/mypy/compileall.

**Transition gate:** `PASS`, коли хоча б один реальний vertical slice проходить
через application layer, а шаблон придатний для `C04`–`C08`.

**Стартовий запит:**

> Виконай C03 після перевірки gate C02. Створи мінімальний application layer,
> ports/Unit of Work та `/api/v1` contract, перенісши один існуючий vertical
> slice без зміни UX. Додай architecture, unit, integration і HTTP contract
> tests. Не мігруй intake або Evidence Map у цьому чаті.

## Stage 4 / C04 — Завершити SQLite lifecycle, Unit of Work і migration gates

**Тема нового чату:** `VARTA C04 — SQLite transactions, migrations і recovery foundation`

**Статус:** `PARTIAL`

### Що є на цей момент

- migration discovery, checksum і transactional apply реалізовані;
- `0001`/`0002`, foreign keys, WAL та append-only audit tests існують;
- repository використовує shared connection із `check_same_thread=False`, а
  HTTP layer серіалізує частину викликів `RLock`;
- немає завершеного Unit of Work, busy policy, consistent backup proof або
  tested connection lifecycle для workers/parallel reads.

### Що треба зробити

1. Реалізувати ADR connection/UoW model із явним begin/commit/rollback.
2. Увімкнути й перевірити `foreign_keys`, `busy_timeout`, WAL/checkpoint policy
   для кожного connection lifecycle.
3. Заборонити workers прямий shared DB connection; результати повертаються
   application service або через versioned result manifest.
4. Розділити/додати migrations для system, intake, case й evidence лише
   forward-only additive changes; не редагувати вже застосовані файли.
5. Додати schema compatibility check, application schema floor/ceiling і
   зрозумілу помилку для newer/invalid DB.
6. Реалізувати SQLite online backup primitive й integrity verification як
   foundation; повний filesystem bundle завершується в `C15`.
7. Додати crash/failure tests і migration from previous fixture.

### Який результат отримаємо

- передбачувані транзакції для application services;
- контрольована конкуренція одного локального користувача та workers;
- schema evolution і restore foundation, на яку безпечно спирається storage;
- жодна applied migration не змінюється мовчки.

### Як перевірити

- fresh DB, upgrade DB, checksum mismatch, failed migration rollback;
- foreign-key and append-only negative tests;
- concurrent reader/single-writer test із bounded busy behavior;
- application transaction rollback при audit/storage failure;
- SQLite backup -> restore -> `integrity_check` -> read-back;
- packaged resource test: усі SQL files доступні після install/build.

**Transition gate:** `PASS`, коли transaction і migration behavior однакові в
source checkout та installed package.

**Стартовий запит:**

> Виконай тільки C04. Заверши SQLite connection/UoW lifecycle, migration gates,
> schema compatibility і online-backup primitive. Не реалізуй filesystem
> originals або UI. Доведи fresh/upgrade/failure/concurrency/restore tests.

## Stage 5 / C05 — Реалізувати managed storage та immutable originals

**Тема нового чату:** `VARTA C05 — immutable originals і кероване файлове сховище`

**Статус:** `PARTIAL`

### Що є на цей момент

- upload безпечно нормалізує relative paths і складає файли до timestamped
  `00_INBOX`;
- технічна специфікація вимагає незмінну копію original, окремі
  working/derived/report zones та SHA-256;
- цілісного storage service, crash reconciliation і file identity contract ще
  немає;
- оригінальні назви не можна замінювати managed transliterated names.

### Що треба зробити

1. За ADR визначити versioned workspace layout і boundaries `originals`,
   `staging`, `working`, `derived`, `reports`, `logs`, `backups`.
2. Реалізувати storage port/service з opaque `file_id`, literal source name,
   source-relative path, byte length і streaming SHA-256.
3. Копіювати до staging на тому самому volume, перевіряти hash/size, а потім
   атомарно finalize без перезапису існуючого original.
4. Визначити content-addressing/collision policy: однакові bytes сигналізують
   duplicate, але не зливають document roles автоматично.
5. Відокремити managed presentation names від immutable stored object.
6. Додати crash-recovery/reconciliation для orphan staging file та DB/file
   mismatch.
7. Заборонити path traversal, reserved Windows names, unsafe archive paths і
   symlink/reparse-point escape.

### Який результат отримаємо

- байти original захищені від overwrite і rename;
- SQLite metadata однозначно посилається на managed object;
- provenance може зберігати буквальне ім'я незалежно від UI;
- `C06` отримує надійну filesystem transaction boundary.

### Як перевірити

- source hash == stored hash, source timestamps/bytes не змінені;
- duplicate bytes, same name/different bytes, case-insensitive collision;
- Unicode, кирилиця, довгі paths, reserved names;
- path traversal/reparse negative tests;
- simulated interruption before/after finalize і reconciliation;
- read-only/locked file, disk-full/failure injection без прихованої втрати.

**Transition gate:** `PASS`, коли synthetic originals можна прийняти, повторно
перевірити й відновити зв'язок із БД без ручного перейменування.

**Стартовий запит:**

> Виконай C05: реалізуй managed storage та immutable originals поверх рішень
> C02/C04. Збережи буквальні source names, streaming SHA-256 і provenance;
> відокрем managed names. Додай Windows/path/crash/collision tests. Не будуй
> повний intake UI.

## Stage 6 / C06 — Реалізувати intake vertical slice до SQLite

**Тема нового чату:** `VARTA C06 — file, folder і ZIP intake до source of truth`

**Статус:** `PARTIAL`

### Що є на цей момент

- HTTP upload і legacy processor працюють;
- legacy pipeline веде JSON indexes та XLSX register;
- DDL частково містить file/processing entities, але повний `import_batch` flow
  і authoritative inventory read-back відсутні;
- storage foundation має бути наданий `C05`.

### Що треба зробити

1. Реалізувати `IntakeService` для одного файла, каталогу й ZIP; інші archive
   formats — тільки через окремо підтверджений adapter/capability.
2. Створювати intake context та `import_batch` до обходу input.
3. Для кожного entry фіксувати discovered/accepted/duplicate/failed/skipped,
   source URI/path, literal name, size, timestamps, media/type hints і error.
4. Викликати storage service для streaming hash і immutable copy.
5. Забезпечити idempotency key/retry policy; duplicate не видаляється.
6. Partial failure одного entry не rollback-ить успішні entries і не ховається.
7. Формувати inventory query/report тільки з SQLite.
8. Підключити мінімальний API/CLI adapter; legacy XLSX export поки залишається
   compatibility output, не source of truth.

### Який результат отримаємо

- перший повний authoritative flow input -> storage -> SQLite -> read-back;
- після restart inventory відтворюється без XLSX;
- кожен file має SHA-256 і provenance;
- помилки видимі користувачу та в audit/processing history.

### Як перевірити

- unit tests enumeration/idempotency/status transitions;
- integration: mixed synthetic file/folder/ZIP package;
- malicious ZIP traversal, duplicate members, zero-byte, corrupt archive;
- retry same batch і same file under another path;
- restart server/process і compare inventory;
- source tree hash before/after однаковий;
- API/CLI contract та synthetic local-web upload smoke.

**Transition gate:** `PASS`, коли acceptance criteria technical specification
для intake/storage/integrity виконані без XLSX authority.

**Стартовий запит:**

> Виконай C06: побудуй end-to-end intake file/folder/ZIP через application
> service, immutable storage й SQLite. Inventory має читатися з БД після
> restart; partial failures і duplicates — явні. Не починай case detection або
> legacy import.

## Stage 7 / C07 — Реалізувати workspace, case bootstrap та active case

**Тема нового чату:** `VARTA C07 — multi-case workspace і визначення справи`

**Статус:** `PLANNED`

### Що є на цей момент

- case profile schema формалізує candidates, source, confidence і manual review;
- DDL має case/proceeding foundations;
- поточний server часто використовує root folder/config case number;
- назва файла/папки за правилами не є достатнім доказом номера справи;
- multi-case DB + one active case UI ще потребує реалізації.

### Що треба зробити

1. Реалізувати workspace service, case/proceeding repositories і active-case
   selection як presentation preference, а не global domain truth.
2. Після intake створювати temporary `intake_case_id`, не втрачаючи файл.
3. Витягувати raw candidates із дозволених source locations, нормалізувати й
   зберігати evidence basis/confidence/tool version.
4. Обробляти zero/one/multiple candidates; неоднозначність ->
   `manual_review_required`.
5. Locate/create case тільки через application command з audit trail.
6. Зв'язати document/file з однією або кількома справами/провадженнями через
   membership records.
7. Додати API queries/commands для case list, active case і pending bootstrap
   reviews без повного UI redesign.

### Який результат отримаємо

- одна БД безпечно містить багато справ;
- перший документ приймається навіть без визначеного номера;
- автоматична пропозиція не підміняє рішення користувача;
- UI наступних етапів має stable `case_id` context.

### Як перевірити

- zero/one/multiple candidate fixtures;
- filename-only candidate не auto-confirms;
- duplicate normalized number і conflicting external reference;
- many-to-many case/proceeding membership;
- active-case switch не змінює domain membership;
- restart persistence, audit і API contract tests.

**Transition gate:** `PASS`, коли кожен accepted file має визначений case link
або явний pending-review state.

**Стартовий запит:**

> Виконай C07. Реалізуй multi-case workspace, temporary intake_case_id,
> candidate detection/normalization і manual confirmation. Не використовуй
> filename/folder як достатній доказ. Додай API contracts і zero/one/multiple
> candidate tests; повний UI залиш C12/C13.

## Stage 8 / C08 — Завершити evidence-domain services і invariants

**Тема нового чату:** `VARTA C08 — claims, relations, sources і review services`

**Статус:** `PARTIAL`

### Що є на цей момент

- migration `0002` і schema `1.1.0` формалізують file objects, processing runs,
  source references, claims, relations, review decisions, amounts та exports;
- constraints/negative tests частково є;
- окремих repository/application APIs для більшості цих сутностей немає;
- Evidence Map view не доводить наявність authoritative domain flow.

### Що треба зробити

1. Реалізувати repositories/queries/commands для documents, events, actors,
   source references, claims, typed relations, review decisions і findings.
2. Зафіксувати invariants у domain/application, не лише SQL CHECK:
   confirmed relation потребує evidence basis; automatic/user decisions окремі;
   file != document; membership many-to-many.
3. Реалізувати append-only decision history замість in-place overwrite.
4. Визначити optimistic concurrency/version field для user edits.
5. Додати query model, достатню для timeline, source context і Evidence Map.
6. Перенести authoritative anomaly/review state із JSON у SQLite або залишити
   compatibility import із явним sunset plan.
7. Описати public DTOs, ordering, pagination і error cases.

### Який результат отримаємо

- Evidence Map і UI можуть працювати з application API, а не raw tables;
- ручні рішення відтворювані й не стирають автоматичний висновок;
- source basis кожного confirmed claim/relation перевіряється;
- `C11` отримує повну read model.

### Як перевірити

- repository + application integration tests для всіх aggregates;
- orphan/invalid type/missing source negative tests;
- append-only review history й conflict version tests;
- transaction rollback разом з audit;
- synthetic case від document/event до claim/relation/source query;
- restart/read-back і schema/API compatibility tests.

**Transition gate:** `PASS`, коли synthetic case читається через services без
direct SQL у HTTP handlers або projection code.

**Стартовий запит:**

> Виконай C08. Заверши repository/application services та invariants для
> evidence domain поверх чинного DDL/JSON contract. Перенеси authoritative
> review state до SQLite, збережи automatic/user history окремо. Не генеруй
> map-data і не перебудовуй UI.

## Stage 9 / C09 — Побудувати read-only legacy XLSX/.caseflow adapter

**Тема нового чату:** `VARTA C09 — контрольована міграція legacy state до SQLite`

**Статус:** `PLANNED`

### Що є на цей момент

- Airtable schema/importer уже дає приклад two-pass idempotent migration;
- legacy CaseFlow читає/пише XLSX, JSON і `.caseflow` runtime;
- старі каталоги поза `D:\VARTA` є read-only sources;
- немає повного dry-run/reconciliation/switchover для XLSX і `.caseflow`.

### Що треба зробити

1. Інвентаризувати versioned legacy formats без запису в source.
2. Описати mapping кожного поля до application command/DTO; unsupported,
   lossy, ambiguous і derived fields позначити явно.
3. Реалізувати dry-run report: counts, hashes, conflicts, unresolved links,
   proposed actions, zero DB writes.
4. Перед import вимагати verified backup destination; не видаляти legacy data.
5. Реалізувати two-pass idempotent import із stable external references.
6. Звірити row/document/file counts, hashes, memberships і skipped reasons.
7. Конфлікти направляти в manual review/quarantine.
8. Переключати authoritative read path лише окремим feature/config gate після
   reconciliation; XLSX export залишається adapter.

### Який результат отримаємо

- корисний legacy state переноситься без другої writable truth;
- повторний import безпечний;
- кожне відхилення пояснюється reconciliation report;
- старі джерела залишаються незмінними.

### Як перевірити

- frozen synthetic legacy fixtures і golden dry-run report;
- read-only hash tree before/after;
- first import/reimport/update/conflict scenarios;
- counts та SHA-256 reconciliation;
- unsupported field і broken reference tests;
- rollback DB transaction без зміни source;
- privacy scan fixtures.

**Transition gate:** `PASS`, коли два послідовні imports не створюють дублів, а
звіт пояснює кожне source record.

**Стартовий запит:**

> Виконай C09. Побудуй read-only dry-run та idempotent XLSX/.caseflow importer
> до application services/SQLite. Не змінюй legacy sources і не перемикай
> production read path без reconciliation gate. Використовуй лише synthetic
> fixtures, якщо окремо не надано acceptance corpus.

## Stage 10 / C10 — Запровадити durable processing jobs і plugin contract

**Тема нового чату:** `VARTA C10 — processing_runs, workers і fault recovery`

**Статус:** `PARTIAL`

### Що є на цей момент

- server запускає subprocess workers і має in-memory/file job lock;
- DDL містить `processing_runs` та file links;
- plugin packages OCR/КЕП/STT є scaffolds;
- worker result/error/version/provenance ще не мають єдиного durable contract;
- crash/restart може залишити operational JSON state.

### Що треба зробити

1. Визначити job state machine: queued/running/succeeded/failed/cancelled/
   interrupted/not_available із дозволеними переходами.
2. Реалізувати application `JobService`, durable queue/leases і restart
   recovery для одного локального instance.
3. Стандартизувати processor request/result manifest: input file IDs, hashes,
   parameters, tool/model version, timestamps, stdout/stderr summary, artifacts,
   findings, confidence й error.
4. Workers отримують лише дозволені managed paths/IDs і не змінюють originals.
5. Authoritative finalize виконує application service в транзакції після
   перевірки result/artifact hashes.
6. Реалізувати timeout, cancellation, retry/idempotency і resource limits.
7. Додати plugin discovery без silent import failures; unavailable dependency
   є явним capability state.

### Який результат отримаємо

- довгі OCR/STT/КЕП/matching tasks не блокують HTTP lifecycle;
- crash не маскує job як running forever;
- кожен derived artifact відтворювано пов'язаний із input і tool version;
- окремі processor chats можуть працювати по стабільному contract.

### Як перевірити

- state-transition unit tests;
- worker success/failure/timeout/cancel/crash/restart integration tests;
- duplicate request/idempotent retry;
- invalid result manifest/hash mismatch quarantine;
- original hash unchanged;
- server responsive while worker runs;
- installed/frozen hidden-import and capability smoke.

**Transition gate:** `PASS`, коли synthetic processor переживає restart і його
результат читається з SQLite з повним provenance.

**Стартовий запит:**

> Виконай C10. Створи durable processing job contract і isolated worker
> lifecycle поверх processing_runs. Доведи crash/restart/timeout/retry та
> provenance. Реальний OCR/КЕП/STT алгоритм не реалізовуй — лише synthetic
> reference processor і stable plugin API.

## Stage 11 / C11 — Побудувати детерміновану Evidence Map projection

**Тема нового чату:** `VARTA C11 — SQLite to Evidence Map generator`

**Статус:** `BLOCKED_BY_DECISION` до завершення `C08`

### Що є на цей момент

- JSON Schema `1.1.0`, templates і offline HTML view існують;
- migration `0002` має потрібні нижні таблиці;
- view використовує snapshot/embedded data;
- generator із authoritative services, canonical ordering і export hash відсутній.

### Що треба зробити

1. Реалізувати read-only `EvidenceMapProjectionService(case_id, profile_version)`.
2. Читати тільки application queries; direct SQL у generator заборонити.
3. Формувати nodes/edges/claims/events/documents/sources/reviews згідно schema.
4. Детерміновано впорядковувати keys/arrays, нормалізувати timestamps і не
   включати volatile runtime fields у canonical hash.
5. Формувати inventory/exclusions/manual-review summary.
6. Перевіряти referential integrity й блокувати `valid`, якщо confirmed item не
   має source basis або є broken reference.
7. Валідувати JSON Schema, обчислювати snapshot SHA-256 і зберігати export
   record, не імпортуючи snapshot назад як truth.

### Який результат отримаємо

- `map-data.json` стає відтворюваною read-only проєкцією SQLite;
- одна revision дає один canonical hash;
- UI й sealed export використовують один generator;
- broken/uncertain data не приховуються.

### Як перевірити

- golden synthetic case snapshot;
- same revision repeated hash equality;
- insertion-order independence;
- broken reference, missing source, unsupported classification negative tests;
- schema validation і snapshot hash verification;
- DB unchanged by projection except explicit export audit record.

**Transition gate:** `PASS`, коли generator відтворює валідний snapshot після
restart і однаково працює для UI та export caller.

**Стартовий запит:**

> Виконай C11 після C08. Реалізуй детермінований Evidence Map projection через
> application queries, schema validation і canonical SHA-256. Snapshot — лише
> read-only projection, не друга БД. Додай golden, determinism і broken-reference
> tests; HTML UI не змінюй.

## Stage 12 / C12 — Перевести local web UI на application services

**Тема нового чату:** `VARTA C12 — thin local HTTP API і інтегрований web UI`

**Статус:** `PARTIAL`

### Що є на цей момент

- local page, contacts CRUD, upload, document tree та anomalies UI існують;
- loopback restriction, mutating-request token і CSP реалізовані;
- contacts persistence після restart перевірена;
- server handlers і JavaScript ще працюють із legacy XLSX/JSON/filesystem flows;
- Evidence Map не під'єднана до SQLite generator.

### Що треба зробити

1. Розділити HTTP presentation adapter на versioned route modules; handlers
   лише parse/auth/call service/map response.
2. Підключити application APIs для intake/inventory, case selection,
   documents/tree, timeline, Evidence Map, review queue, sources й exports.
3. Модульно розділити `app.js` за presentation concerns без domain duplication.
4. Зберігати navigation context `case_id`, optional `proceeding_id`,
   `document_id`, `event_id`, `returnTo`.
5. Заборонити browser direct paths/SQLite access; file open/download проходить
   safe ID-based endpoint.
6. Посилити local HTTP boundary: validate Host/Origin, loopback only, CSRF,
   CSP/frame policy, request limits, no external assets by default.
7. Залишити Google/інші integrations окремими disabled optional adapters; їх
   failure не блокує core UI.
8. Додати accessibility/keyboard/error/loading/empty states.

### Який результат отримаємо

- один локальний web UI поверх єдиного source of truth;
- browser не знає storage layout і не реалізує legal/domain conclusions;
- restart не втрачає authoritative state;
- HTTP framework можна змінити пізніше без зміни use cases.

### Як перевірити

- HTTP contract tests кожного route;
- Host/Origin/CSRF/path/request-size negative tests;
- browser smoke: upload -> inventory -> case -> document -> map;
- persistence after full restart;
- no external network request assertion;
- keyboard navigation, visible errors, 320px/desktop layout smoke;
- full regression suite та optional integration disabled test.

**Transition gate:** `PASS`, коли мінімальний user journey працює в browser без
authoritative XLSX/JSON writes.

**Стартовий запит:**

> Виконай C12. Переведи наявний local web UI на `/api/v1` application services,
> зроби handlers thin і підключи SQLite-backed intake/case/documents/map. Посиль
> loopback Host/Origin/CSRF/CSP boundary та додай browser/runtime tests. Не
> розширюй processor algorithms або packaging.

## Stage 13 / C13 — Завершити review, timeline і source-context workflow

**Тема нового чату:** `VARTA C13 — manual review і доказовий контекст у web UI`

**Статус:** `PLANNED`

### Що є на цей момент

- UI має contacts, tree і anomaly cards;
- schema/domain передбачають source references та review decisions;
- частина manual statuses історично зберігається в JSON;
- немає єдиного переходу від finding/claim/relation до original source context.

### Що треба зробити

1. Реалізувати manual-review inbox із фільтрами за case/type/status/severity.
2. Показувати automatic result, confidence, tool version і evidence basis
   окремо від user decision/note/actor/time.
3. Додати source-context view: document/file ID, literal name, hash, provenance,
   source location/page/range та safe open action.
4. Реалізувати timeline query/navigation з поверненням до попереднього context.
5. Зберігати decision append-only із optimistic concurrency; undo означає нове
   рішення, не rewrite history.
6. Інтегрувати claims/relations/findings із Evidence Map selection.
7. Додати empty/conflict/stale-version/unavailable-source states.

### Який результат отримаємо

- користувач може перевірити, чому система зробила висновок;
- автоматизація не видається за остаточне юридичне рішення;
- кожна manual action має audit history;
- Evidence Map, timeline і original source утворюють один навігаційний flow.

### Як перевірити

- application/UI tests pending -> confirm/reject/defer;
- concurrent stale decision conflict;
- source reference to correct immutable file/hash;
- navigation return context tests;
- restart persistence й audit history;
- browser keyboard/accessibility/error-state smoke;
- privacy: absolute source paths не витікають у export/непотрібні logs.

**Transition gate:** `PASS`, коли synthetic uncertain finding можна відкрити,
перевірити за source, вирішити й повторно побачити після restart.

**Стартовий запит:**

> Виконай C13. Побудуй наскрізний manual-review, timeline і source-context flow
> поверх services C08/C11/C12. Зберігай automatic і user decisions окремо та
> append-only. Додай conflict, provenance, navigation і browser tests.

## Stage 14 / C14 — Створити sealed standalone export і validator

**Тема нового чату:** `VARTA C14 — автономний Evidence Map export без сервера`

**Статус:** `PARTIAL`

### Що є на цей момент

- offline HTML view і snapshot schema існують;
- немає повного generator/manifest/validator lifecycle;
- standalone export не повинен виглядати редагованим або звертатися до мережі;
- режими `full_local`, `redacted`, `metadata_only` визначені концептуально.

### Що треба зробити

1. Створювати export із конкретного `export_id`, case revision, profile version
   і snapshot hash.
2. Генерувати sealed directory `index.html`, `map-data.json`, `manifest.json`,
   `validation-report.json` та дозволені local assets.
3. Реалізувати explicit export modes і redaction policy; `full_local` лише після
   явного user choice.
4. Додати SHA-256 manifest для кожного entry, schema/tool versions і exclusions.
5. Validator працює offline, перевіряє entries/hashes/schema/references і не
   модифікує export.
6. HTML не використовує CDN, external fonts, fetch/XHR/WebSocket/service worker
   і не має write controls.
7. Export source record/audit зберігається в SQLite; сам export не стає truth.

### Який результат отримаємо

- переносимий read-only пакет із доказовою цілісністю;
- одержувач може перевірити hashes без VARTA server;
- redaction scope і exclusions видимі;
- UI та export використовують той самий canonical snapshot.

### Як перевірити

- manifest/hash/schema validator positive/negative tests;
- tampered/missing/extra file detection;
- offline browser render і zero network request assertion;
- no write controls/API calls;
- deterministic snapshot linkage;
- redacted/metadata/full fixture inspection без реальних case data.

**Transition gate:** `PASS`, коли свіжий export проходить standalone validator,
а одна змінена byte дає керовану failure.

**Стартовий запит:**

> Виконай C14. Створи sealed standalone export і offline validator на основі
> C11 projection. Додай manifest SHA-256, explicit modes, tamper tests і browser
> zero-network verification. Не пакуй весь Windows application.

## Stage 15 / C15 — Довести backup/restore, Windows package та update path

**Тема нового чату:** `VARTA C15 — data recovery і Windows delivery`

**Статус:** `PARTIAL`

### Що є на цей момент

- Windows scripts і PyInstaller build material існують;
- one-file EXE historically запускав local server;
- offline support bundle є захищеним asset;
- SQLite online-backup primitive має бути створений у C04;
- немає прийнятого coordinated SQLite + filesystem backup/restore/update gate.

### Що треба зробити

1. Реалізувати consistent backup orchestration: quiesce/finalize jobs, SQLite
   backup API, managed-file inventory, SHA-256 manifest і completion marker.
2. Restore тільки в новий/порожній target, потім DB integrity, schema, files,
   provenance і sample read-back verification.
3. Визначити retention, incomplete backup cleanup і recovery instructions.
4. Побудувати package із clean staging, включити SQL migrations/static assets/
   dictionaries/config catalogs/required hidden imports.
5. Перевірити offline install/start, Unicode path, no-admin mode і dependency
   availability.
6. Реалізувати update preflight: backup, compatible schema, atomic app switch,
   rollback application version без destructive DB down migration.
7. Uninstall ніколи не видаляє user workspace без окремої explicit operation.

### Який результат отримаємо

- користувач може відновити повну узгоджену систему на новому місці;
- package відтворюється з контрольованого source snapshot;
- update failure не знищує originals/DB;
- offline support assets не плутаються з project debris.

### Як перевірити

- live write/jobs vs backup consistency test;
- restore to new Unicode/long-path directory;
- corrupted/incomplete backup rejection;
- fresh packaged start -> workflow -> restart;
- previous-version upgrade й failed-update rollback;
- offline dependency resolution/import/tool version checks;
- uninstall/update assert user data remains;
- archive entry inventory і SHA-256 manifest.

**Transition gate:** `PASS`, коли package, backup і restore працюють на чистому
Windows environment із вимкненою мережею.

**Стартовий запит:**

> Виконай C15. Заверши coordinated SQLite+filesystem backup/restore, clean
> Windows package і safe update/rollback. Використай захищений offline bundle
> лише read-only. Доведи restore в новий Unicode path і те, що uninstall/update
> не видаляють user data. Не commit/push/release без окремої команди.

## Stage 16 / C16 — Провести acceptance, privacy та release gate

**Тема нового чату:** `VARTA C16 — end-to-end acceptance і release candidate audit`

**Статус:** `PLANNED`

### Що є на цей момент

- synthetic unit/integration baseline уже значний;
- реальний acceptance corpus дозволений лише локально/приватно й не входить до
  Git або release artifacts;
- release не можна доводити результатами одного dirty working tree;
- commit/push виконуються лише окремим GitHub checkpoint після `TECH PASS`;
  merge/release/publication залишаються окремими рішеннями.

### Що треба зробити

1. Побудувати clean controlled candidate з exact source snapshot і зафіксованих
   dependencies.
2. Запустити full automated suite: unit, integration, migration, restore,
   contract, architecture, browser, package, offline та tamper tests.
3. Виконати end-to-end synthetic journey від intake до sealed export і restore.
4. Окремо, у контрольованому локальному режимі, запустити authorized real-corpus
   acceptance без копіювання даних до repo/logs/report artifacts.
5. Виміряти цільові volumes: intake throughput, DB queries, UI response,
   worker memory/time, export/backup duration; не вигадувати target без ADR.
6. Провести privacy/security audit staged tree, package, logs, manifests і
   export modes; перевірити Host/Origin/CSRF/path/archive abuse cases.
7. Звірити product/schema/API/profile/export versions і known limitations.
8. Сформувати release evidence report, bill of included files, hashes,
   reproduction commands і rollback instructions.
9. Після `TECH PASS` окремий підтверджений GitHub checkpoint може виконати exact
   staging, commit, push і Draft PR. Merge, tag, release та publication не
   випливають ані з `PASS`, ані з `GITHUB SYNCED`.

### Який результат отримаємо

- доказово відтворюваний release candidate;
- окремі результати synthetic і real-corpus acceptance;
- відомі обмеження, performance bounds і recovery procedure;
- рішення про publication може бути прийняте на основі exact evidence.

### Як перевірити

- clean checkout/build parity;
- all quality gates і end-to-end journey;
- network-disabled package test;
- backup/restore/upgrade/restart;
- staged/package secret and case-data scans;
- file manifests, hashes і archive integrity;
- real-corpus output залишається тільки в дозволеному local workspace;
- final `git status`, staged paths і diff report показані користувачу.

**Transition gate:** `TECH PASS` означає технічну готовність candidate;
`GITHUB SYNCED` фіксує commit/push/Draft PR, але не є дозволом на merge або
release.

**Стартовий запит:**

> Виконай C16 як read/verify-first release candidate audit. Побудуй clean
> candidate, запусти всі automated, browser, offline, package, backup/restore і
> privacy gates; synthetic та authorized real-corpus результати звітуй окремо.
> Не commit, push або release без моєї окремої явної команди.

## 6. Окремі processor-чати після C10

Ці задачі не блокують core critical path, якщо Evidence Map може працювати з
synthetic/manual data. Кожний `Pxx` так само має рівно один постійний чат і
використовує тільки затверджений plugin/job contract.

### P01 — OCR і text extraction

**Тема:** `VARTA P01 — OCR/text processor adapter`

**Статус:** `PLANNED`

**Залежності:** `C05`, `C08`, `C10`.

#### Що є на цей момент

- у baseline є OCR/processing scaffolds і локальні dependency checks;
- `C05` має дати immutable source/derived-storage boundary;
- `C08` має дати evidence/source repository APIs;
- `C10` має дати durable job і versioned plugin contract;
- конкретний OCR adapter не повинен формувати власну чергу, provenance model
  або другу writable truth.

#### Що треба зробити

1. Реалізувати capability detection для дозволеного local OCR runtime без
   silent fallback у мережевий service.
2. Визначити versioned request parameters: language set, page range, rotation,
   preprocessing profile, engine/version і timeout.
3. Перетворювати OCR output тільки на derived artifacts; оригінальний PDF/image
   і його hash залишаються незмінними.
4. Зберігати text blocks, page mapping, confidence, warnings/errors, source
   artifact ID/hash і processing run ID.
5. Підтримати retry/restart через `C10`, не створюючи duplicate authoritative
   results.
6. Додати synthetic fixtures без реальних документів справи.

#### Який результат отримаємо

- OCR запускається як ізольований local processor;
- кожний text fragment має source page/provenance;
- UI/application services можуть відрізнити success, partial, unsupported і
  failed result;
- відсутність OCR dependency є capability state, а не прихованим exception.

#### Як перевірити

- Ukrainian/English synthetic pages;
- rotated page, blank page, corrupt/unsupported PDF;
- missing OCR dependency і offline/no-network assertion;
- deterministic result для однакових versioned params;
- timeout, cancellation, retry й process/controller restart;
- derived hash, source document hash і page linkage;
- original bytes/hash before/after.

**Transition gate:** `PASS`, коли synthetic OCR job переживає restart, result
читається через stable application contract, а кожний fragment має source page
і незмінний original hash.

**Стартовий запит:**

> Виконай тільки P01 з `docs/chat-roadmap.md` після gates C05, C08 і C10.
> Реалізуй local OCR capability detection, versioned language/model params,
> derived text з page mapping, confidence/errors і незмінністю originals. Додай
> synthetic Ukrainian/English, rotation, blank/corrupt PDF, missing dependency,
> timeout, restart і provenance tests.

### P02 — КЕП і attachment validation

**Тема:** `VARTA P02 — КЕП/P7S і заявлені додатки`

**Статус:** `PLANNED`

**Залежності:** `C05`, `C08`, `C10`.

#### Що є на цей момент

- правила acquisition вимагають literal filename/structure і збереження
  `.pdf`/`.pdf.p7s` pairing;
- P7S/document artifacts і processing scaffolds існують частково;
- немає одного stable result contract для cryptographic verification,
  unsupported provider і claimed-vs-actual attachment findings;
- private keys, OAuth state і credentials заборонені в repository/logs.

#### Що треба зробити

1. Побудувати literal pairing без lowercasing, auto-rename або derivation із
   `blob:` URL.
2. Визначити local verifier adapter і capability states: `available`,
   `unsupported`, `not_verifiable`, `failed`.
3. Записувати tool/version, verification time, certificate/public metadata,
   signature status і source hashes без private key material.
4. Розділити cryptographic fact, certificate-time semantics і user/legal
   interpretation.
5. Порівнювати заявлений перелік додатків з фактичними immutable artifacts та
   створювати reviewable findings, а не автоматичний правовий висновок.
6. Підключити retry/provenance до `C10` і evidence links до `C08`.

#### Який результат отримаємо

- literal file/signature relation збережена;
- supported signatures мають відтворюваний local verification result;
- unsupported/unknown не перетворюється на `valid` або `invalid`;
- missing/extra/ambiguous attachments потрапляють у manual review.

#### Як перевірити

- synthetic valid/invalid/missing/ambiguous pairs;
- uppercase/mixed-case, repeated spaces і `.pdf.p7s` literal names;
- unsupported provider, missing verifier і corrupt signature;
- expired/unknown certificate-time semantics без overclaim;
- original hashes before/after;
- privacy scan logs/results на private key, token і credential patterns;
- retry/restart і deterministic pairing.

**Transition gate:** `PASS`, коли pairing literal, supported verification
відтворюваний, unsupported state чесний, originals незмінні, а secrets не
потрапляють у logs або result artifacts.

**Стартовий запит:**

> Виконай тільки P02 з `docs/chat-roadmap.md` після gates C05, C08 і C10.
> Реалізуй literal `.pdf`/`.pdf.p7s` pairing, local verification adapter,
> certificate/tool metadata, `not_verifiable` та claimed-vs-actual attachments
> без передавання private keys. Додай valid/invalid/missing/ambiguous,
> unsupported provider, no-secret-log і unchanged-original tests.

### P03 — STT для audio/video

**Тема:** `VARTA P03 — offline STT processor`

**Статус:** `PLANNED`

**Залежності:** `C05`, `C08`, `C10`, verified offline model asset.

#### Що є на цей момент

- offline bundle і Whisper/FFmpeg support assets розглядалися як protected
  local dependencies;
- processing worker scaffolds існують, але stable STT result contract не
  підтверджений;
- model asset не можна вважати доступним лише через filename або старий
  inventory — потрібен live hash/capability check;
- audio/video originals мають залишатися незмінними.

#### Що треба зробити

1. Додати capability check для FFmpeg і exact offline model asset/version/hash.
2. Нормалізувати media у derived artifact із source hash і command/parameter
   provenance.
3. Реалізувати local transcription через `C10` job contract без network
   fallback.
4. Зберігати segments, timestamps, detected/selected language, confidence або
   explicit unavailable-confidence semantics.
5. Визначити timeout, cancellation, retry і resume-from-safe-boundary policy.
6. Не перетворювати transcript на verified fact без source audio context і
   manual review.

#### Який результат отримаємо

- відтворювана offline transcription із прив'язкою segment → time range →
  source media;
- missing model/FFmpeg має контрольований capability status;
- interruption не залишає authoritative partial result;
- derived media й transcript повністю provenance-linked.

#### Як перевірити

- short synthetic Ukrainian audio з відомим текстом;
- silence, corrupt media, unsupported codec і empty stream;
- offline model load після network disable;
- model hash/version mismatch;
- timeout, cancellation, retry й controller/process restart;
- segment timestamp boundaries і deterministic parameters;
- original hash before/after та derived/source linkage.

**Transition gate:** `PASS`, коли verified offline asset обробляє synthetic
media без мережі, interruption/retry контрольовані, timestamps коректні й усі
results посилаються на immutable source hash.

**Стартовий запит:**

> Виконай тільки P03 з `docs/chat-roadmap.md` після gates C05, C08, C10 і лише
> за наявності verified offline model asset. Реалізуй FFmpeg normalization як
> derived artifact, local Whisper, segments/timestamps/language/confidence та
> interruption/resume policy. Додай synthetic Ukrainian audio,
> silence/corrupt/unsupported media, offline-load, timeout/retry і provenance
> tests.

### P04 — matching і anomaly analysis

**Тема:** `VARTA P04 — document matching і findings`

**Статус:** `PLANNED`

**Залежності:** `C08`, `C10`; OCR/STT only when their evidence is required.

#### Що є на цей момент

- anomaly detector і matching-related fields існують у baseline частково;
- exact hash, metadata similarity і extracted-text similarity мають різну
  доказову силу, але не всюди розділені;
- automatic finding не є fraud/legal conclusion;
- user review/override має зберігатися окремо від recomputed automatic state.

#### Що треба зробити

1. Визначити versioned matching levels: exact bytes/hash, normalized metadata,
   structure і derived text similarity.
2. Для кожного algorithm/version зберігати inputs, thresholds, score,
   confidence/uncertainty, exclusions і processing run.
3. Створювати structured finding з source artifact IDs, але без автоматичного
   legal/fraud label.
4. Визначити same-hash/different-role і same-content/different-container
   semantics.
5. Підключати OCR/STT-derived evidence лише з явним provenance та capability
   state.
6. Зберігати user decision append-only; recompute не має його переписувати.

#### Який результат отримаємо

- matching result відтворюваний для exact algorithm/threshold version;
- false/ambiguous cases не маскуються як підтверджений факт;
- кожне finding відкриває source context і manual-review action;
- automatic recompute й user decision мають окрему історію.

#### Як перевірити

- true/false/ambiguous synthetic document pairs;
- exact threshold boundaries і version change;
- same-hash different-role та different-hash equivalent-text cases;
- insertion/order independence і deterministic result;
- missing OCR/STT capability;
- confirm/reject/defer user decision після recompute/restart;
- no automatic fraud/legal language assertion.

**Transition gate:** `PASS`, коли matching deterministic/versioned, ambiguous
cases явні, кожне finding має source basis, а user decision зберігається після
recompute й restart.

**Стартовий запит:**

> Виконай тільки P04 з `docs/chat-roadmap.md` після gates C08 і C10. Реалізуй
> versioned exact/metadata/text matching, explicit confidence, structured
> findings і manual-review link без automatic fraud/legal conclusion. Додай
> true/false/ambiguous pairs, threshold boundaries, same-hash different-role,
> determinism і preserved-user-decision tests.

## 7. Правила паралельної роботи чатів

1. Паралельно дозволені лише packages з виконаними dependencies та без
   overlapping write scope.
2. `C01`–`C08` краще виконувати послідовно: вони змінюють спільні contracts.
3. Після `C10` processor chats можуть працювати паралельно в окремих plugin
   modules і fixtures.
4. `C11` projection і processor implementation можуть йти паралельно, якщо
   projection використовує stable application DTOs, а не processor internals.
5. `C12`–`C15` виконуються послідовно через спільний UI/export/package surface.
6. Перед інтеграцією паралельний чат повторно читає current contracts і не
   force-overwrites зміни іншого чату.

## 8. Definition of Done для будь-якого package

Package не має статусу `DONE`, якщо відсутній хоча б один застосовний елемент:

- implementation у точному scope;
- tests для happy, negative і failure/restart paths;
- type/lint/compile checks;
- runtime або browser evidence для user-visible flow;
- migration/restore evidence для data changes;
- privacy scan для data/export/package changes;
- документація contract/status/open limitations;
- transition result і handoff;
- підтвердження, що materials, legacy sources і protected assets не змінені.

Наявність файла, таблиці, route, button або passing unit test не доводить
наскрізний flow. Формула перевірки для кожної авторитетної операції:

```text
input
  -> application command
  -> SQLite + managed filesystem transaction
  -> process restart
  -> application query
  -> local web UI/report/export
  -> audit/provenance verification
```

## 9. Найближча дія

Відкривати новий чат із темою:

```text
VARTA C01 — стабілізація поточного working baseline
```

До `PASS` C01 не починати масовий refactor, новий UI framework, full Evidence
Map generator, processor integrations або release packaging: вони можуть
закріпити поточне роздвоєння state й ускладнити безпечну інтеграцію вже наявних
змін.
