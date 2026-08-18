# VARTA managed workspace structure

| Metadata | Value |
|---|---|
| Status | `APPROVED TARGET` |
| Version | `v1.0` |
| Date | `2026-08-18` |
| Decision | `ADR-005` |

## Target workspace

```text
<workspace>/
└── .varta/
    ├── database/
    │   └── varta.sqlite3
    ├── originals/
    │   └── <storage_partition>/<file_id>/
    ├── working/
    │   └── <processing_run_id>/
    ├── derived/
    │   └── <source_file_id>/<artifact_type>/
    ├── reports/
    │   └── <case_id>/<report_run_id>/
    ├── exports/
    │   └── <export_id>/
    ├── logs/
    ├── quarantine/
    └── temp/
```

Одна database містить багато справ. UI може мати нуль або одну active case,
але це presentation context; commands/queries/jobs передають IDs явно.

## Zone rules

### `originals`

Незмінні байтові копії отриманих файлів. Literal source name/path зберігається
в SQLite; physical path будується з opaque storage key/`file_id`. Застосунок
не overwrite/rename-ить оригінал.

### `working`

Per-run staging. Це не evidence/source of truth; cleanup можливий лише після
recorded finalize/failure/reconciliation.

### `derived`

OCR, normalized text, page images, transcripts та інші registered artifacts.
Кожен має source, algorithm/tool version, parameters, hash і run provenance.

### `reports` and `exports`

Відтворювані projections. Export не змінює internal state і не приймає edits
назад без explicit import use case.

### `quarantine`, `temp`, `logs`

`quarantine` — operational status, не висновок про malicious/fraudulent
content. `temp` disposable лише за safe cleanup contract. Logs локальні,
мінімізовані й без secrets.

## Constraints

- SQLite зберігає relative paths від managed root.
- ПІБ, case number, display name або filename не є physical key.
- Same-name/different-bytes і same-bytes/different-provenance не overwrite.
- Backup узгоджує SQLite й registered files за `ADR-003`.
- `.caseflow` не перейменовується in place і не видаляється автоматично.

## Current compatibility state

Чинний code path `<workspace>/.caseflow/varta.sqlite3` не змінено C02. `C05`
реалізує target zones; `C09` робить read-only legacy reconciliation; `C15`
доводить migration/backup/restore. Цей target document не є доказом, що
physical migration уже виконано.

## Open decisions

| ID/question | Owner stage | Closing gate |
|---|---|---|
| Retention/cleanup для `working`/`derived` | `C05`, `C15` | respective PASS |
| `OQ-C02-004` backup retention/RPO/RTO | `C15` | `C15 PASS` |
