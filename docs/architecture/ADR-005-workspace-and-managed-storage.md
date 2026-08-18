# ADR-005: Multi-case workspace and managed storage

| Metadata | Value |
|---|---|
| Status | `APPROVED` |
| Version | `v1.0` |
| Decision date | `2026-08-18` |
| Owner | `C02` |

## Контекст

VARTA має підтримувати кілька справ без окремої копії застосунку/БД для
кожної. Водночас користувач повинен працювати в передбачуваному контексті
однієї активної справи. Legacy runtime використовує `.caseflow` і каталоги,
які не відповідають цільовому immutable storage contract. Мовчазне rename або
часткова міграція може втратити зв'язок із файлами.

## Рішення

Один локальний **workspace** містить одну SQLite database та багато справ.
Browser session має нуль або одну active case; це presentation preference,
а не глобальний domain key. Commands/queries/jobs завжди отримують target IDs
явно, тому background processing не залежить від активної вкладки UI.

Цільовий managed root:

```text
<workspace>/.varta/
├── database/
│   └── varta.sqlite3
├── originals/
├── working/
├── derived/
├── reports/
├── exports/
├── logs/
├── quarantine/
└── temp/
```

Zone rules:

- `originals` — immutable, content-verified copies; ніколи не
  overwrite/rename in place;
- `working` — per-run staging, не evidence і не source of truth;
- `derived` — registered reproducible artifacts із source/run provenance;
- `reports`/`exports` — projections, не editable authority;
- `quarantine` — керований статус обробки, не твердження про шкідливість;
- `temp` — disposable only after recorded operation/reconciliation;
- `logs` — local operational data без secrets та з privacy minimization.

SQLite зберігає лише relative managed paths. Physical addressing originals
використовує opaque `file_id`/storage key; literal source name, source path і
людиночитне транслітероване managed name є metadata/representation. Same-name
different-bytes і same-bytes different-provenance не перезаписують один
одного.

`.varta` є цільовим runtime namespace. Чинна `.caseflow` залишається
compatibility source до read-only inventory, idempotent import,
reconciliation та explicit switchover. VARTA не робить silent rename, не
видаляє legacy state й не змінює зовнішні CaseFlow/CMSD каталоги.

## Відхилені альтернативи

1. **Одна DB/workspace на одну справу як обов'язкова модель.** Ускладнює
   cross-case contacts/search, update та backup без потреби.
2. **Одна global active case у DB.** Створює race між UI, CLI та workers.
3. **Користувацькі names/paths як physical keys.** Небезпечно для Unicode,
   collisions, rename та provenance.
4. **In-place `.caseflow` -> `.varta` rename.** Не дає reconciliation/rollback.
5. **Зберігати originals поруч із exports або source tree.** Розмиває
   immutability й privacy boundary.

## Наслідки

Workspace backup/restore охоплює DB та всі registered zones. Один workspace
може рости, тому scale/retention перевіряються окремими gates. UI повинен
показувати active case й вимагати explicit context для mutations. Filesystem
operations потребують staged finalize/reconciliation, бо SQLite і filesystem
не мають спільної транзакції.

## Вплив на міграцію

- C02 затверджує target layout, але не переносить жодного runtime файла;
- `C05` реалізує safe managed-storage primitives і zones;
- `C07` реалізує multi-case bootstrap/active-case contract;
- `C09` виконує read-only `.caseflow` inventory/import/reconciliation;
- `C15` доводить coordinated backup/restore та update path;
- поточний `<workspace>/.caseflow/varta.sqlite3` залишається фактом legacy
  implementation до відповідного migration gate.

## Пов'язані рішення

- [ADR-002](ADR-002-source-of-truth.md)
- [ADR-003](ADR-003-migrations-backup-and-restore.md)
- [ADR-004](ADR-004-identity-and-cardinality.md)
