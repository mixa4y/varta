# VARTA project status

**Статус:** `ACTIVE`

**Версія продуктового baseline:** `0.1.0`

**Дата синхронізації:** `18.08.2026`

**Канонічний root:** `D:\VARTA`

**Гілка:** `codex/stabilize-baseline`

## Контрольований Git baseline для C02

Controller до початку package зафіксував:

| Field | Value |
|---|---|
| HEAD | `c3a5b122894e81aff2d82078df7e38e5659d3733` |
| Branch | `codex/stabilize-baseline` |
| Tracked/staged/untracked status | empty |
| Status SHA-256 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Captured | `2026-08-18T08:49:29+00:00` |

Commit `c3a5b12` містить стабілізований C01 roadmap/controller scope поверх
попереднього product baseline `bc51a00`. C01 evidence: `94 passed`, clean
Ruff/mypy/compileall, package-data proof, synthetic HTTP/SQLite restart smoke
і privacy scan. C02 не виконує commit, push, publication, release або remote
changes.

На continuation turn цього самого C02-чату controller повторно зафіксував
`HEAD c3a5b12`, ту саму branch і 36 dirty status entries зі SHA-256
`19bae2a50f3b31fe2ad70ca9f9c89014a3b2f1cbf1d2d508ce6febb052bf51e6` о
`2026-08-18T10:11:18+00:00`. Це checkpoint незавершеного C02 разом із
паралельними roadmap-controller changes, а не новий clean dependency baseline.

## C02: рішення та реалізація — окремі стани

| Рівень | Стан після C02 |
|---|---|
| Architecture decisions | `APPROVED`: `ADR-001`–`ADR-007` |
| Technical specification | `APPROVED v1.0`, синхронізована з ADR |
| Local web choice | `DECIDED`: embedded browser UI, explicit loopback only |
| Notion | `EXCLUDED`: не runtime, docs workflow, integration або source of truth |
| Structured source of truth | `DECIDED`: тільки SQLite writable; XLSX/JSON/HTML — adapters/projections |
| Binary authority | `DECIDED`: registered bytes у managed filesystem |
| Application boundary | `DECIDED`, implementation `PENDING C03/C12` |
| SQLite connection model | `DECIDED`: short-lived UoW/connection per application operation |
| Worker boundary | `DECIDED`, durable implementation `PENDING C10` |
| Workspace/storage | `DECIDED`: one multi-case DB, zero/one active UI case, `.varta` target |
| Current legacy code | `UNCHANGED BY C02`; direct server/repository/filesystem paths ще існують |

C02 є architecture/documentation package. `APPROVED` не означає, що
application layer, managed storage, migration або security refactor уже
реалізовано.

## C02 verification evidence

| Gate | Result |
|---|---|
| C02 architecture-doc tests | `8 passed` |
| Roadmap/controller contract suite | `15 passed`; combined targeted suite `23 passed` |
| Full pytest | `105 passed` |
| Ruff | `All checks passed` for `case_docket`, `caseflow`, `tests`, controller tools |
| mypy | `Success: no issues found in 26 source files` |
| compileall | passed for `case_docket`, `caseflow`, `tests`, controller tools |
| JSON / inline JavaScript syntax | passed for stage catalog and both interactive maps |
| ADR completeness / links / open-question owners | passed in C02 tests |
| UI dependency scan | no browser asset imports repository/SQLite |
| Terminology/source-of-truth scan | 14 canonical docs; 6 stale-pattern classes absent |
| Git whitespace | `git diff --check` passed |
| C02 privacy scan | 32 owned paths; zero high-risk findings; only triaged support path `D:\CMSD\offline_bundle` |

Окремі verification launches не виконали повний test body через environment:
WindowsApps `python.exe` був недоступний, один `--basetemp` мав неіснуючий
parent, а default `%TEMP%\pytest-of-mixa4y` був недоступний sandbox. Runs
повторено через `D:\VARTA\.venv\Scripts\python.exe` з explicit repo-local
basetemp; наведені вище фінальні результати зелені, temp видалено.

Під час C02 окремо з'явилися сторонні для цього package зміни у
`tools/roadmap_controller/server.py`, `tests/test_roadmap_controller.py`,
`tools/roadmap_controller/browser_smoke.cjs`, `docs/roadmap-controller.md` та
live-progress hunks у `docs/interactive/varta-chat-roadmap.html`. C02 не
редагував і не відкидав controller/test/browser-smoke/docs paths; у mixed HTML
C02 володіє лише version/status summary, `DONE`/`READY`, stats і C01–C03
content-hunks.
Full suite пройшов на фактичному combined working tree; exact C02 scope
відділено hunk-level і перевірено regression-testом.

## Target architecture

```text
browser on loopback
  -> versioned local HTTP presentation adapter
  -> application services + Unit of Work
  -> domain/ports
  -> SQLite + managed filesystem
  -> durable supervisor -> isolated workers -> validated result finalize
```

Authoritative state — узгоджена пара SQLite + managed filesystem. SQLite є
єдиним writable structured source of truth; originals є immutable registered
bytes. `map-data.json`, XLSX, JSON, HTML, reports і exports не є другою
editable database.

