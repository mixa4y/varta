# VARTA-001 — формалізація повного контракту Evidence Map

```yaml
change_id: VARTA-001
title: Формалізувати case profile та Evidence Map snapshot schema 1.1.0
status: IMPLEMENTED
objective: >-
  Замінити довільні additionalProperties повним privacy-safe контрактом для
  максимально заповнених карток справи, проваджень, учасників, файлів,
  документів, подій, тверджень, зв’язків, джерел і review decisions.
scope:
  - case-profile.schema.json 1.1.0
  - map-data.schema.json 1.1.0
  - SQLite migration 0002_evidence_map_domain.sql
  - privacy-safe templates
  - embedded Evidence Map template payload
  - blueprint contract
  - positive and negative schema tests
out_of_scope:
  - real case records
  - projection service
  - integrated UI rendering of every new field
  - sealed export generator
source_of_truth: SQLite and immutable local filesystem
affected_contracts:
  - VARTA case profile JSON Schema
  - VARTA Evidence Map snapshot JSON Schema
  - VARTA SQLite evidence domain
privacy_impact: >-
  Repository examples remain empty or fictional; real profiles and generated
  maps stay outside Git.
originals_impact: none
decision_dependencies:
  - SQLite remains the writable source of truth
  - case-specific facts are not embedded in universal code
migration: >-
  Profiles and snapshots using schemaVersion 1.0.0 must be projected or
  explicitly upgraded to 1.1.0. Silent acceptance under the old version is
  not allowed. SQLite workspaces apply versioned migration 0002 after 0001.
rollback: >-
  Restore the 1.0.0 schemas, templates, embedded payload and blueprint as one
  consistent set. No runtime case data is modified by this contract change.
tests:
  - JSON Schema meta-validation
  - privacy-safe template validation
  - embedded template validation
  - rejection of unformalized case-profile fields
  - rejection of filename-only case-number evidence
  - rejection of confirmed claims and relations without evidence basis
  - creation and constraints of evidence-domain SQLite tables
  - append-only review decisions
acceptance:
  - all formal collections are present in the snapshot template
  - unknown profile fields fail validation
  - confirmed facts require non-empty evidence basis
  - full pytest, Ruff, mypy and compileall gates pass
evidence:
  - 82 pytest tests passed
  - Ruff passed
  - mypy passed for case_docket and caseflow
  - compileall passed
known_limits:
  - application services for the new SQLite entities remain pending
  - deterministic projection from SQLite remains pending
  - UI does not yet render every schema 1.1.0 field
```

## Результат

Case profile тепер формально описує bootstrap, expected proceedings,
root selector, key-document rules, relation hypotheses, export defaults і
validation rules.

Evidence Map snapshot тепер має окремі типізовані колекції:

```text
proceedings
actors
files
documents
events
claims
relations
sourceReferences
reviewDecisions
exclusions
```

Невідомі факти залишаються `null` або порожніми. Вони не замінюються
припущеннями для формального заповнення картки.
