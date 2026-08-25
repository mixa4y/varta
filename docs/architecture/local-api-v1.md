# VARTA local API v1 contract

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Version | `v1.0` |
| Date | `2026-08-18` |
| Owner | `C03` |
| Additive intake extension | `C06`, contract `intake-v1.md` |
| Additive workspace extension | `C07`, contract `workspace-v1.md` |

## Призначення і межа

`/api/v1` є versioned local HTTP boundary між browser/CLI/future adapters та
application services. HTTP handler відповідає лише за route matching,
декодування запиту, transport validation, CSRF check і перетворення
application result/error на JSON. Він не викликає SQLite repository напряму.

C03 переносить один реальний slice — contacts. Intake, Evidence Map,
processors, workspace detection і повний security hardening залишаються поза
цим контрактом та належать їхнім наступним packages.

## Versioning policy

- major version є частиною path: `/api/v1`;
- у межах `v1` можна додавати optional response fields і нові endpoints;
- значення або обов’язковість наявного поля, HTTP status, error code чи
  semantics не змінюються несумісно без `/api/v2`;
- клієнт має ігнорувати невідомі optional fields;
- кожна versioned відповідь містить `apiVersion: "v1"`;
- видалення compatibility routes можливе лише окремою міграцією після
  підтвердження відсутності callers.

## Versioned endpoints implemented through C07

| Method | Path | Application operation | Success |
|---|---|---|---|
| `GET` | `/api/v1/status` | мінімальна API/product capability відповідь | `200` |
| `GET` | `/api/v1/contacts?q=` | `ListContactsQuery` | `200` |
| `GET` | `/api/v1/contacts/context` | `GetContactsContextQuery` | `200` |
| `GET` | `/api/v1/contacts/{contact_id}` | `GetContactQuery` | `200` |
| `POST` | `/api/v1/contacts` | `CreateContactCommand` | `201` |
| `PATCH` | `/api/v1/contacts/{contact_id}` | `UpdateContactCommand` | `200` |
| `POST` | `/api/v1/contacts/{contact_id}/roles` | `AssignContactRoleCommand` | `201` |
| `POST` | `/api/v1/intake` | multipart -> `IntakeCommand` | `201`; replay `200` |
| `GET` | `/api/v1/intake/inventory` | `ListIntakeInventoryQuery` | `200` |
| `GET` | `/api/v1/intake/batches/{batch_id}` | SQLite batch read-back | `200` |
| `GET` | `/api/v1/workspace/cases` | `ListWorkspaceCasesQuery` | `200` |
| `POST` | `/api/v1/workspace/cases` | `CreateWorkspaceCaseCommand` | `201` |
| `POST` | `/api/v1/workspace/proceedings` | `CreateWorkspaceProceedingCommand` | `201` |
| `GET` | `/api/v1/workspace/bootstrap-reviews` | `ListPendingBootstrapReviewsQuery` | `200` |
| `POST` | `/api/v1/workspace/bootstrap-reviews/{id}/candidates` | `RegisterCandidateSourcesCommand` | `200` |
| `POST` | `/api/v1/workspace/bootstrap-reviews/{id}/confirm` | `ConfirmCaseBootstrapCommand` | `200` |
| `POST` | `/api/v1/workspace/memberships` | `AddFileMembershipsCommand` | `201` |
| `POST` | `/api/v1/workspace/document-memberships` | `AddDocumentMembershipsCommand` | `201` |
| `GET` | `/api/v1/workspace/active-case?preferenceId=` | `GetActiveCaseQuery` | `200` |
| `POST` | `/api/v1/workspace/active-case` | `SelectActiveCaseCommand` | `200` |

C06 intake mutation додатково вимагає `Idempotency-Key`; multipart приймає
лише `files`, а literal relative filenames проходять C05 path/archive policy.
Детальні status, retry й archive semantics визначає
[`intake-v1.md`](intake-v1.md). Full visual intake workflow лишається C12/C13.

C07 workspace routes використовують той самий stable envelope/token boundary.
Filename/folder не є достатнім candidate evidence, manual confirmation не
виводиться з active-case preference, а HTTP handler викликає лише
`WorkspaceService`. Детальний contract —
[`workspace-v1.md`](workspace-v1.md); full workspace/review UI лишається
C12/C13.

Mutating requests використовують чинний per-launch token у
`X-Caseflow-Token`. Повний Host/Origin/CSP negative contract затверджено
`ADR-006`, але його implementation/acceptance належить C12/C15/C16 і не
підмінюється C03.

## Success envelope

```json
{
  "ok": true,
  "apiVersion": "v1",
  "contact": {
    "id": "contact-synthetic",
    "full_name": "Синтетична Особа",
    "participant_type": "person",
    "email": "contact@example.invalid",
    "roles": []
  }
}
```

Приклад навмисно вигаданий. Fixtures і документація не використовують реальні
ПІБ, номери справ, контакти, суми або локальні case paths.

## Stable error envelope

```json
{
  "ok": false,
  "apiVersion": "v1",
  "error": {
    "code": "request_validation_error",
    "message": "Відсутнє обов’язкове поле",
    "details": {
      "field": "full_name"
    }
  }
}
```

| HTTP | Stable code | Meaning |
|---|---|---|
| `403` | `forbidden` | неправильний local mutation token |
| `404` | `not_found` | application resource не існує |
| `404` | `route_not_found` | versioned route не існує |
| `409` | `conflict` | uniqueness/state conflict |
| `409` | `busy` | інша несумісна локальна операція виконується |
| `422` | `request_validation_error` | JSON shape/type/field contract порушено |
| `422` | `validation_error` | domain/application invariant порушено |
| `500` | `internal_error` | неочікувана помилка без витоку internal detail |

`details` містить лише безпечні machine hints. Raw payload, SQLite exception,
шлях workspace, token або case-specific значення в error envelope не
повертаються.

## Validation boundary

Transport adapter:

- вимагає JSON object;
- відхиляє unknown fields;
- перевіряє JSON types, required field presence і ISO date syntax;
- створює typed command/query, а не передає raw JSON далі.

Application/domain:

- нормалізує ідентифікатори та обов’язковий текст;
- перевіряє contact invariants, зокрема participant type, email і
  organization/person rules;
- переводить missing/conflict у service errors;
- передає repository port лише domain objects/typed DTO, не request body.

## Unit of Work boundary

Кожна contacts command/query створює окремий Unit of Work і short-lived SQLite
connection. Command має одну explicit transaction, викликає `commit()` тільки
після успішного write/read-back, а exception або незакомічений context виконує
rollback і close. Query повертає DTO, від’єднаний від connection.

`StoragePort` і `JobPort` у C03 є лише inward-facing contracts. C03 не читає,
не копіює і не змінює originals та не запускає processing. Busy policy,
connection tuning, migration/concurrency/recovery gates завершує C04; durable
job lifecycle — C10.

## Compatibility adapter

Наявні `/api/contacts`, `/api/contacts/context`, `/api/contacts/{id}` і
`/api/contacts/{id}/roles` залишаються явним compatibility adapter до тих
самих application operations. Вони зберігають legacy success/error shape без
`apiVersion`; direct repository path для них відсутній. Contacts UI C03
використовує `/api/v1/contacts`, тому видимий UX не змінюється.

Legacy `/api/status` та інші unversioned slices не оголошуються частиною v1 і
мігруються окремими packages; C03 не починає C12.
