# Integrations API

| Metadata | Value |
|---|---|
| Status | `DRAFT` |
| Version | `v0.1` |
| Date | `2026-07-24` |

## Призначення

Визначити нейтральні контракти адаптерів без вигадування API конкретних постачальників. Core CSMD працює без зовнішніх інтеграцій.

## Принципи

- Adapter є необов'язковим і явно вмикається.
- Domain не імпортує SDK зовнішньої системи.
- Mapping між зовнішньою та внутрішньою моделями ізольований.
- Вхідні дані проходять ті самі intake, hashing і audit rules.
- Вихідна операція потребує явного scope та журналу.
- Secrets передаються через credential provider, а не через документи чи БД домену.

## Концептуальні порти

### `ImportSourceAdapter`

Операції: перевірити доступність джерела, перелічити доступні об'єкти, відкрити потік читання, повернути provenance metadata. Контракт не повинен вимагати локального шляху.

### `ExportDestinationAdapter`

Операції: перевірити destination, підготувати export, передати явно обрані artifacts, повернути external references і помилки. Повторна спроба не повинна створювати невидимі дублікати.

### `ReferenceLookupAdapter`

Read-only lookup довідкових або статусних даних із фіксацією джерела, часу й raw response reference, якщо це дозволено.

## Спільний результат

Adapter result повинен мати `operation_id`, `status`, `started_at`, `completed_at`, `items`, `warnings`, `errors`, `external_references` та `provenance`. Точні Python types і JSON schema ще не затверджені.

## Помилки

Розрізняти authentication, authorization, timeout, rate limit, validation, remote unavailable, unsupported operation і internal adapter error. Повідомлення не повинні містити секрети.

## Airtable

Airtable не використовується в core. Будь-який майбутній Airtable adapter вимагатиме окремого рішення, mapping та явного увімкнення; він не може стати джерелом істини без нового ADR.

## Open questions

- Чи потрібні інтеграції взагалі в першому релізі?
- Яка політика idempotency, retries і offline queue?
- Які класи даних заборонено передавати назовні?
