# VARTA C01-02 — roadmap/controller baseline і handoff

```yaml
change_id: VARTA-C01-02
title: Зафіксувати атомарний roadmap/controller patch і C01 technical handoff
status: TECH_PASS
objective: >-
  Перетворити pre-existing roadmap/controller scope на exact logical patch із
  відтворюваним inventory, quality/privacy gates, package-data proof і
  synthetic HTTP/SQLite restart smoke.
scope:
  - canonical chat roadmap та interactive companion
  - localhost roadmap controller, catalog і browser smoke source
  - controller tests та operation/security documentation
  - Windows start/stop launchers
  - цей change record і exact manifest C01-02
out_of_scope:
  - зміни VARTA product architecture з C02
  - commit, push, PR, release або remote changes
  - матеріали справи й immutable originals
source_of_truth: docs/chat-roadmap.md для work packages; SQLite/filesystem для product data
affected_contracts:
  - C01-C16 та P01-P04 machine catalog
  - localhost controller execution and Git checkpoint state machine
privacy_impact: >-
  Runtime state залишається в ignored .varta; verification використовує лише
  synthetic workspace та вигадані contact data.
originals_impact: none
decision_dependencies: []
migration: none
rollback: >-
  Майбутній Git checkpoint має зберегти patch атомарним; C01 не видаляє й не
  reset-ить жодний pre-existing path.
tests:
  - full pytest
  - Ruff, mypy, compileall
  - controller targeted tests і syntax parsers
  - git diff checks
  - package-data wheel/install proof
  - tracked/staged/untracked privacy scan
  - synthetic HTTP/SQLite restart smoke
acceptance:
  - кожен final status path належить рівно одному C01 manifest
  - roadmap/controller files не розрізані на хибні незалежні hunks
  - усі mandatory gates зелені
  - C02 handoff не починає C02 і вимагає окремого GITHUB SYNCED
evidence:
  - 94 pytest tests passed
  - Ruff, mypy, compileall and Git whitespace gates passed
  - package-data wheel/install proof passed
  - synthetic HTTP/SQLite restart smoke passed and workspace was removed
  - privacy scan covered 147 tracked/untracked files with staged scope empty
  - manifest/status bijection is exact for 18 final paths
known_limits:
  - TECH PASS не є GitHub checkpoint або GITHUB SYNCED
  - Windows elevated sandbox не має credential основного користувача; тільки
    явно підтверджений Git checkpoint отримує turn-scoped dangerFullAccess
```

## 1. Controller-captured baseline

| Field | Exact value |
|---|---|
| Captured | `2026-08-11T23:37:51+00:00` |
| Branch | `codex/stabilize-baseline` |
| HEAD | `bc51a0095adb664c9bebd98764c101976f75e575` |
| Tracked working changes | `0` |
| Staged files | `0` |
| Expanded untracked files | `14` |
| Controller status SHA-256 | `7b7ebfd38705b6efc0e3f0d820d59a3554420b7e9686dc4877723682113ff6b5` |
| Index entries | `129` |
| Initial `.git/index` bytes | `13744` |
| Initial `.git/index` SHA-256 | `3c0c981661bee1c4414eb11656b1669423bf7695dd6abe348ca32363dbd1fe1c` |
| Initial unstaged/cached stat | both empty |

Live recapture before writing C01 records reproduced the supplied HEAD, branch
and controller status hash exactly. The expanded list contains twelve
roadmap/controller paths and two independent `.github` paths.

## 2. Logical patch map

| Order | Patch | Owner | Exact paths | Dependency/disposition |
|---|---|---|---:|---|
| 1 | `C01-01` repository diagram guidance | developer-experience | 4 including record/manifest | independent; separate checkpoint review |
| 2 | `C01-02` roadmap/controller | roadmap execution tooling | 14 including record/manifest | atomic feature over `bc51a00` |

There are no current dirty files owned by `typing/runtime`, `Airtable-to-SQL`,
`Evidence Map contracts`, or `contacts/API/UI`: those scopes are already in
HEAD `bc51a00`. Windows files in this dirty tree launch only the roadmap
controller and therefore remain in C01-02, not in product packaging P0-6.

## 3. Mixed-file review

No hunk-level split is safe or useful inside C01-02:

- `docs/interactive/varta-chat-roadmap.html` is simultaneously the static
  companion and live localhost surface served by the controller;
- `docs/chat-roadmap.md` defines both package semantics and the two-phase
  TECH PASS/GITHUB SYNCED protocol mirrored by the machine catalog;
- `tests/test_roadmap_controller.py` validates catalog, result parsing, state,
  HTTP security and the Windows allowlisted runtime staging as one acceptance
  suite;
- the four Windows wrappers are the documented entry/exit path for this exact
  controller, not a reusable product installer change.

Splitting those files would produce intermediate snapshots in which the UI,
catalog, server contract, launchers and tests disagree. All C01-02 paths are
therefore staged as whole files with explicit pathspecs. The only independent
scope is C01-01.

## 4. Exact C01-02 scope

