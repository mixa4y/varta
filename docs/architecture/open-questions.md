# VARTA architecture open decisions

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Version | `v1.0` |
| Date | `2026-08-18` |
| Owner | `C02` maintains routing; listed stages own closure |

Цей реєстр не перетворює майбутні implementation details на blocker для
`C03`. Кожне справді відкрите рішення має стабільний ID, чинне обмеження,
owner stage і gate закриття. Нове питання додається сюди або до нового ADR;
воно не залишається безстроковим bullet у legacy draft.

## Open decisions

| ID | Відкрите рішення | Чинне обмеження до рішення | Owner stage | Must close before |
|---|---|---|---|---|
| `OQ-C02-002` | Application-level encryption at rest і key-recovery model | Не заявляти encryption at rest; покладатися на Windows account/ACL і чинне secret storage; plaintext workspace не можна видавати за encrypted | `C15` | `C15 PASS` |
| `OQ-C02-003` | Цільовий corpus/volume/performance profile | Не вигадувати числа; `C16` спершу версіонує acceptance profile, потім вимірює intake/query/UI/worker/export/backup | `C16` | `C16 TECH PASS` |
| `OQ-C02-004` | Числові RPO/RTO, backup retention і media policy | Діє `ADR-003`: тільки consistent completed backup і restore у new/empty target; жодної обіцянки RPO/RTO без тесту | `C15` | `C15 PASS` |

## Routed legacy questions

Питання з успадкованих `DRAFT` документів не є прихованими рішеннями:

| Тема | Owner stage / package | Gate або disposition |
|---|---|---|
| application package, DI/config і API types | `C03` | `C03 PASS` |
| SQLite busy/transaction/online-backup details | `C04` | `C04 PASS`; architecture fixed by `ADR-003`/`ADR-007` |
| storage collisions, retention of working/derived | `C05`, `C15` | respective PASS |
| archive parsing and intake statuses | `C06` | `C06 PASS`; closed in `intake-v1.md` |
| case bootstrap and active-case persistence | `C07` | `C07 PASS`; workspace model fixed by `ADR-005` |
| evidence cardinalities, history and personal-data minimization | `C08`, `C16` | `C08 PASS` for model; `C16` privacy gate |
| legacy adapters and external-data classes | `C09`, `C16` | `C09 PASS` plus final privacy gate |
| retries, queue and processor result contracts | `C10` | `C10 PASS` |
| Evidence Map/report fields and review UX | `C11`, `C13`, `C14` | respective projection/workflow/export PASS |
| package/update, encryption and recovery | `C15` | `C15 PASS`; see `OQ-C02-002`/`004` |
| fixtures, anonymization and performance targets | `C16` | `C16 TECH PASS`; see `OQ-C02-003` |
| OCR/text coordinates | `P01` | `P01 PASS` |
| КЕП formats/tools/protocol retention and attachment parsing | `P02` | `P02 PASS` |
| matching libraries/threshold calibration | `P04` | `P04 PASS` |

## Closed by C06

| ID | Owner | Closing gate | Рішення |
|---|---|---|---|
| `OQ-C02-001` | `C06` | `C06 PASS` | C06 v1 supports file/folder/top-level ZIP. Nested ZIP is stored but not expanded; encrypted member is explicit failed; duplicate member path is explicit skipped; corrupt/traversal is explicit failed; all other archive formats require a separately versioned adapter/capability. Source archive remains read-only. See `intake-v1.md`. |

## Closed by C02

| Питання | Рішення |
|---|---|
| UI technology | embedded local web UI on loopback; `ADR-001`/`ADR-006` |
| Notion | outside product, docs workflow, integrations and source of truth |
| Python baseline | Python `3.12`, already fixed by `pyproject.toml` |
| SQLite connection ownership | short-lived UoW/connection per application operation; `ADR-007` |
| identifiers/cardinality | opaque internal IDs, separate external refs, many-to-many; `ADR-004` |
| workspace shape | one multi-case DB/workspace, one active UI case, `.varta` target; `ADR-005` |
| schema rollback | forward-only migrations + consistent restore, no destructive down; `ADR-003` |
