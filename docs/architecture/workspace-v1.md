# VARTA multi-case workspace and case bootstrap v1

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Contract version | `v1.0` |
| Owner package | `C07` |
| Dependency | `C06` |
| SQLite schema | `0009_case_workspace_bootstrap` |
| API prefix | `/api/v1/workspace` |
| Decision basis | `ADR-002`, `ADR-004`, `ADR-005`, `ADR-007` |

## Межа C07

C07 реалізує одну SQLite database з багатьма справами, temporary
`intake_case_id` для кожного accepted/duplicate intake file, candidate
detection/normalization, explicit manual confirmation, file memberships і
active-case presentation preference. Повний visual workflow не входить у цей
contract і залишається C12/C13.

Case number, filename, folder, SHA-256, external reference та display name не є
internal identity. `case_id`, `proceeding_id`, `file_id` і `intake_case_id` —
opaque application-generated IDs. Active case ніколи не підміняє explicit
context ID у command/query.

## Intake bootstrap invariant

Після C07 terminal `accepted` або `duplicate` entry і pending bootstrap
створюються в одній SQLite transaction:

```text
accepted intake entry
  -> opaque intake_case_id
  -> manual_review_required
  -> candidate_ready або manual_review_required
  -> explicit user confirmation
  -> confirmed case membership
```

Migration `0009` additively створює pending bootstrap також для accepted C06
rows, які існували до upgrade. Тому кожен accepted file має або confirmed case
link, або видимий pending-review state. File/original не видаляється, якщо
номер відсутній чи неоднозначний.

## Candidate source contract

Adapter передає versioned candidate source signal із:

- `text`, який detector переглядає, але не зберігає повністю;
- `detectionSource` із allowlist `structured_metadata`, `document_text`, `ocr`,
  `verified_manifest`, `filename`, `folder`, `manual`;
- exact `sourceLocation` та коротким `evidenceBasis`;
- `confidence` у межах `0..1`;
- `tool.name` і `tool.version` для automatic signal;
- optional external-reference triple `system`/`kind`/`value`.

SQLite зберігає raw і normalized candidate, evidence location/basis,
confidence, tool version, external reference та review decision. Normalizer не
домислює відсутні сегменти: у v1 валідний case-number candidate має три цифрові
сегменти, розділені `/`; Unicode width і whitespace нормалізуються
детерміновано.

Candidate readiness рахується за distinct normalized values:

| Signals | Bootstrap status before confirmation |
|---|---|
| zero normalized candidates | `manual_review_required` |
| one filename/folder-only value | `manual_review_required` |
| one distinct value з дозволеним evidence source | `candidate_ready` |
| multiple distinct values із будь-яких sources | `manual_review_required` |

Кілька observations одного normalized value зберігаються окремо як provenance,
але не створюють хибну ambiguity. `candidate_ready` є лише пропозицією:
автоматичного підтвердження немає. Filename/folder може бути сигналом, але
ніколи не є достатнім доказом сам по собі.

## Manual confirmation і locate/create

Confirmation command вимагає `actorId` і одне з такого:

- candidate, обраний із цього `intake_case_id`;
- вручну введений case number, який стає окремим `manual` candidate;
- explicit existing `caseId`, якщо номер досі невідомий.

Application service в одній short write UoW:

1. перевіряє bootstrap/candidate та нормалізований номер;
2. locate-ить рівно одну справу або створює нову opaque case identity;
3. відхиляє duplicate normalized-number ambiguity;
4. відхиляє external reference, уже закріплений за іншою справою;
5. додає file-to-case та optional file-to-proceeding memberships;
6. фіксує candidate decisions, bootstrap history, append-only review decision
   і audit event;
7. переводить bootstrap у `confirmed`.

Помилка будь-якого кроку rollback-ить confirmation transaction: pending state
і immutable file залишаються доступними для нового ручного рішення.

## Multi-case і membership cardinality

`cases` та `proceedings` мають окремі repositories/application commands.
`case_proceedings` лишається many-to-many link. `file_context_memberships`
зберігає окремі file-to-case/file-to-proceeding rows із role, origin, actor,
note й timestamp; один file може належати кільком справам і провадженням.
Document-to-case/document-to-proceeding links використовують formal
`entity_memberships` rows із таким самим explicit application command.

Case membership не виводиться з filename/folder або active-case preference.
Перемикання active case не створює, не змінює й не видаляє domain memberships.

## Active-case preference

`preferenceId` визначає presentation session/tab scope, у якому є нуль або
одна active case. Preference зберігається в SQLite для restart persistence,
але response явно має `scope: "presentation_preference"`. Commands, workers і
queries продовжують отримувати target IDs явно.

## Versioned HTTP contract

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/workspace/cases` | SQLite-backed case list |
| `POST` | `/api/v1/workspace/cases` | explicit case creation command |
| `POST` | `/api/v1/workspace/proceedings` | proceeding creation + case memberships |
| `GET` | `/api/v1/workspace/bootstrap-reviews` | pending bootstrap reviews |
| `POST` | `/api/v1/workspace/bootstrap-reviews/{intake_case_id}/candidates` | detect/store candidate sources |
| `POST` | `/api/v1/workspace/bootstrap-reviews/{intake_case_id}/confirm` | manual confirmation/locate/create |
| `POST` | `/api/v1/workspace/memberships` | explicit file context memberships |
| `POST` | `/api/v1/workspace/document-memberships` | explicit document context memberships |
| `GET` | `/api/v1/workspace/active-case?preferenceId=...` | presentation preference query |
| `POST` | `/api/v1/workspace/active-case` | select/clear presentation preference |

Mutations потребують launch token. Transport adapter відхиляє unknown fields,
не працює з SQLite напряму й повертає stable v1 success/error envelopes.

## Restart, audit і privacy

Cases, proceedings, candidates, membership, bootstrap/status history,
review decisions і active preference читаються з SQLite після restart. Raw
file bytes та full extracted text не копіюються в candidate rows. Fixtures і
docs використовують лише явно синтетичні values, без матеріалів справ,
контактів, сум або user paths.

## C07 acceptance

- одна DB зберігає багато cases/proceedings без global domain case key;
- кожен accepted/duplicate file має `intake_case_id` і pending/confirmed state;
- zero/one/multiple та duplicate-normalized candidates мають deterministic
  status;
- filename/folder-only signal не достатній для `candidate_ready`;
- manual confirmation має audit/review history та conflict-safe locate/create;
- file membership many-to-many, а active-case switch її не змінює;
- state/API contract переживає process restart;
- full UI не розпочато.
