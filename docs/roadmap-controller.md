# Локальний controller для запуску roadmap packages

**Статус документа:** `IMPLEMENTATION GUIDE / DEVELOPMENT TOOLING`

Цей controller перетворює
`docs/interactive/varta-chat-roadmap.html` з офлайн-карти на локальну панель,
яка може:

1. створити рівно один постійний Codex task/chat з точною темою package;
2. одразу передати йому повний stage prompt і почати turn, а всі повторні
   спроби продовжувати новими turns у цьому самому task;
3. показувати live-процес, доказовий відсоток виконання, `starting`, `running`,
   `waiting`, `failed` та завершення;
4. прийняти структурований handoff із summary, tests, changed files і gate;
5. після `TECH PASS` показати окрему підтверджену кнопку GitHub checkpoint;
6. запустити Git checkpoint новим turn у тому самому package task для audit,
   exact staging, commit, push у приватну `codex/*` branch і
   створення/оновлення Draft PR;
7. розблокувати залежні stages тільки після валідного `GITHUB SYNCED`;
8. зупинити активний stage або Git turn без видалення task чи його історії.

Notion, зовнішній SaaS, OpenAI API key і окрема хмарна БД для цього не
потрібні. Controller використовує локальний Codex App Server та активну
авторизацію Codex Desktop.

Офіційна основа інтеграції:

