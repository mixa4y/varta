# C06 — file, folder і ZIP intake до SQLite

| Field | Value |
|---|---|
| Task | `C06` |
| Dependency | `C05` |
| Baseline HEAD | `de75ab041b8173b2fba64f06cce6dee374f01533` |
| Branch | `codex/stabilize-baseline` |
| Scope | application intake, top-level ZIP, immutable storage, SQLite inventory, API/CLI |
| Originals impact | none outside synthetic repo-local test workspaces |
| Case data | none; fixtures are explicitly synthetic |
| Remote actions | none |

## Реалізовано

- additive migration `0008_intake_batches` з `intake_contexts`,
  `import_batches`, per-entry provenance, append-only batch/entry histories,
  immutable inventory triggers та status/source indexes;
- typed `SQLiteIntakeRepository` у short-lived UoW; batch створюється до
  enumeration, а per-entry transition/finalize не тримає long DB transaction;
- application `IntakeService` з file/folder/top-level-ZIP flow, explicit
  accepted/duplicate/failed/skipped, partial batch, same-key replay/conflict і
  SQLite-only inventory DTO;
- C05 storage bridge із окремим actual materialization path та literal
  provenance path, що дозволяє безпечно stream-ити ZIP member з opaque temp;
- deterministic folder traversal без symlink/reparse follow, source
  fingerprints і unchanged-source verification;
- malicious/traversal ZIP reject, case-insensitive duplicate member policy,
  zero-byte support, corrupt/encrypted/nested/unsupported archive policy;
- distinct immutable object/provenance для same bytes під іншим path;
- versioned multipart `POST /api/v1/intake`, SQLite inventory/detail GET та
  `varta-intake` CLI над тим самим application service;
- fresh runtime DB у `.varta/database`; existing legacy `.caseflow` DB
  використовується in place без copy/move до C09/C15; одночасна наявність обох
  DB дає explicit conflict замість silent dual writable authority.

## Verification evidence

| Gate | Current result |
|---|---|
| C05 dependency preflight | `34 passed` before C06 changes |
| C05 regression after provenance bridge | `16 passed` |
| C06 core file/folder/ZIP/restart/archive matrix | `8 passed` |
| Versioned local HTTP upload/replay/restart smoke | `1 passed` |
| CLI add/inventory/failure contract | `2 passed` |
| Fresh schema smoke | migrations `[1,2,3,4,5,6,7,8]`; five intake tables present |
| C06 + API/C03/C04/C05/architecture targeted matrix | `69 passed in 11.74s` |
| Full pytest | `185 passed` (final rerun `19.34s`) |
| Ruff | `All checks passed` for `case_docket`, `caseflow`, `tests`, `tools` |
| mypy | `Success: no issues found in 50 source files` |
| compileall | passed for `case_docket`, `caseflow`, `tests`, `tools` |
| Offline wheel | `varta-0.1.0-py3-none-any.whl`, 202376 bytes, SHA-256 `F53C31E522F11FCFDC9F5DE0EDBEE481896DE86DF50C6FC6EF9062A524591355` |
| Installed-package smoke | isolated import from installed target; entry point present; SQL `0001`–`0008`; file intake/source unchanged/restart inventory/SQLite `integrity_check=ok` passed |
| Privacy/whitespace | 35 C06-owned paths scanned: zero prohibited extensions, high-risk/case-specific matches або trailing whitespace; `git diff --check` passed with line-ending warnings only |

Проміжний combined targeted run мав `63 passed, 2 failed`: обидва failures
були stale C04 assertions, що вважали version `8` future і перелічували
catalog лише до `7`. Assertions оновлено на application ceiling `8`/future
`9`; final targeted run має `69 passed`.

Перший full run мав `183 passed, 1 failed`: закритий `OQ-C02-001` утратив у
registry row explicit owner/gate, яких вимагав architecture test. Closed table
отримала `C06`/`C06 PASS`; isolated rerun і фінальний full `185 passed`
зелені. Перший `pip wheel` frontend run вичерпав 180-second timeout без
artifact; локальний `setuptools.build_meta` backend створив wheel за 2.9s,
після чого isolated install/runtime smoke пройшов. Failures/timeout не
маскувалися як success.

## Archive decision closure

`OQ-C02-001` закрито contract `docs/architecture/intake-v1.md`: required v1
capability — file/folder/top-level ZIP; nested ZIP не expands, encrypted member
failed, duplicate path skipped, corrupt/traversal failed, інші archive formats
потребують окремого adapter/capability. Source archive не змінюється.

## Authority і recovery boundary

Inventory після restart формується тільки SQLite query. Source input, managed
filesystem scan, XLSX register і JSON index у query path відсутні. C05
reconciliation лишається authority для prepared/finalized original crash
states. C06 same-key retry повертає persisted non-terminal/terminal batch без
silent resume; фізичний retry використовує new key і створює explicit
duplicate provenance, якщо bytes збігаються.

## Excluded

- case detection, `intake_case_id`, active case та document-role workflow (`C07`/`C08`);
- legacy `.caseflow`/XLSX inventory/import/switchover (`C09`);
- durable processing jobs (`C10`);
- full visual intake/review UI (`C12`/`C13`);
- coordinated backup/restore, retention та DB-path switchover (`C15`);
- commit, push, publication, release, tag, merge або remote mutation.

П'ять baseline changes у roadmap controller/companion залишено поза C06
ownership. C06 не читав, не переміщував і не змінював зовнішні CaseFlow/CMSD
каталоги чи матеріали справ.
