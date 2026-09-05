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
  лише `evidence_map_exports`. Окремий test-only handle
  `synthetic://r04/consumer-readiness/v1` створює ізольовану тимчасову SQLite,
  не приймає шлях або case ID реальної справи та виконує фінальний local smoke
  через новий `SQLiteUnitOfWorkFactory` без generated case artifacts.
- `tests/test_evidence_map_export_r03.py`: valid audit restart, idempotency,
  hash conflict і invalid-hash rollback.

Усі значення fixture є synthetic. Фінальний local smoke використовує тільки
окремий safe synthetic handle; реальні case roots не читаються, їхні значення
не логуються, а generated artifacts не створюються.

## Поточна перевірка

- R02/R03/R04 targeted matrix: `12 passed`.
- Повний pytest suite: `233 passed`.
- Ruff для `case_docket`/`tests`, compileall та `git diff --check`: passed.
- Privacy/path scan: case-specific values, user paths і secrets не знайдені.

## Gate

R04 TECH PASS є обґрунтованим лише після targeted/full test run, privacy/path
scan і `git diff --check`. Git checkpoint, commit, push та C11 unlock не є
частиною цього turn.
