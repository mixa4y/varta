# VARTA project status

**Статус:** `DRAFT`

**Версія baseline:** `0.1.0`

**Канонічний root:** `D:\VARTA`

**Гілка:** `codex/stabilize-baseline`

## Live baseline 11.08.2026

- старий baseline `0c263f7b83a05cdd7eae5635350740f50ab51dbe` збережено як base;
- 38 погоджених шляхів розділено на шість P0 commits: migrations/repository,
  Airtable mapping/import, contacts model/API/UI, Evidence Map DDL/contract,
  Windows packaging/typing і документація/status;
- сторонній streaming multipart change зафіксовано окремим двофайловим
  `HOLD-1` commit, а не домішано до Windows або contacts patch;
- фінальний clean checkout: `82 passed`, Ruff clean, mypy clean для 26 source
  files, compileall і `git diff --check` пройдені;
- wheel містить обидві SQL migrations, Airtable schema, static UI і version
  manifest; installed-wheel smoke бачить 9 Airtable tables і 2 migrations;
- з clean checkout зібрано й запущено `VARTA.exe`; API створив SQLite,
  застосував migrations `0001`/`0002` і підтвердив таблицю `claims`;
- push, PR або release не виконувалися.

На початку аудиту було 27 змінених tracked-файлів, 10 untracked і
розходження документації `MM`/`AM`. Застарілий staging очищено без зміни
working content. Два пізніше створені сторонні файли `docs/chat-roadmap.md` і
`docs/interactive/varta-chat-roadmap.html` не входять до baseline commits і
залишаються окремою незмішаною роботою.

Migration checksum канонізує line endings до LF перед SHA-256. Однаковий SQL
у LF source і CRLF Windows checkout має один checksum; фактична зміна SQL
залишається забороненою після застосування migration.

Це підтверджений відтворюваний baseline і готова локальна серія Git patches.
Exact scopes та перевірки зафіксовано в `docs/action-algorithm.md`; публікація
залишається окремою дією.

## Єдине робоче місце

Усі нові зміни вносяться тільки в цей репозиторій. Вихідні каталоги
CaseFlow і CMSD залишаються незмінними джерелами для звірки до завершення
міграції.

## Зовнішній офлайн-комплект

`D:\CMSD\offline_bundle` має статус `CURRENT_SUPPORT_ASSET`. Це не окремий
варіант вихідного коду, а відновлений офлайн-комплект для Python 3.12,
PDF/OCR/STT, 7-Zip, FFmpeg, Tesseract і локальної Whisper-моделі. Його не
можна видаляти або замінювати без перевіреної повної копії та повторної
offline-валидації.

## Що вже консолідовано

- CMSD domain models, dictionaries, repository, audit і naming;
- локальний сервер, intake pipeline та anomaly detector CaseFlow;
- основна HTML/CSS/JavaScript в’юха;
- універсальна privacy-safe Evidence Map view;
- повторно використовувані скрипти аналізу, staging та extraction;
- Windows build/install/update tooling;
- архітектурні документи, правила workspace і універсальний blueprint;
- case profile, schemas та шаблони snapshot;
- тести обох вихідних кодових баз.

## SQLite та модель Airtable

SQLite і файлове сховище затверджені як локальне writable джерело істини.
Airtable залишається джерелом одноразового або повторюваного імпорту, а не
паралельною робочою базою.

До versioned SQLite migration перенесено повну структуру історичної Airtable
base: 9 таблиць, 127 полів, 38 record-link зв'язків і 12 computed fields.
Зв'язки подані нормалізованими foreign key та many-to-many таблицями;
формули й lookup-залежності збережені у каталозі схеми та SQL views. Додано
двопрохідний idempotent importer, який зберігає Airtable record IDs, raw JSON
і явно показує unresolved links.

Модель контактів уже доступна через SQLite repository, локальний HTTP API та
детальну картку у в'юсі. Поточний acceptance run використовує лише вигадані
дані. Реальні записи з Airtable не імпортовано автоматично й не включено до
Git.

## Evidence Map: точна межа реалізації

| Рівень | Стан |
|---|---|
| Versioned DDL | `DONE`: migration `0002_evidence_map_domain.sql` створює case profiles, file objects, processing runs, source references, claims, evidence relations, review decisions, amounts та export records |
| JSON contracts | `DONE`: case profile і Evidence Map schema `1.1.0`, templates та negative tests синхронізовані |
| Repository API | `PARTIAL`: migration виконується, але окремих services/CRUD для claims, evidence relations, source references, review decisions та exports ще немає |
| Application flow | `PARTIAL`: наявна HTML-в’юха використовує snapshot/embedded JSON; детермінований SQLite → Evidence Map generator ще не реалізовано |

Тому існування таблиць не описується як завершений Evidence Map flow:
фактичний статус — `DDL/CONTRACT DONE`, `REPOSITORY API PARTIAL`,
`APPLICATION FLOW PARTIAL`.

## Межа даних

Git містить код, правила, схеми, порожні або вигадані приклади й дизайн.
Матеріали справ, реєстри, підписи, runtime state, secrets та generated maps
залишаються поза Git.

## Сумісність першого baseline

Усередині репозиторію поки збережено Python namespace `caseflow`, назви
сумісних PowerShell-файлів `*_caseflow.ps1` і runtime-каталог `.caseflow`.
Це свідомий перехідний шар, а не назва нового продукту. Product manifest,
EXE, UI та GitHub-репозиторій використовують назву VARTA.

## Що ще не погоджено

1. контракт XLSX import/export adapter поверх SQLite;
2. міграція runtime-каталогу `.caseflow` до `.varta`;
3. repository/application services і повний generator Evidence Map із SQLite;
4. release packaging та автоматичне оновлення;
5. режим одного workspace для однієї або багатьох справ;
6. процедура контрольованого імпорту авторизованих реальних записів;
7. увімкнення суворих style/modernization правил Ruff після окремого
   форматувального diff; baseline перевіряє error-level правила.

Ці пункти не маскуються як завершені. Їх погоджуємо по одному за порядком у
`docs/INDEX.md`.
