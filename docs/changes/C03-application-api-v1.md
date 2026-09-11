# VARTA C03 — application services, ports і local API v1

```yaml
change_id: VARTA-C03
status: TECH_PASS
baseline: b41a1ac6d43c1fb11af3356327ce043e5ce6693d
branch: codex/stabilize-baseline
vertical_slice: contacts
scope:
  - typed application commands, queries, DTOs and service errors
  - repository, Unit of Work, storage, job, clock and ID ports
  - short-lived SQLite UoW adapter with explicit commit/rollback
  - /api/v1 status and contacts HTTP contract
  - explicit unversioned contacts compatibility adapter
  - unchanged contacts-card UX using versioned routes
  - architecture, unit, integration, HTTP and runtime tests
out_of_scope:
  - intake and managed-originals implementation
  - Evidence Map services or projection
  - complete C04 SQLite lifecycle, busy, migration and recovery gates
  - broad C12 UI/security migration
  - commit, push, publication, release or remote changes
privacy: synthetic fixtures only; no case materials or real identifiers
originals_impact: none
```

## Реалізована boundary

Contacts проходять один шлях:

```text
browser або compatibility caller
  -> stdlib HTTP transport validation
  -> ContactService command/query
  -> ContactRepositoryPort у short-lived Unit of Work
  -> SQLite adapter і explicit transaction
  -> detached DTO та stable HTTP envelope
```

Handler більше не передає raw JSON у repository і не викликає contacts
repository напряму. Request-shape errors (`request_validation_error`) та
domain/application errors (`validation_error`) розрізняються. Missing і
uniqueness conflict мають стабільні `404`/`409` responses.

## Verification evidence

| Gate | Result |
|---|---|
| C02 dependency | `b41a1ac`, C02 `DONE`, C03 `READY`, C02 architecture tests `8 passed` |
| New C03 tests | application fake ports, real SQLite, architecture and HTTP contracts |
| Full pytest | `123 passed in 16.54s` |
| Ruff | `All checks passed` for `case_docket`, `caseflow`, `tests` |
| mypy | no issues in `36` source files |
| compileall | passed for `case_docket` and `caseflow` |
| HTTP contract | status, success, request/domain validation, not-found, route-not-found and conflict passed |
| Compatibility/restart | legacy create plus v1 read-back after server restart passed |
| Browser runtime | fresh start, contacts create/edit/reload, seven role options and zero console errors passed |
| Startup race | parallel legacy status + v1 context regression passed after pre-thread DB bootstrap |
| Git whitespace | working and cached `git diff --check` passed; staged scope empty |
| Privacy | 22 C03 paths scanned; no secrets, case numbers, IBAN or prohibited artifacts; only `example.invalid` emails |

## Scope separation

П’ять controller files були modified до старту C03 і залишені без C03 edits:

- `docs/interactive/varta-chat-roadmap.html`;
- `docs/roadmap-controller.md`;
- `tests/test_roadmap_controller.py`;
- `tools/roadmap_controller/browser_smoke.cjs`;
- `tools/roadmap_controller/server.py`.

Ignored `tmp/c03-browser-*`/pytest roots містять лише synthetic runtime QA.
Server processes зупинені; sandbox відхилив recursive cleanup, тому ці каталоги
не трактуються як source, staged scope або package artifact.

## Transition gate

`PASS`: реальний contacts vertical slice проходить application layer і
versioned API, pattern має inward ports та explicit UoW і перевірений на fake
ports, real SQLite, HTTP, restart та видимому browser surface. C03 не відкриває
і не починає C04 без окремого controller transition.
