# R04 — C11 consumer readiness evidence

## Результат

R04 доводить populated synthetic SQLite → application queries →
`EvidenceMapSourceDTO` contract. C11 generator не змінювався і не запускався.

## Докази

- `tests/test_evidence_map_source_r02.py`: повний synthetic graph, page-size-1
  pagination, case isolation, missing-provider guard, repeated-page guard,
  restart і insertion-order independence.
- `tests/test_r04_consumer_readiness.py`: golden contract, populated counts,
  revision/data-cutoff read-back та точний DB diff; після valid audit змінюється
  лише `evidence_map_exports`; source boundary блокує missing source basis,
  broken subject/endpoint/source/file references, а SQLite відхиляє unsupported
  classifications. Окремий test-only handle
  `synthetic://r04/consumer-readiness/v1` створює ізольовану тимчасову SQLite,
  не приймає шлях або case ID реальної справи та перевіряє synthetic restart
  через новий `SQLiteUnitOfWorkFactory` без generated case artifacts.
- `tests/test_evidence_map_export_r03.py`: valid audit restart, idempotency,
  hash conflict і invalid-hash rollback.

Усі значення fixture є synthetic. Матеріалізація фактичної справи з повної
Airtable base та immutable local corpus не є consumer-contract gate R04: її
виділено в окремий R05, де real-case values, paths і local SQLite залишаються
поза Git.

## Поточна перевірка

- Професійний перепрогін 2026-09-08 дав актуальні результати: R04 golden
  contract — `9 passed`; R01 profile prerequisite — `4 passed`; R02 source
  prerequisite — `6 passed`; R03 export-audit prerequisite — `13 passed`.
- Fresh mypy виявив reuse однієї loop-variable між heterogeneous
  `CaseScopedSourceItem[T]`; type-specific renames усунули defect без зміни
  runtime logic. Exact-scope mypy, повторні R04/R02 tests, Ruff lint,
  Ruff format-check і compileall пройдені окремими checkpoints §3.7.
  Historical Luna/low результати не використовуються як transition evidence.
- Synthetic restart перевірений через окремий safe handle; реальну database не
  створювали й не використовували як прихований prerequisite readiness gate.
- Повний authorized Airtable/corpus → SQLite import, reconciliation і real-case
  restart smoke передані R05; жодні case values, paths або artifacts не записані
  до report чи Git-owned fixtures.

## Gate

R04 transition gate закритий повним synthetic SQLite/application consumer
contract: pagination, order independence, source-basis/reference negatives,
restart та export-audit DB diff підтверджені. Реальна case database належить
R05 і не блокує C11 consumer readiness. Git checkpoint і push виконуються лише
за окремою прямою командою.
