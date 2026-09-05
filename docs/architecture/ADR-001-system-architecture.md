# ADR-001: Local-first system architecture

| Metadata | Value |
|---|---|
| Status | `APPROVED` |
| Version | `v1.0` |
| Decision date | `2026-08-18` |
| Owner | `C02` |

## Контекст

VARTA працює з чутливими документами, великими файлами, метаданими, хешами
та відтворюваними перевірками на локальному Windows-комп'ютері. Поточний
репозиторій поєднує універсальне Python-ядро CMSD і робочий local-web
прототип CaseFlow. До створення application layer потрібна одна цільова межа,
щоб UI, SQLite, файлове сховище та важкі processors не стали взаємозалежними.

Канонічні вимоги й архітектурні рішення мають залишатися у versioned-файлах
репозиторію. Notion або інший SaaS не повинен бути прихованою залежністю для
запуску, розробки, документації чи відновлення продукту.

## Рішення

VARTA є модульним local-first Python-застосунком для одного локального
користувача з таким цільовим контуром:

```text
browser UI на loopback
  -> embedded local HTTP presentation adapter
  -> application services (commands, queries, DTOs, ports, Unit of Work)
  -> domain
  -> infrastructure adapters
       -> SQLite
       -> managed filesystem
       -> durable job supervisor
            -> isolated local workers
```

Чинні dependency rules:

- browser UI взаємодіє лише з versioned local HTTP API і не читає SQLite чи
  файлове сховище напряму;
- HTTP handlers, CLI та майбутні adapters є presentation/inbound adapters і
  викликають ті самі application services;
- application services координують use cases, транзакції й порти, але не
  залежать від HTTP або конкретного UI;
- domain не імпортує HTTP, SQLite, filesystem, worker SDK чи зовнішні SDK;
- infrastructure реалізує порти application layer;
- важка обробка виконується поза HTTP request і поза DB transaction в
  ізольованих workers за контрактом `ADR-007`;
- authoritative state утворює пара SQLite + managed filesystem за
  `ADR-002` і `ADR-005`;
- зовнішні інтеграції вимкнені за замовчуванням і можливі лише як явно
  активовані adapters через application boundary.

Основний інтерактивний інтерфейс — browser UI, який embedded server віддає
лише на loopback. `stdlib` HTTP server можна зберігати, доки вимірювана
потреба не обґрунтує інший framework. Framework не визначає межі шарів.

Notion не входить до runtime, core, документаційного workflow, інтеграцій або
джерел істини VARTA. Його майбутнє додавання потребуватиме нового ADR і не
може бути обов'язковим для роботи з локальним workspace.

## Відхилені альтернативи

1. **Notion/Airtable або інший SaaS як core чи system of record.** Відхилено
   через privacy, offline, provenance і vendor-lock-in межі.
2. **Desktop UI як окрема authoritative реалізація use cases.** Відхилено,
   бо це дублює application logic; desktop shell допустимий лише як launcher
   local-web surface.
3. **CLI-only продукт.** CLI залишається adapter для automation/diagnostics,
   але не замінює погоджений інтерактивний browser UI.
4. **Cloud/multi-user server або microservices.** Немає підтвердженої потреби;
   мережевий чи багатокористувацький режим потребує нового ADR.
5. **UI або workers із прямим доступом до repositories.** Відхилено через
   обхід validation, audit, authorization context і transaction boundary.

## Наслідки

Переваги: локальний контроль, offline operation, одна use-case boundary,
замінні adapters, відтворювані processors і відсутність SaaS-залежності.

Вартість: треба виділити application contracts, перенести legacy handlers та
processors поступово й підтримувати чіткі DTO/error contracts. Embedded
local HTTP не робить дані безпечними автоматично; його boundary визначає
`ADR-006`.

Це target architecture, а не твердження про завершену реалізацію. Поточний
`caseflow/server.py` ще містить repository/filesystem/business concerns;
перенесення належить `C03`, `C10` і `C12`.

## Вплив на міграцію

- `C03` створює application package, ports, DTOs, Unit of Work і `/api/v1`,
  не змінюючи погодженого UX;
- `C10` реалізує durable job/result contracts та worker lifecycle;
- `C12` переводить integrated local web UI і thin HTTP handlers на
  application services;
- compatibility namespace `caseflow` може існувати під час переходу, але не
  визначає dependency direction;
- перехід не дозволяє змінювати immutable originals або робити legacy
  каталоги writable.

## Пов'язані рішення

- [ADR-002](ADR-002-source-of-truth.md)
- [ADR-005](ADR-005-workspace-and-managed-storage.md)
- [ADR-006](ADR-006-local-http-security.md)
- [ADR-007](ADR-007-sqlite-uow-and-workers.md)
