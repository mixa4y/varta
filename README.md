# VARTA

**VARTA — Verified Archive of Relations, Timeline & Analysis.**

Локальна система для приймання, збереження, перевірки та візуалізації
матеріалів судових справ. VARTA об’єднує робочий прототип CaseFlow та
універсальне ядро CMSD в один продукт і один репозиторій.

## Канонічне розташування

```text
D:\VARTA
```

Старі каталоги CaseFlow і CMSD є лише read-only джерелами міграції. Усі нові
зміни виконуються тут. Поточний стан і порядок перегляду зафіксовано в
`PROJECT_STATUS.md` та `docs/INDEX.md`.

## Що входить до репозиторію

```text
VARTA/
├── case_docket/          універсальні моделі, словники, naming і repository
├── caseflow/             локальний сервер та успадкована робоча в’юха
├── config/               загальна конфігурація і JSON Schema
├── docs/                 індекс, архітектура, blueprint і журнал міграції
├── scripts/              повторювані локальні інструменти
├── templates/
│   ├── case/             порожній профіль справи
│   └── evidence-map/     контракт і дизайн доказової мапи
├── tests/                тести обох вихідних проєктів
└── tools/windows/        інсталятор, запуск, оновлення і пакування
```

Репозиторій не містить PDF/DOCX/P7S, реєстрів XLSX, персональних даних,
OAuth-токенів, локальних індексів або згенерованої мапи конкретної справи.

## Локальна архітектура та джерело істини

VARTA використовує embedded browser UI тільки на loopback. UI викликає
application services через versioned local HTTP API; цільова dependency
boundary не дозволяє UI або workers напряму працювати з repository.

Authoritative state — SQLite + managed filesystem. SQLite є єдиним writable
structured source of truth, а managed filesystem зберігає registered bytes та
immutable originals. XLSX/JSON/HTML є import/export/projection artifacts.

Fresh C07 runtime під час першого запуску застосовує migrations `0001`–`0009`
і створює `<workspace>\.varta\database\varta.sqlite3` разом із managed storage
zones. Якщо існує лише legacy `<workspace>\.caseflow\varta.sqlite3`, VARTA
використовує й additively upgrades його in place без copy/move. Якщо існують
обидві DB, запуск fail-иться explicit до reconciliation C09/C15, без silent
authority choice, rename або видалення.

File/folder/top-level-ZIP intake проходить application service, C05 immutable
storage і SQLite batch/entry history. Inventory після restart читається тільки
з SQLite; XLSX/JSON/HTML лишаються adapters/projections. Детальний status,
idempotency й archive contract — `docs/architecture/intake-v1.md`.

Кожен accepted/duplicate file отримує temporary `intake_case_id` і явний
pending-review state. Multi-case list, candidate normalization/manual
confirmation, memberships та active-case presentation preference визначає
`docs/architecture/workspace-v1.md`; повний UI лишається C12/C13.

Історична Airtable-модель перенесена повністю: 9 таблиць, 127 полів,
38 зв'язків і 12 computed fields. Вона збережена як privacy-safe schema
snapshot у `config/airtable_schema.json`; записи та облікові дані до snapshot
не входять. Детальний контракт SQL та імпорту описано в
`docs/airtable-sql-migration.md`.

Evidence Map domain формалізовано на двох нижніх рівнях: versioned migration
`0002_evidence_map_domain.sql` створює таблиці, constraints та indexes, а JSON
Schema `1.1.0` визначає case profile і snapshot contract. Це
`DDL/CONTRACT DONE`, але ще не завершений продукт: repository/application API
для claims, evidence relations, source references і review decisions є
частковим, а детермінований SQLite → Evidence Map flow ще не реалізовано.

## Дані, а не hardcode

Номер справи, кількість проваджень, aliases, центральний документ, ключові
документи та причинні зв’язки задаються у case profile. Один і той самий код
повинен працювати зі справою з одним, трьома, п’ятьма або іншою кількістю
проваджень.

Початковий шаблон:

```text
templates/case/case-profile.example.json
```

## Назви керованих документів

Назва документа не дублює номер справи або провадження, оскільки цей
контекст уже визначений шляхом. Українська назва передається латиницею за
КМУ №55, без перекладу англійською:

```text
20240314_pozovna_zaiava.pdf
20240314_pozovna_zaiava_dodatok_001.pdf
20240314_pozovna_zaiava_dodatok_002.pdf
```

Оригінальні файли не перейменовуються; коротке ім’я належить керованому
представленню. Внутрішні ID і SHA-256 зберігаються окремо та не виводяться
у назву.

## Локальний запуск

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\varta.exe --root D:\Cases\example --open
.\.venv\Scripts\varta-intake.exe --workspace D:\Cases\example add D:\Input\synthetic.txt --idempotency-key synthetic-001
.\.venv\Scripts\varta-intake.exe --workspace D:\Cases\example inventory
```

Історичний clean baseline на 11.08.2026: `82 passed`, Ruff clean, mypy clean
для 26 source files і compileall passed. Результат повторено з clean checkout
гілки `codex/stabilize-baseline`, де 38 погоджених шляхів розділено на шість
предметних P0 commits, а streaming multipart change винесено в окремий
двофайловий `HOLD-1` commit. Wheel/install і packaged `VARTA.exe` smoke
підтвердили, що SQL migrations, `config/airtable_schema.json`, static UI та
version manifest входять до доставки. Push, PR і release не виконувалися.

Після запуску локальна в'юха доступна за адресою, яку виводить `varta.exe`.
Розділ **Контакти** підтримує пошук, створення, редагування повної картки та
призначення ролі у справі або провадженні.

Поточний baseline навмисно зберігає внутрішню назву Python-пакета `caseflow`
і підтримує existing legacy `.caseflow` DB in place до reconciliation.
Користувацький продукт, manifest, EXE та в’юха називаються VARTA; fresh
structured/file authority уже використовує `.varta`. Повний decision package:
`docs/architecture/architecture-decision-log.md`.