Повний пакет: `docs/architecture/architecture-decision-log.md` та
`docs/architecture/technical-specification.md`.

## Що вже реально реалізовано

- Python 3.12 package, versioned SQLite migrations і checksum runner;
- immutable migrations `0001`/`0002`, additive scoped indexes `0003`–`0006`
  та C05 storage metadata migration `0007`;
- per-operation thread-owned SQLite connections, explicit read/write UoW,
  verified foreign keys/WAL/busy/checkpoint policy та schema floor/ceiling;
- DB-only online backup/restore primitive з integrity/FK/schema verification;
- managed storage layout v1, streaming SHA-256, immutable original finalize,
  duplicate signal і DB/filesystem crash reconciliation для одного source file;
- SQLite repository/API/UI vertical slice для контактів;
- DDL та JSON contracts для case profile і Evidence Map domain;
- local `ThreadingHTTPServer`, static UI, loopback restriction, mutating token,
  CSP та path checks як partial security baseline;
- upload/legacy processing, anomaly detector і plugin scaffolds;
- Windows build/install/update tooling як migration material;
- roadmap controller і synthetic tests.

## Evidence Map: точна межа реалізації

| Рівень | Стан |
|---|---|
| Versioned DDL | `DONE` для migrations `0001`/`0002` |
| JSON contracts | `DONE`: case profile/Evidence Map schema `1.1.0` |
| Repository API | `PARTIAL`: немає повних services для claims/relations/sources/review/exports |
| Application flow | `PARTIAL`: немає детермінованого SQLite -> projection/UI/export flow |

Отже статус лишається `DDL/CONTRACT DONE`, `REPOSITORY API PARTIAL`,
`APPLICATION FLOW PARTIAL`.

## Затверджений migration path і поточний implementation state

1. `C03`: `IMPLEMENTED` — application services, ports, Unit of Work і `/api/v1`.
2. `C04`: `IMPLEMENTED IN CURRENT WORKTREE` — connection/concurrency,
   migration compatibility та DB-only online-backup lifecycle; Git checkpoint
   залишається окремою явно дозволеною дією.
3. `C05`: `IMPLEMENTED IN CURRENT WORKTREE` — managed storage,
   immutable-original finalize/reconciliation; Git checkpoint окремий.
4. `C06`: next package — authoritative file/folder/ZIP intake до SQLite read-back.
5. `C07`/`C08`: multi-case bootstrap та evidence-domain services.
6. `C09`: read-only `.caseflow`/XLSX inventory/import/reconciliation.
7. `C10`: durable jobs та isolated workers.
8. `C11`–`C14`: deterministic projections, UI workflow і sealed export.
9. `C15`/`C16`: recovery, Windows delivery, privacy/performance/release gates.

Поточний server runtime path `<workspace>/.caseflow/varta.sqlite3` залишається
legacy implementation. C05 library реалізує target
`<workspace>/.varta/database/varta.sqlite3` + versioned managed zones, але не
переміщує legacy state і не підключає upload UI до C06. Жодного in-place rename
або видалення runtime файла немає.

## C05 implementation evidence

C05 працює лише через application ports/UoW та `case_docket.storage` adapter.
Synthetic verification охоплює literal Unicode names, actual Windows path
понад 260 символів, reserved/traversal/reparse negatives, same-name/different-
bytes, duplicate bytes, case-insensitive managed-name collision, readonly/
locked/disk-full, no-overwrite collision і interruptions до/після finalize.
Recovery відтворює SQLite link із валідного manifest без ручного rename.

Фінальні локальні gates: `173 passed`, clean Ruff, mypy для 46 source files,
compileall, `git diff --check`, offline wheel та isolated installed-package
storage/schema smoke. Жодного commit/push/publication/release або доступу до
case materials C05 не виконував.

## Versioned open decisions

| ID | Owner | Gate |
|---|---|---|
| `OQ-C02-001` archive variants beyond required file/folder/ZIP | `C06` | `C06 PASS` |
| `OQ-C02-002` application encryption at rest/key recovery | `C15` | `C15 PASS` |
| `OQ-C02-003` target corpus/performance profile | `C16` | `C16 TECH PASS` |
| `OQ-C02-004` numeric RPO/RTO/retention | `C15` | `C15 PASS` |

Деталі та чинні обмеження: `docs/architecture/open-questions.md`. Ці питання
не приховують вибір UI, DB, IDs, workspace, storage або connection model і не
блокують design application contracts у C03.

## Privacy та зовнішні джерела

Git містить код, правила, schemas, порожні/вигадані examples і design.
Матеріали справ, XLSX/PDF/DOCX/P7S, contacts, bank data, OAuth/DPAPI/secrets,
runtime DB/logs і generated case maps залишаються поза Git.

Старі CaseFlow/CMSD каталоги й protected case roots залишаються read-only.
`D:\CMSD\offline_bundle` залишається захищеним support asset; C02 його не
читає, не копіює й не змінює.

## Transition

Architecture gate C02 дає C03 достатні рішення для commands, queries, DTOs,
ports, Unit of Work і versioned local API. Фактичне розблокування наступного
controller package після `TECH PASS` потребує окремого `GITHUB SYNCED`; цей
статус не є дозволом на commit/push і не виконує їх автоматично.
