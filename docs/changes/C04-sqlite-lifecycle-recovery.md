# C04 — SQLite transactions, migrations і recovery foundation

| Field | Value |
|---|---|
| Task | `C04` |
| Dependency | `C03` |
| Baseline HEAD | `94cf2958d0e9045913544fa86688a1c04e377a43` |
| Branch | `codex/stabilize-baseline` |
| Scope | SQLite connection/UoW, migrations, compatibility, DB-only backup/restore |
| Originals impact | none |
| Case data | none; tests use synthetic values only |
| Remote actions | none |

## Реалізовано

- централізований `SQLiteConnectionFactory` із verified FK, WAL,
  `busy_timeout`, synchronous й autocheckpoint policy;
- thread-owned connection per operation; shared repository connection видалено
  з `CaseFlowState`;
- `BEGIN IMMEDIATE` для commands, `BEGIN DEFERRED` для queries, explicit
  commit/rollback/close та single-use UoW;
- bounded `SQLiteBusyError` і concurrent reader/single-writer behavior;
- schema floor `2`, ceiling `6`, newer/invalid/gapped/name/checksum gates;
- atomic concurrent migration apply без `executescript` implicit commit;
- immutable `0001`/`0002` з additive scoped `0003`–`0006` indexes;
- DB-only SQLite online backup, restore-to-new-target, integrity/FK/schema
  verification та SHA-256 result;
- architecture guards: workers не мають direct SQLite/repository access.

## Verification evidence

| Gate | Result |
|---|---|
| C03 dependency regression | `18 passed` |
| C04 targeted matrix | `44 passed in 4.20s` |
| Full pytest | `138 passed in 18.07s` |
| Ruff | `All checks passed` |
| mypy | `Success: no issues found in 38 source files` |
| compileall | passed for `case_docket` and `caseflow` |
| Git whitespace | passed; only line-ending warnings on existing mixed files |
| Wheel | offline build passed; `varta-0.1.0-py3-none-any.whl`, 165116 bytes, SHA-256 `1C46F375E4E3DEB80E6F1CDD17F08C57E3221471FBFB835B08089A2859299E66` |
| Installed package | isolated import path, SQL `0001`–`0006`, schema `6`, backup/restore integrity `ok`, synthetic read-back passed |

Перший `pip wheel` run вичерпав timeout під час pip version-check до PyPI й не
створив artifact. Повторний обов’язковий gate виконано без мережі з
`PIP_DISABLE_PIP_VERSION_CHECK=1`, `--no-index` і `--no-build-isolation`; сам
setuptools/wheel build завершився за секунди. No commit, push, publication,
release, tag, merge або remote mutation є частиною C04.

## Rollback/recovery boundary

Schema evolution forward-only; `0001`/`0002` не змінені. Code rollback
дозволений лише для binary, що підтримує schema 6. Data/schema rollback —
restore consistent completed snapshot, не down migration. C04 snapshot містить
лише SQLite; coordinated managed-filesystem manifest, completion marker,
retention та activation належать `C15`.

## Excluded

- managed storage та immutable originals (`C05`);
- intake flow (`C06`);
- evidence application services (`C08`);
- durable job/worker lifecycle і versioned result finalization (`C10`);
- UI зміни;
- full SQLite+filesystem recovery/package/update orchestration (`C15`).
