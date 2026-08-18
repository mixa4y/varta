# CSMD Data Model

| Metadata | Value |
|---|---|
| Status | `DRAFT DETAIL` |
| Version | `v0.2` |
| Date | `2026-08-18` |

## Призначення

Документ описує концептуальну модель SQLite. Точні SQL-типи, обмеження та індекси затверджуються окремою схемою й міграціями.

## Базові правила

- Стабільні ключі мають машинні англомовні назви в `snake_case`.
- Відображувані назви не використовуються як первинні ідентифікатори.
- Час зберігається у форматі ISO 8601 із часовою зоною, де вона відома.
- Невідоме значення не підмінюється порожнім рядком або вигаданим фактом.
- Автоматичні результати та підтвердження користувача зберігаються окремо.
- Внутрішні IDs є opaque canonical UUID strings; зовнішні references та
  display/path values не використовуються як primary identity (`ADR-004`).
- Membership, що допускає кілька справ/проваджень, моделюється link tables, а
  не одним прихованим foreign key або списком у text.

## Сутності

### `cases`

Контейнер верхнього рівня для матеріалів справи. Можливі атрибути: `id`, `display_name`, `external_reference`, `status`, `created_at`, `updated_at`. Конкретні судові реквізити не є обов'язковими до затвердження вимог.

### `proceedings`

Провадження в межах справи: `id`, `case_id`, `kind`, `external_reference`, `status`.

### `import_batches`

Операція приймання: `id`, `source_type`, `source_label`, `started_at`, `completed_at`, `status`, `error_summary`.

### `files`

Фізичний або логічний файловий об'єкт: `id`, `import_batch_id`, `original_name`, `source_relative_path`, `storage_relative_path`, `size_bytes`, `extension`, `media_type`, `sha256`, `created_time_source`, `modified_time_source`, `imported_at`, `status`.

### `documents`

Логічний документ, який може мати кілька файлів або версій: `id`, `case_id`, `document_type`, `title`, `document_date`, `external_reference`, `review_status`.

### `document_files`

Зв'язок документа з файлом: `document_id`, `file_id`, `role`, `sequence_number`.

### `participants` і `contacts`

Учасник у контексті справи та окрема контактна сутність. Перелік персональних полів визначається після аналізу правових підстав і мінімізації даних.

### `events`

Подія хронології: `id`, `case_id`, `event_type`, `occurred_at`, `precision`, `source_document_id`, `description`, `confidence`, `review_status`.

### `attachments`

Заявлений або фактичний додаток: `id`, `parent_document_id`, `file_id`, `declared_name`, `declared_count`, `actual_count`, `status`.

### `signatures` і `certificates`

Результати перевірки підпису та відомості відкритого сертифіката. Приватний ключ і пароль у БД не зберігаються.

### `document_relations`

Зв'язок між документами: `source_document_id`, `target_document_id`, `relation_type`, `confidence`, `review_status`.

### `processing_runs`

Відтворювана операція: `id`, `run_type`, `tool_name`, `tool_version`, `parameters_json`, `started_at`, `completed_at`, `status`, `error_details`.

### `findings`

Структурований результат аналізу: `id`, `finding_type`, `severity`, `subject_type`, `subject_id`, `message`, `evidence_json`, `review_status`.

### `audit_log`

Додавальний журнал значущих дій: `id`, `occurred_at`, `actor_type`, `actor_id`, `action`, `subject_type`, `subject_id`, `details_json`.

## Важливі зв'язки

- `case` має багато `proceedings`; documents/events можуть бути пов'язані зі
  справами та провадженнями через explicit many-to-many links.
- `import_batch` має багато `files`.
- `document` пов'язаний із файлами через `document_files`.
- `document` може мати багато `attachments`, `signatures` і relations.
- `processing_run` пов'язує входи, виходи та findings через окремі таблиці зв'язків, які ще треба визначити.

## Assumptions

- Усі первинні ключі генеруються застосунком.
- SHA-256 зберігається у нормалізованому lowercase hexadecimal форматі.
- Native v1 IDs використовують UUIDv4; stable import mappings можуть
  використовувати persisted mapping/namespaced UUIDv5, але API трактує ID як
  opaque string.

## Open questions

| Question | Owner stage | Closing gate |
|---|---|---|
| Чи потрібна історичність beyond append-only audit/review history? | `C08` | `C08 PASS` |
| Які персональні поля справді необхідні? | `C08`, `C16` | model gate + final privacy gate |
| Як моделювати сторінки, OCR-фрагменти й координати тексту? | `P01` | `P01 PASS` |

Формат identity/cardinality більше не open; його закриває `ADR-004`.
