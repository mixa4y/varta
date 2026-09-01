# C07 — multi-case workspace і case bootstrap

| Field | Value |
|---|---|
| Task | `C07` |
| Dependency | `C06` |
| Baseline HEAD | `72ff4c9e524dca3b0f11c214ebc99d4d1489d7b0` |
| Branch | `codex/stabilize-baseline` |
| Scope | workspace service, bootstrap candidates/review, memberships, local API v1 |
| Originals impact | none; originals only read through existing C06/C05 flow |
| Case data | none; tests and docs are explicitly synthetic |
| Remote actions | none |

## Реалізовано

- additive schema `0009_case_workspace_bootstrap`;
- atomic C06 accepted-entry -> temporary `intake_case_id` pending hook;
- typed workspace/case/proceeding repository і application service;
- deterministic raw candidate extraction та case-number normalization;
- filename/folder evidence restriction, zero/one/multiple state machine і
  explicit manual confirmation;
- conflict-safe normalized-number/external-reference registration;
- many-to-many file case/proceeding memberships;
- active case як session-scoped presentation preference;
- versioned `/api/v1/workspace` queries/commands без повного UI;
- restart, audit/status history й stable response contracts.

## Межі

- full workspace/review UI належить C12/C13;
- evidence-domain documents/events/claims та їхні services належать C08;
- legacy XLSX/`.caseflow` adapter належить C09;
- commit, push, publication, release та remote changes не виконуються цим
  package.

## Verification evidence

| Gate | Current result |
|---|---|
| C07 required matrix | `7 passed in 4.64s` |
| Full pytest | `193 passed in 28.53s` |
| Ruff | `All checks passed!` |
| mypy | `Success: no issues found in 53 source files` |
| compileall | passed for `case_docket`, `caseflow`, `tests`, `tools` |
| C06 -> C07 upgrade | existing accepted file backfilled to explicit pending bootstrap |
| Restart/API | bootstrap, confirmed case membership та active preference persisted |
| Offline wheel | `varta-0.1.0-py3-none-any.whl`, 222923 bytes, SHA-256 `1CBA30809E4784D457C1D08594DDDF7C88054DAD3C765100736E6F815AA6FF32` |
| Installed-package smoke | isolated import, schema ceiling/current `9`, required C07 tables present, `integrity_check=ok` |

Перший optional `pip wheel` frontend run вичерпав 180-second timeout без
artifact. Перевірений локальний fallback
`setuptools.build_meta.build_wheel(...)` створив final wheel за 3.4s; wheel містить
application/repository workspace modules і migration `0009`, після чого
isolated install/runtime smoke пройшов. Timeout не класифіковано як success.