| Path | Role | C01 stabilized SHA-256 |
|---|---|---|
| `START_ROADMAP.cmd` | double-click launcher | `cbcd9bc37e7dbd1bc8355a3abc1732d5edfb24906cc84340fe6c8707588a859a` |
| `STOP_ROADMAP.cmd` | double-click stop | `473f43eddd5e39bb39dc79e0efb5478873eea37ecb4e4ce263295325ed9f4723` |
| `docs/chat-roadmap.md` | canonical work-package roadmap | `6757e31a5b5dafc28b4db8944a006703443cdc2ab3c8efd8c25d1986213c317e` |
| `docs/interactive/varta-chat-roadmap.html` | static/live controller UI | `ab3431bd1a15d15e5699e73c87b74383656c389b2d1c142e3e0c3ca3e4ca6900` |
| `docs/roadmap-controller.md` | operation/security contract | `14ed9a41b9e2c74e8b17e8bcf635aa9514e22815093dca919d5011db469def06` |
| `tests/test_roadmap_controller.py` | integrated controller tests | `ab2484f4defda7634dec0b6aa9775194266cc897189895c573ca08da65d9a6da` |
| `tools/roadmap_controller/__init__.py` | package marker | `937f9f7ce97ecaa50dcd71ec4215a6ad18865ef34416edf16a3cc801e1ca9524` |
| `tools/roadmap_controller/browser_smoke.cjs` | Playwright smoke source | `b5071b72aff813cda9eeb9a331bfd2411d01a8b0d6d379c76a2b2e447873e437` |
| `tools/roadmap_controller/server.py` | localhost controller/state machine | `8d6b20e53249e6c7048f787731c793fa9f882ce2ff70a3358ab02ce80f022be6` |
| `tools/roadmap_controller/stages.json` | allowlisted 20-stage catalog | `cda517e91c59cf8888bb9ba1cced951d04f136d285e2c7c651a8b466ca34cd1e` |
| `tools/windows/start_varta_roadmap.ps1` | verified hidden-process launcher | `77168dc1fd18e61a9f6e84d054547e902a7e7d9f257e83195948f54dc525e8d2` |
| `tools/windows/stop_varta_roadmap.ps1` | authenticated local stop | `09fa3cca6fdcca9170d1a4cae96e8151b5c7761f92d141c221cb038eee1b0e7b` |
| `docs/changes/C01-02-roadmap-controller.md` | C01 record and handoff | refreshed at final gate |
| `docs/changes/manifests/C01-02-roadmap-controller.json` | exact manifest | self-listed; no recursive self-hash |

## 5. Important baseline hashes

These hashes verify that C01 did not modify established core contracts while
inventorying the new tooling.

| Path | SHA-256 |
|---|---|
| `AGENTS.md` | `d749b9a46c7dbbc4519a597d4930e7373821a3c78b821f23c9d647e4cff16ec6` |
| `PROJECT_STATUS.md` | `10a6dd539f25d5aba26ee06bd36e28072fb70912e105c1fd57e5e7347cc016da` |
| `pyproject.toml` | `7c69766493b2f7e903e0038eec343cc8049590a2b0ef34cdfb6676d1b1fd8098` |
| `docs/action-algorithm.md` | `5f2285724fb3b1885a093c3429dfd66edef64b09ece9c056050f7d29a2fe7807` |
| `config/airtable_schema.json` | `999bf83429efb3ac1b9f7e5561ba66aa6d93de090b3bd7aaa19b9da7d30647aa` |
| `0001_airtable_sql.sql` | `637cc4eb483032e49c3b64e1b534ccc566d59358df63bfef15cb2cba3868ccd2` |
| `0002_evidence_map_domain.sql` | `ce8b4ed3e65d379408caf3ae2f6a61d9f1f5aa4e18756215382ca045c09c36cb` |

## 6. Runtime/package-data boundary

`MigrationRunner` resolves its default directory beside
`case_docket/repository/migrations.py`. `pyproject.toml` explicitly delivers
`repository/migrations/*.sql`; the Airtable loader checks installed
`<sys.prefix>/config/airtable_schema.json`, and setuptools data-files delivers
that file there. The wheel gate must also confirm `caseflow/static/*` and
`caseflow/version.json`, because the local server reads them at runtime.

| Gate | Result |
|---|---|
| Source loader/package declarations | confirmed |
| Wheel archive entries | passed: 56 entries; both SQL files, Airtable schema, static UI and version manifest present |
| Installed-wheel repository bootstrap | passed: migrations `[1,2]`, catalog tables `9`, fields `127`, relations `38`, computed `12`; `claims` present |

## 7. Verification evidence