- [Codex App Server](https://learn.chatgpt.com/docs/app-server) —
  `thread/start`, `thread/name/set`, `turn/start`, streamed notifications і
  `turn/completed`;
- [Projects and chats](https://learn.chatgpt.com/docs/projects) — один
  постійний task на один `Cxx`/`Pxx` package у межах одного local project.

## Швидкий запуск

1. У корені `D:\VARTA` двічі натиснути `START_ROADMAP.cmd`.
2. Дочекатися відкриття `http://127.0.0.1:8766/`.
3. Переконатися, що верхній badge показує `CODEX READY`.
4. Відкрити потрібний package і натиснути **Створити чат і почати Cxx**. Якщо
   package вже має Task ID, кнопка продовжить саме цей чат новим turn.
5. Підтвердити точну тему та prerequisites у діалозі.
6. Стежити за live-процесом, відсотком, контрольними подіями, status, останнім
   повідомленням, tests і transition gate на тій самій сторінці.
7. Після `TECH PASS` перевірити stage result і натиснути **GitHub checkpoint**.
8. У другому confirmation прочитати точний scope: privacy/ownership audit,
   exact staging, commit, push і Draft PR без merge/release.
9. Дочекатися `GITHUB SYNCED`; тільки тоді відкриється залежний stage.
10. Для штатної зупинки controller використати `STOP_ROADMAP.cmd`.

Статичний `file://` варіант залишається читабельним, але не створює tasks:
браузерний файл не має привілейованого доступу до Codex. Кнопки виконання
активуються тільки на loopback-сторінці, яку віддає controller.

## Що відбувається після Start

```text
stage button
  -> POST 127.0.0.1 + Origin check + per-launch token
  -> allowlist stage ID + dependency gate + single-active-task gate
  -> thread/start + thread/name/set лише для першого запуску package
  -> для retry/continuation повторно використати збережений package thread
  -> turn/start у D:\VARTA
  -> streamed status, agent message і VARTA_PROGRESS checkpoints
  -> live UI: процес + evidence-based percent + event history
  -> VARTA_STAGE_RESULT validation
  -> local state.json
  -> TECH PASS / awaiting_approval
  -> окреме підтвердження GitHub checkpoint
  -> новий Git turn у тому самому package thread + VARTA_GIT_RESULT
  -> exact stage-owned paths + privacy gates
  -> commit + push origin/codex/* + Draft PR
  -> GITHUB SYNCED
  -> roadmap UI poll і розблокування dependencies
```

Controller не виконує наступний stage автоматично. Кожний Start залишається
явною дією користувача.

## Три незалежні типи статусів

`planningStatus` описує стан напрацювань до запуску task:

- `READY` — package можна починати;
- `PARTIAL` — частина реалізації вже є;
- `PLANNED` — scope визначено, але prerequisites ще не пройдені;
- `BLOCKED_BY_DECISION` — перед кодом потрібен попередній ADR/gate.

`runStatus` описує фактичний execution lifecycle:

| Run status | Значення |
|---|---|
| `not_started` | controller ще не запускав package |
| `starting` | створюється перший thread або новий turn у вже наявному package task |
| `running` | Codex виконує task |
| `waiting` | App Server повідомив про очікування дії/дозволу |
| `completed` | turn завершено й валідний result підтвердив `passed` |
| `blocked` | agent повернув конкретний blocker/decision request |
| `failed` | запуск, turn або package завершився помилкою |
| `interrupted` | turn зупинено або controller перезапущено під час роботи |
| `needs_review` | turn завершився без валідного machine-readable handoff |

`turn/completed` не дорівнює `PASS`. Stage стає `completed` лише коли його
фінальна відповідь містить валідний блок `VARTA_STAGE_RESULT`, ID збігається,
`outcome=passed`, є фактичні tests і жоден з них не має `failed` або `not_run`.

Вкладений `git.status` описує окремий publication lifecycle:

| Git status | Значення |
|---|---|
| `not_ready` | stage ще не має технічного PASS |
| `awaiting_approval` | TECH PASS є, GitHub не змінено; потрібне натискання користувача |
| `starting` | створюється Git turn у тому самому package task |
| `running` | Codex перевіряє ownership/privacy та виконує checkpoint |
| `waiting` | Git turn очікує дії/дозволу |
| `synced` | private origin містить commit у `codex/*`, Draft PR підтверджено |
| `blocked` | ownership, privacy, branch або інший gate не доведено |
| `failed` | Git/gh/turn завершився помилкою |
| `interrupted` | Git turn зупинено або controller перезапущено |
| `needs_review` | немає валідного `VARTA_GIT_RESULT` |

`synced` приймається лише коли machine result підтверджує `visibility=PRIVATE`,
`remote=origin`, non-main branch `codex/*`, valid commit SHA, `pushed=true`,
усі обов'язкові checks і GitHub Draft PR URL. Локальний commit без push не
позначається як synced. Після цього controller сам виконує read-back:
`git rev-parse`, canonical origin URL, `git ls-remote`, `gh repo view` і
`gh pr view`; він звіряє local HEAD, remote SHA, `PRIVATE`, Draft/Open,
head branch, base `main` і PR head SHA. Невідповідність дає `needs_review`, а
не розблокування наступного stage.

`progress` зберігається окремо для технічного та Git lifecycle. Controller
публікує власні lifecycle checkpoints, а agent може додавати лише значення
`1`–`99` у валідному package-scoped блоці `VARTA_PROGRESS`; `100%` controller
встановлює сам тільки після валідного `VARTA_STAGE_RESULT` або
`VARTA_GIT_RESULT`. Це відсоток підтверджених контрольних точок, а не прогноз
часу. UI опитує loopback API щосекунди, показує поточну фазу, detail і журнал
подій; повний Task ID залишається незмінним для всіх turns одного package.

Roadmap tasks є unattended execution. Якщо agent все ж викликає interactive
request-user-input, controller повертає protocol error замість безстрокового
зависання; prompt вимагає завершити такий package як `blocked` з конкретним
потрібним рішенням. Нову спробу користувач запускає після усунення blocker.

## Dependency і concurrency gates

- Server, а не тільки JavaScript, перевіряє всі prerequisite IDs.
- `C16` вимагає `GITHUB SYNCED` усіх `C01`–`C15`.
- `P01`–`P04` мають власні dependencies з machine catalog.
- В одному `D:\VARTA` одночасно дозволено один активний stage або Git task. Це
  захищає спільний dirty working tree від паралельного перезапису.
- Failed/blocked/interrupted package можна запустити новою спробою; попередня
  спроба залишається у локальній history, а новий turn використовує той самий
  package Task ID.
- Completed package controller повторно не запускає; він очікує Git checkpoint.
- Failed/blocked/interrupted Git checkpoint можна повторити, не втрачаючи його
  локальну history.

## Межа безпеки

Controller:

- слухає тільки `127.0.0.1`;
- перевіряє точний `Host`;
- для кожного write request вимагає same-origin `Origin`;
- вимагає випадковий per-launch token у custom header;
- не вмикає CORS;
- має stage allowlist із `tools/roadmap_controller/stages.json` і не приймає
  довільний prompt або shell command через HTTP;
- запускає всі threads з `approvalPolicy=never` і базовим
  `sandbox=workspace-write`;
- лише після окремого confirmation **GitHub checkpoint** задає для відповідного
  Git turn `sandboxPolicy.type=dangerFullAccess`: Windows elevated sandbox
  працює під окремим low-privilege user і не може використати GitHub credential
  з Windows Credential Manager основного користувача;
- не передає в UI email, account ID, auth tokens або App Server account object;
- не зберігає матеріали справ у repository.

Git turn додатково отримує жорсткий allowlist-policy prompt:

- перевірити live branch, HEAD, origin і private visibility перед write;
- порівняти baseline до stage, `changed_files` і поточний diff;
- блокувати checkpoint, якщо stage ownership не доведений;
- використовувати тільки `git add -- <exact paths>`, ніколи `git add .`, `-A`
  або broad glob;
- перевірити staged diff, `git diff --cached --check`, secrets, заборонені
  extensions/paths і case-specific значення до commit;
- push тільки `origin`/`codex/*` без force і створити/оновити Draft PR до `main`;
- не merge, не tag, не release, не змінювати remote або visibility.

Звичайна кнопка **Стартувати task** не дає stage agent дозволу на commit/push.
Лише окреме confirmation **GitHub checkpoint** є прямою вузькою командою на ці
дії та на turn-scoped `dangerFullAccess`, потрібний для Windows credential
manager і мережевої GitHub-перевірки. Звичайні stage turns не отримують цей
override і залишаються у `workspace-write`. Це захищає від прихованої
публікації одразу після agent-generated PASS та не розширює доступ усіх tasks.

Runtime state, PID, logs, session token і staged службові executables лежать у
`.varta/roadmap-controller/`. Увесь `.varta/` уже виключений з Git.

У поточному Windows MSIX пакет дозволяє читати bundled Codex executable, але
прямий запуск із `WindowsApps` може повертати `Access is denied`. Тому launcher
один раз копіює тільки такі службові файли у локальний ignored runtime:

- `codex.exe`;
- `codex-code-mode-host.exe`;
- `codex-command-runner.exe`;
- `codex-windows-sandbox-setup.exe`.

Копія versioned за fingerprint/size, не додається до Git і оновлюється після
оновлення Desktop package. Матеріали справ, конфіг авторизації та secrets не
копіюються.

## Локальні файли

| Файл | Призначення |
|---|---|
| `tools/roadmap_controller/stages.json` | allowlisted machine catalog 20 tasks |
| `tools/roadmap_controller/server.py` | HTTP controller, App Server client, state machine |
| `tools/windows/start_varta_roadmap.ps1` | безпечний launcher і health check |
| `tools/windows/stop_varta_roadmap.ps1` | перевірена штатна зупинка |
| `START_ROADMAP.cmd` | double-click start |
| `STOP_ROADMAP.cmd` | double-click stop |
| `.varta/roadmap-controller/state.json` | локальний execution state та handoff history |

Write API має окремі маршрути:

- `POST /api/v1/stages/{ID}/start|stop` — stage turn без Git publication;
- `POST /api/v1/stages/{ID}/git/start|stop` — підтверджений Git checkpoint.

## Діагностика

Без запуску HTTP UI:

```powershell
py -3.12 tools\roadmap_controller\server.py --root D:\VARTA --diagnose
```

Health endpoint не повертає secrets або account identity:

```powershell
Invoke-RestMethod http://127.0.0.1:8766/api/v1/health
```

Якщо `codexReady=false`, дивитися локальний
`.varta/roadmap-controller/app-server.log`. Не копіювати цей лог у Git без
privacy review.

## Відомі межі

- Офіційного документованого browser deep-link до конкретного Codex task тут
  не використано. Створений task має точну тему й доступний у project history;
  roadmap також показує його ID.
- Закриття/аварійне завершення controller перериває live event stream. Після
  restart активний stage консервативно стає `interrupted`, а не `PASS`.
- Зміна runtime state вручну не є доказом виконання stage.
- `GITHUB SYNCED` не означає merge, release або production publication; це лише
  підтверджений remote checkpoint у feature branch і Draft PR.
- Controller є development tooling для виконання roadmap, а не частиною
  майбутнього користувацького VARTA local web UI.
