# R05 — локальна база справи VARTA

## Чинна реалізація

Airtable використаний лише як історичне джерело offline структури таблиць,
полів і зв’язків. Робочий шлях R05 не використовує мережу, Airtable API,
токени, Base ID binding, authorization handles або DPAPI.

`case_docket.local_case_source` приймає локальний JSON опис справи з назвами
SQL-таблиць та полів. Зв’язки називаються за SQL mapping target, щоб однаково
названі source links не втрачали напрямок. `--schema` показує всі допустимі
поля, choices, formulas/lookups та link metadata. Невідомі поля/таблиці,
некоректні choices, links, attachment identities, дублікати ID та відсутня
обрана справа відхиляються до запису БД.

Всередині persistence compatibility layer збережені історичні table/field IDs
та назви SQL-таблиць з префіксом airtable. Це локальні ідентифікатори mapping,
а не мережеве підключення. Застосовані міграції не переписувалися. Повний
локальний snapshot має sourceKind=local-case, hashes структури/даних і точні
counts. Зміни локального опису між plan/execute/resume виявляються hashes.

R05PrivateSettingsStore зберігає тільки локальні шляхи в атомарно записуваному
JSON-файлі поза Git. Зашифровані файли попередньої реалізації не мігруються,
не читаються і не видаляються. Live adapter, його тести й DPAPI-модулі вилучені;
попередні версії збережені локально в checkpoint поза Git.

## Використання

Показати повний offline контракт локального опису:

```powershell
.\.venv\Scripts\python.exe -m case_docket.local_case_source --schema
```

Мінімальний явно синтетичний локальний опис:

```json
{
  "formatVersion": 1,
  "caseId": "synthetic-case",
  "tables": {
    "cases": [{"id": "synthetic-case", "fields": {
      "case_number": "SYNTHETIC-ONLY", "name": "Вигадана справа"
    }}]
  }
}
```

Інші таблиці можна не подавати, якщо вони порожні. Локальний файл опису містить
реальні дані лише поза Git. Матеріали корпусу не повинні містити workspace чи
backup; CLI відхиляє вкладені corpus/workspace directories і backup у originals.

```powershell
.\.venv\Scripts\python.exe -m case_docket.local_case_source --input <local-case.json> --corpus <originals-directory> --workspace <workspace-directory> --backup <new-backup.sqlite3>
```

CLI виконує plan, local import, corpus hash verification, exact attachment
reconciliation, restart/backup verification та finalize. Повторний запуск з
незмінними входами використовує той самий import run; для нового backup proof
потрібен новий backup filename. Наявна резервна копія не перезаписується.

## Покриття й межі

| Потреба | Реалізація / межа |
| --- | --- |
| Таблиці, поля, choices та зв’язки | Повний offline catalog, SQL scalar/link mapping, перевірка відсутності втрати полів і неоднозначних назв |
| Formulas/lookups | Опис і надані значення зберігаються; універсального обчислювача Airtable formulas немає, автоматичне відтворення їхньої поведінки не заявляється |
| Case/proceedings/documents/events/actors | Локальні records через чинний repository materialization, versioned profile і case isolation |
| Вкладення та файли | Exact SHA-256 або source-relative provenance; name+size тільки review suggestion; file/document та file/case memberships |
| Версії, відповіді, findings | Чинні evidence relations і source basis; unverified/manual-review semantics |
| Claims/reviews | Чинні C08 repositories, без вигадування підтверджених висновків |
| Originals та lineage | Незмінні originals, inventory manifest, managed copy/reference, run/batch history і hashes |
| Повторний запуск та backup | Idempotency/resume, integrity/FK/count/revision parity і managed-file hashes |
| C11 | R02/R04 query contract і read-back відновленої SQLite; реалізація C11 поза R05 |
| OCR/КЕП/UI | Downstream scope, не реалізовано тут |

## Перевірки

Новий end-to-end тест забороняє network/WinDLL calls та перевіряє локальний
імпорт з реальним синтетичним файлом, його attachment mapping, незмінність
originals, повторний запуск, backup/restore та EvidenceMapSourceQueryService
на відновленій SQLite. Цей тест виявив і закрив відсутній file_context_membership,
який раніше залишав broken file reference для C11.

Актуальні exact commands, результати й fingerprints зберігаються в локальному
R05 checkpoint. Старий G20 про Airtable credentials/DPAPI скасований зміною вимог,
а не зарахований як виконаний. Реальний corpus користувача в цьому проході не
імпортувався; synthetic TECH evidence не називається real-case acceptance.
