# Expected Reports

| Metadata | Value |
|---|---|
| Status | `DRAFT` |
| Version | `v0.1` |
| Date | `2026-07-24` |

## Загальні вимоги

Кожен звіт має містити `report_id`, час формування, версію CSMD, scope, використані джерела, обмеження та посилання на записи системи. Звіт не повинен замовчувати помилки або подавати невизначеність як факт.

## `intake_inventory_report`

Перелік імпортованих файлів: оригінальна назва, джерельний шлях, розмір, media type, SHA-256, статус імпорту, warnings і errors.

## `integrity_verification_report`

Результати повторної перевірки SHA-256, еталон, час і статус `verified`, `mismatch`, `reference_unavailable` або `error`.

## `document_matching_report`

Порівнювані об'єкти, рівні аналізу, сигнали, результат, confidence, limitations і посилання на diff artifacts.

## `attachment_validation_report`

Заявлені додатки, фактичні кандидати, відповідності, відсутні й незаявлені елементи, невирішені випадки.

## `signature_verification_report`

Технічний статус підпису, хеші, публічні реквізити сертифіката, час, джерела статусу, warnings і errors. Секрети не включаються.

## `case_timeline_report`

Події у хронологічному порядку, точність часу, джерело кожної події, confidence і review status.

## `findings_report`

Findings за severity і type, предмет перевірки, evidence references, автоматичний висновок, ручне рішення та статус.

## `audit_report`

Хронологія значущих операцій і змін. Звіт має дозволяти встановити, хто або який компонент виконав дію та над яким об'єктом.

## Формати

Машинний JSON є базовим форматом обміну. Людиночитні HTML/PDF/CSV визначаються окремо. Формування PDF не повинно бути єдиним способом доступу до даних звіту.

## Open questions

| Question | Owner stage | Closing gate |
|---|---|---|
| Обов'язкові reports першого release | `C13`, `C14` | workflow/export PASS |
| Signature/timestamp для exported report | `C14`, `P02` | export/processor decision gate |
| Role/redaction masking | `C14`, `C16` | export + privacy gate |
