# Індекс належності файлів VARTA

Цей документ відповідає на два різні питання: де шукати потрібний компонент і
хто має право включати конкретний файл до package checkpoint. Канонічний
машинний manifest: `config/file-ownership.json`. Поточний Git-стан можна
проіндексувати без читання вмісту файлів:

```powershell
D:\VARTA\.venv\Scripts\python.exe tools\project_inventory.py --write-reports
```

Команда створює локальні ignored-звіти:

- `.varta/reports/project-inventory.md` — читабельна таблиця;
- `.varta/reports/project-inventory.json` — машинний звіт.

Інвентаризатор нічого не видаляє, не stage-ить і не читає матеріали справ. Він
показує лише repository-relative Git paths, їхній стан, owner, категорію та
дозволену disposition.

## Канонічні зони

| Зона | Що тут лежить | Правило |
|---|---|---|
| `case_docket/` | domain/application/repository core | package-owned або shared code; перевіряти manifest |
| `caseflow/` | local server, UI та compatibility boundary | shared `CORE`; потрібна координація |
| `config/` | schemas, dictionaries й ownership manifest | product contracts, не runtime data |
| `docs/` | architecture, roadmap, change records та індекси | статус визначає authority документа |
| `templates/` | порожні або явно synthetic шаблони | жодних реальних case values |
| `tests/` | synthetic verification | тест має owner того самого package або shared core |
| `tools/roadmap_controller/` | controller, stage definitions і browser smoke | `ROADMAP` |
| `.varta/` | controller/runtime state та локальні reports | `RUNTIME`, protected, поза Git |
| `.venv/` | локальне Python-середовище | protected tool environment, поза Git |

## Readiness і C11: exact ownership

| Owner | Власні файли | Спільні файли |
|---|---|---|
| `R01` | `profile.py`, `profile_ports.py`, `test_case_profile_r01.py` | application exports, SQLite repository/UoW |
| `R02` | `sqlite_evidence_map_source.py`, відповідний test | `evidence_map_source.py`, application/repository exports |
| `R03` | `evidence_map_export.py`, `sqlite_evidence_map_export.py`, відповідний test | application/repository exports, SQLite UoW |
| `R04` | `docs/changes/R04-consumer-readiness.md`, readiness test | `evidence_map_source.py` consumer-validation contract разом з `R02` |
| `C11` | `evidence_map.py`, projection test | application exports |

Файли з кількома owners не належать останньому package цілком. Для них
обов'язковий hunk-level diff і literal `git add -- <paths>` лише після доказу
меж конкретного checkpoint.

## Поточний робочий scope

Незакомічені зміни controller/roadmap належать `ROADMAP`:

- `docs/chat-roadmap.md`;
- `docs/interactive/varta-chat-roadmap.html`;
- `docs/roadmap-controller.md`;
- `tools/roadmap_controller/server.py`;
- `tools/roadmap_controller/stages.json`;
- `tools/roadmap_controller/browser_smoke.cjs`;
- `tests/test_roadmap_controller.py`.

`README.md`, `PROJECT_STATUS.md` і `docs/action-algorithm.md` є shared
governance files. Навіть коли їхні поточні hunks стосуються roadmap, вони не
стають одноосібно roadmap-owned і потребують окремого exact review.

## Generated і cleanup boundary

Безпечні для повторного створення test/build artifacts:

- `.pytest-tmp-*`, `.pytest-tmp/`, `.pytest_cache/`;
- `.mypy_cache/`, `.ruff_cache/`, `build/`, `varta.egg-info/`;
- перевірені test/build залишки у `tmp/` та `.tmp/`.

Нові verification runs мають використовувати explicit `--basetemp` у
користувацькому temp-каталозі поза `D:\VARTA`. Якщо environment цього не
дозволяє, repo-local `.pytest-tmp-*` залишається ignored і прибирається після
завершення run; такий каталог ніколи не є package evidence сам по собі.

Protected за замовчуванням і не є cleanup debris:

- `.varta/`, `.caseflow/`, `.venv/`;
- case workspaces, immutable originals, exports і runtime databases;
- зовнішній offline/support bundle;
- будь-який невідомий або `UNCLASSIFIED` path.

Невідомий файл спочатку отримує owner і лише потім може бути переміщений або
видалений. Назви `final`, `ready`, `old` чи номер package самі по собі не є
доказом належності або застарілості.

## Остання контрольована чистка

02.09.2026 з кореня репозиторію перенесено 66 перевірених generated-каталогів:
15 112 payload-файлів і 4 045 216 108 байтів без урахування локального manifest.
До набору входили `.pytest-tmp*`, test caches, локальні build/egg-info
результати та перевірені залишки `tmp/.tmp`.

Вони не видалені фізично. Відновлюваний локальний manifest і payload лежать у
`quarantine/generated-artifacts-20260902/`, не входять до Git і не є source of
truth. `.varta`, `.venv`, package code, committed R01–R04/C11 та зовнішні case/
offline assets не переміщувалися.
