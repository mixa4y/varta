# ADR-004: Opaque identity, external references and cardinality

| Metadata | Value |
|---|---|
| Status | `APPROVED` |
| Version | `v1.0` |
| Decision date | `2026-08-18` |
| Owner | `C02` |

## Контекст

Номер справи, назва файла, шлях, display name і ID зовнішньої системи можуть
змінюватися, повторюватися або з'являтися лише після intake. Використання цих
значень як primary identity робить links нестабільними. Документи, події,
учасники, claims і джерела також можуть належати кільком провадженням або
мати кілька взаємозв'язків.

## Рішення

- кожна independently addressable entity має application-generated opaque
  internal ID, який зберігається як canonical lowercase UUID text;
- v1 native records використовують UUIDv4; clients і API трактують будь-який
  ID як opaque string і не покладаються на UUID version чи порядок;
- stable import може використовувати persisted mapping або namespaced UUIDv5,
  але зовнішнє значення й provenance зберігаються окремо;
- internal identity не залежить від case number, display name, literal
  filename, managed path, hash або external record ID;
- external references мають щонайменше `system`, `kind`, `raw_value`/
  `normalized_value` та provenance scope; їхня унікальність визначається
  окремим provider contract, не глобальним припущенням;
- file content identity (`sha256`) не дорівнює entity identity: однакові байти
  можуть мати різні provenance/roles;
- many-to-many relations моделюються link entities/tables із type, role,
  order, provenance й, де потрібно, history;
- documents/events/claims не отримують єдиний authoritative
  `proceeding_id`, якщо domain допускає кілька проваджень;
- rename/move/export ніколи не створює нову identity сам по собі.

API й application DTOs передають context IDs явно. UI `active_case_id` є лише
presentation context і не замінює `case_id` у command/query.

## Відхилені альтернативи

1. **Case number як primary key.** Може бути невідомим, неоднозначним або
   виправленим.
2. **Шлях/filename як identity.** Змінюється при migration і collision handling.
3. **SHA-256 як єдиний file record ID.** Втрачає окремі provenance occurrences.
4. **External provider ID як internal primary key.** Створює coupling і
   collisions між systems.
5. **Comma-separated IDs або один `proceeding_id`.** Не моделює attributes,
   provenance та справжню many-to-many cardinality.

## Наслідки

Display/reference changes не ламають links. Importer має вести явне mapping
та idempotency. Join tables збільшують кількість queries, але роблять
cardinality й constraints перевірюваними. UI не може виводити domain context
лише з URL/path/name.

## Вплив на міграцію

- існуючі TEXT IDs залишаються сумісними; C02 не переписує rows або schema;
- `C03` типізує IDs як opaque strings у commands/queries/DTOs;
- `C07` реалізує temporary `intake_case_id`, candidates і explicit activation;
- `C08` вирівнює document/event/proceeding та evidence cardinalities через
  versioned migrations і services;
- `C09` зберігає legacy IDs як external references/mapping, не як приховані
  primary identifiers.

## Пов'язані рішення

- [ADR-005](ADR-005-workspace-and-managed-storage.md)
