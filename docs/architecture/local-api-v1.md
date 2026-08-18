# VARTA local API v1 contract

| Metadata | Value |
|---|---|
| Status | `ACTIVE` |
| Version | `v1.0` |
| Date | `2026-08-18` |
| Owner | `C03` |

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

## Endpoints C03

| Method | Path | Application operation | Success |
|---|---|---|---|
| `GET` | `/api/v1/status` | мінімальна API/product capability відповідь | `200` |
| `GET` | `/api/v1/contacts?q=` | `ListContactsQuery` | `200` |
| `GET` | `/api/v1/contacts/context` | `GetContactsContextQuery` | `200` |
| `GET` | `/api/v1/contacts/{contact_id}` | `GetContactQuery` | `200` |
| `POST` | `/api/v1/contacts` | `CreateContactCommand` | `201` |
| `PATCH` | `/api/v1/contacts/{contact_id}` | `UpdateContactCommand` | `200` |
| `POST` | `/api/v1/contacts/{contact_id}/roles` | `AssignContactRoleCommand` | `201` |

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