| Check | Command/scope | Result |
|---|---|---|
| Controller targeted suite | `pytest -q tests/test_roadmap_controller.py` with repo-local basetemp | `12 passed in 1.28s`; Git turn full-access override and ordinary-stage negative assertion included |
| Controller Ruff | `ruff check tools/roadmap_controller tests/test_roadmap_controller.py` | passed |
| Controller syntax | compileall, JSON parser, `node --check`, PowerShell parser | passed |
| Full pytest | `pytest -q` with repo-local basetemp | `94 passed in 7.75s` |
| Required Ruff | `ruff check case_docket caseflow tests` | passed |
| Required mypy | `mypy case_docket caseflow` | no issues in 26 source files |
| Required compileall | `compileall -q case_docket caseflow` | passed |
| Git whitespace | `git diff --check`; `git diff --cached --check`; untracked text scanner | passed; two initial blank EOF lines fixed, final findings zero |
| Privacy | 129 tracked, 0 staged, 18 untracked | passed with only triaged synthetic/semantic matches |
| HTTP/SQLite restart | two local server processes and one synthetic contact | page/API ready, SQLite created, contact persisted after restart, workspace removed |
| Manifest bijection | every final status path exactly once | 18 owned = 18 unique = 18 status; no missing/extra/duplicate |

The initial targeted run without `--basetemp` had six test bodies pass and six
fixture setup errors because the managed sandbox denied the system pytest temp
directory. Re-running the identical suite in `D:\VARTA\tmp` passed 12/12; the
first result is environmental evidence, not hidden as a code pass.

Після першого GitHub checkpoint виявлено окрему Windows-межу: звичайний
PowerShell успішно читав `gh` credential, але elevated sandbox запускав Git
turn під dedicated low-privilege user, де `gh auth status` повертав `401`.
Controller тому задає `sandboxPolicy.type=dangerFullAccess` лише для turn,
який створюється після окремого підтвердження **GitHub checkpoint**. Regression
test окремо доводить, що звичайний stage turn не отримує цей override і
залишається під базовим `workspace-write`.

## 8. Privacy scan record

The final scan read the union of `git ls-files` and
`git ls-files --others --exclude-standard`; staged paths were obtained from
`git diff --cached --name-only` and were empty. It covered 147 files: 129
tracked and 18 untracked. All 147 were text; there were zero binaries and zero
files over 5 MiB.

Recorded filename/path patterns:

- prohibited extensions: `xls/xlsx/pdf/doc/docx/p7s/sqlite/sqlite3/db/zip/rar/7z/tar/gz`;
- forbidden runtime paths: `.varta`, `.caseflow`, `map-data.json`,
  `state.json`, `server.log`;
- secret-like filenames: `.env`, `token`, `secret`, `credential`, `dpapi`;
- private path shapes: user-profile paths and numeric case-root-like paths.

Recorded content patterns:

- private-key headers, GitHub/OpenAI/Slack/Google/AWS token prefixes and JWTs;
- non-empty credential assignments for password/API key/client secret/access
  or refresh token;
- Ukrainian IBAN and compact phone shapes;
- case-number shapes, emails, absolute Windows paths and OAuth/DPAPI terms.

Zero-hit high-risk categories: prohibited extensions, forbidden runtime paths,
secret-like filenames, oversize/binary files, private keys, high-risk tokens,
JWTs, credential assignments, IBAN, user-profile paths and numeric case roots.

Triaged low-risk matches:

- 14 case-number-shaped lines in five tracked files are one schema-count false
  positive plus conspicuously synthetic repeated-digit and zero-valued
  fixtures; untracked files had zero case-number matches;
- email matches are `test@example.invalid` and the repository SSH URL
  `git@github.com:mixa4y/varta.git`;
- two compact-phone matches are digits inside a multipart boundary string;
- OAuth/DPAPI matches are denylist wording, documentation and implementation
  identifiers; no credential assignment matched;
- absolute paths are the canonical repository/support paths, an explicit
  `D:\Cases\example`, and generic `Program Files` probe locations; no user
  profile or case-root-like path matched.

No real case/contact/bank data was introduced or copied into C01 artifacts.

## 9. Synthetic HTTP/SQLite restart evidence

The smoke used a uniquely named directory below `tmp/`, no external source
files and one fictional contact (`example.invalid`). It started the VARTA
server as a separate process, performed HTTP checks and a contact write,
terminated it, started a new process on the same workspace and read the
contact back.

| Assertion | Evidence |
|---|---|
| Page | HTTP `200`, `text/html`, VARTA marker present |
| API readiness | `/api/status` HTTP `200`, JSON, `ok=true`, product `VARTA` |
| Write | `/api/contacts` HTTP `201` with synthetic payload |
| SQLite | `.caseflow/varta.sqlite3` created; migrations `[1,2]` |
| Restart read-back | API and direct SQLite each reported one contact |
| Cleanup | runtime, wheel/install and pytest synthetic directories absent after gate |

## 10. Handoff for C02

C02 receives HEAD `bc51a00` plus two explicit C01 logical patches. It may use
the roadmap as input only after C01 has `TECH PASS` and the separate GitHub
checkpoint reaches `GITHUB SYNCED`. This record does not approve or begin C02.

The C02 task must re-check live HEAD/status and then formalize the local-web,
source-of-truth and ADR package described in its own scope. It must not infer
that C01 approved unresolved architecture decisions merely because the
controller tooling is operational.
