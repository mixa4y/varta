# VARTA architecture

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Version | `v1.0` |
| Date | `2026-08-18` |

Цей каталог містить approved target architecture VARTA та успадковані
деталізовані drafts. Архітектурний approval не означає, що відповідний код
уже реалізований.

## Approved baseline

- modular local-first Python application;
- embedded browser UI на explicit loopback;
- SQLite як єдине writable structured source of truth;
- managed filesystem як authoritative storage registered bytes;
- immutable originals і reproducible derived artifacts;
- application-service boundary для HTTP, CLI, workers та adapters;
- short-lived SQLite Unit of Work per application operation;
- isolated workers без shared/direct repository connection;
- one multi-case workspace, zero/one active UI case;
- `.varta` target із контрольованим read-only `.caseflow` transition;
- Notion поза runtime, docs workflow, integrations і source of truth.

## Dependency direction

```text
presentation -> application -> domain
                      |
                      v
             infrastructure ports
```

`domain` не залежить від presentation/infrastructure. Browser assets не
імпортують Python repository/SQLite. Workers повертають result manifests, які
валідує/finalizes application service.

## Canonical decision set

Див. [`architecture-decision-log.md`](architecture-decision-log.md),
[`technical-specification.md`](technical-specification.md) і
[`open-questions.md`](open-questions.md).

## Implementation contracts

- [`local-api-v1.md`](local-api-v1.md) — versioning, contacts application
  boundary, stable envelopes і compatibility policy, реалізовані у C03.
- [`sqlite-lifecycle.md`](sqlite-lifecycle.md) — C04 per-operation UoW,
  migration compatibility і DB-only recovery foundation.
- [`managed-storage.md`](managed-storage.md) — C05 layout v1, streaming
  immutable originals, collision policy та DB/filesystem reconciliation.

## Legacy detail documents

Data model, reports, naming, matching, signatures та integrations залишаються
деталізованими `DRAFT`/target documents. Якщо вони суперечать `APPROVED` ADR,
чинним є ADR. Їхні невирішені implementation details мають owner stage у
`open-questions.md`; UI/source-of-truth/workspace/ID/UoW рішення більше не є
open.

## Security and privacy

Case materials, registers, signatures, secrets, runtime DB, logs і generated
maps не входять до Git. External adapters optional/disabled by default і не
змінюють local authority. Originals не змінюються під час міграції або тестів.
