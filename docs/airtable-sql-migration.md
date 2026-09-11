# Перенесення Airtable у SQLite

**Статус:** `IMPLEMENTED`

**Локальне джерело істини:** SQLite і файлове сховище

**Роль Airtable:** контрольований import source, не паралельна writable база

## Охоплення

Історичний schema snapshot відтворено без записів користувачів і без
облікових даних:

| Показник | Кількість |
| --- | ---: |
| Таблиці | 9 |
| Поля | 127 |
| `multipleRecordLinks` | 38 |
| Computed fields | 12 |
| Lookup fields | 10 |
| Formula fields | 2 |

Таблиці джерела: `Контакти`, `Справи`, `Провадження`, `Події`, `Документи`,
`Учасники справи`, `document_links`, `compliance_flags` і
`document_version_match`.

## SQL-модель

Основні сутності зберігаються у `contacts`, `cases`, `proceedings`, `events`,
`documents`, `actors`, `case_participants`, `document_links`,
`compliance_flags` і `document_version_match`. Файли документів винесені в
`document_files`, щоб не змішувати метадані документа з незмінним оригіналом.

Many-to-many та контекстні зв'язки нормалізовані у `contact_cases`,
`contact_proceedings`, `case_proceedings`, `case_events`, `case_documents`,
`proceeding_events`, `proceeding_documents`, `proceeding_relations`,
`event_documents` і `event_contacts`. Для зв'язків з додатковим змістом
збережено тип: основне провадження, членство, відправник або одержувач.

Повний каталог Airtable IDs, назв, типів, select choices, linked-table
залежностей, формул та lookup fields міститься у таблицях
`airtable_*_mappings`. Представлення `v_cases`, `v_events` і
`v_contact_proceeding_details` відтворюють computed значення без дублювання
їх як редагованих даних.

## Імпорт записів

`case_docket.airtable.import_airtable_snapshot()` виконує імпорт у два проходи:

1. створює або оновлює всі локальні сутності та таблицю відповідності ID;
2. матеріалізує record links після того, як усі target records уже відомі.

Повторний імпорт idempotent. Оригінальні Airtable record IDs і raw JSON
зберігаються для provenance. Посилання на відсутній record не відкидається
мовчки: воно залишається у `airtable_record_links` і відображається через
`v_airtable_unresolved_links`.

Importer приймає таблиці за Airtable table ID, історичною назвою або SQL
назвою. Поля можна передавати за field ID; назва поля підтримується лише тоді,
коли вона однозначна в межах таблиці.

## Контакти

Картка контакту зберігає категорію, ідентифікаційні дані, комунікаційні
канали, адресу, реквізити компанії, банк, нотатки та timestamps. Ролі контакту
у справі або провадженні живуть окремо у `case_participants`, тому одна особа
може мати різні ролі в різних контекстах.

Локальний API надає список, пошук, повну картку, створення, редагування та
призначення ролі. В'юха використовує цей API і не звертається до SQLite
напряму.

## Межа приватності

`config/airtable_schema.json` містить лише структуру. Реальні записи,
вкладення, API keys, OAuth tokens і локальна SQLite база не комітяться.
Імпорт авторизованого набору проваджень має виконуватися локально у вибраний
workspace з окремою перевіркою кількості записів, unresolved links та
read-back після перезапуску.
