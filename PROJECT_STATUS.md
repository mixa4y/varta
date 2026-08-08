# VARTA project status

**Статус:** `DRAFT`

**Версія baseline:** `0.1.0`

**Канонічний root:** `D:\CMSD\VARTA`

**Гілка:** `main`

## Єдине робоче місце

Усі нові зміни вносяться тільки в цей репозиторій. Вихідні каталоги
CaseFlow і CMSD залишаються незмінними джерелами для звірки до завершення
міграції.

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

1. остаточний repository: SQLite-only чи перехідний XLSX adapter;
2. точні many-to-many таблиці для документів, подій, справ і проваджень;
3. міграція `.caseflow` до `.varta`;
4. повний generator Evidence Map із SQLite;
5. release packaging та автоматичне оновлення;
6. режим одного workspace для однієї або багатьох справ.
7. увімкнення суворих style/modernization правил Ruff після окремого
   форматувального diff; baseline перевіряє error-level правила.

Ці пункти не маскуються як завершені. Їх погоджуємо по одному за порядком у
`docs/INDEX.md`.
