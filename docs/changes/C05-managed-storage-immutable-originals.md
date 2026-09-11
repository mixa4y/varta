# C05 — managed storage та immutable originals

| Field | Value |
|---|---|
| Task | `C05` |
| Dependencies | `C02`, `C04` |
| Baseline HEAD | `3652ae8b05c93d239aa3e0b1eb47f64a8b926aca` |
| Branch | `codex/stabilize-baseline` |
| Scope | layout v1, streaming originals, SQLite metadata, collision/crash reconciliation |
| Originals impact | none outside synthetic repo-local test workspaces |
| Case data | none; fixtures are explicitly synthetic |
| Remote actions | none |

## Реалізовано

- `case_docket.storage` з versioned `.varta/layout.json` і zones `database`,
  `originals`, `staging`, `working`, `derived`, `reports`, `exports`, `logs`,
  `backups`, `quarantine`, `temp`;
- Windows-safe literal relative path/archive validator із reserved-name,
  traversal, ADS, component-length та reparse-point guards;
- Windows extended-path source access для paths понад legacy `MAX_PATH`;
- canonical lowercase UUIDv4 `file_id` як opaque physical key; literal
  `original_name`/`source_relative_path` і optional `managed_name` зберігаються
  окремо й не входять до storage path;
- streaming source SHA-256/byte count, same-volume staging, staged/source
  rehash і source size/mtime stability check;
- exclusive file-id directory, atomic no-overwrite Windows rename, read-only
  finalized object і повторна hash/size verification;
- application `OriginalStorageService` поверх `StoragePort` і short-lived
  SQLite UoW; file copy не тримає DB transaction;
- additive migration `0007_intake_managed_storage` зі state/timestamps,
  case-insensitive unique storage references та immutable verified-metadata
triggers для registered provenance/identity та verified delete;
- duplicate-by-hash signal без content dedup або автоматичного злиття
  provenance/document roles;
- versioned recovery manifest і reconciliation для pre-DB, pre-finalize та
  post-finalize interruption, DB/file mismatch і orphan state;
- explicit locked/read, disk-full/write, collision, malformed/orphan та
  integrity failures без source mutation або silent success.

## Verification evidence

| Gate | Result |
|---|---|
| C02/C04 dependency preflight | `27 passed` |
| C05 core path/storage/crash matrix | `34 passed`; actual >260-character Windows path, malformed manifest і missing-reference tests включено |
| C05 + dependency/architecture targeted matrix | `55 passed` |
| Full pytest | `173 passed in 15.76s` |
| Ruff | `All checks passed` for `case_docket`, `caseflow`, `tests`, `tools` |
| mypy | `Success: no issues found in 46 source files` |
| compileall | passed for `case_docket`, `caseflow`, `tests`, `tools` |
| Git whitespace | `git diff --check` passed; лише baseline line-ending warning у controller JS |
| Offline wheel | `varta-0.1.0-py3-none-any.whl`, 181335 bytes, SHA-256 `05857CC3AAEE6ADA1697716DC8F8D24FD6378AC4BB78067C481B6D0C595D2B3B` |
| Installed-package smoke | isolated import from wheel target; SQL `0001`–`0007`; storage accept/read-only/SHA-256/SQLite state `verified` passed |

Перший full pytest після additive migration мав `170 passed, 1 failed`: один
legacy Airtable test hardcode-ив шість migrations. Assertion переведено на
`APPLICATION_SCHEMA_CEILING`; після додаткових malformed/missing recovery
tests фінальний full run має `173 passed`. Перший C05
targeted run мав один некоректний fixture, де numeric-only UUID `.upper()` не
створював case variant; fixture замінено UUID з hex letters, повторний run
зелений. Обидва failures були видимими й не маскувалися.

## Recovery and immutability boundary

Reconciliation автоматично відновлює DB link лише з валідного recovery
manifest, який був атомарно записаний після повної staged verification. Bytes
без manifest/provenance не adopt-яться. Missing/tampered registered object
отримує `reference_unavailable`/`mismatch`; service не repair/overwrite-ить
його source-копією. Verified original metadata та storage identity захищені
SQLite triggers, а filesystem object позначається read-only.

## Excluded

- file/folder/ZIP enumeration, `import_batch`, inventory UI/API (`C06`);
- legacy `.caseflow`/XLSX migration або switchover (`C09`);
- durable worker lifecycle (`C10`);
- coordinated SQLite + filesystem backup/restore, retention та activation
  (`C15`);
- commit, push, publication, release, tag, merge або інша remote mutation.

П'ять baseline changes у roadmap controller/companion залишено недоторканими
за ownership boundary. C05 не читав, не переміщував і не змінював зовнішні
CaseFlow/CMSD каталоги чи матеріали справ.
