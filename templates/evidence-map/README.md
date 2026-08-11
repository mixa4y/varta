# Evidence Map template

- `map-data.example.json` — максимально повний privacy-safe приклад snapshot
  schema `1.1.0`: усі формалізовані колекції та лічильники присутні, а
  невідомі факти залишаються `null` або порожніми.
- `../../config/schemas/map-data.schema.json` — формальний JSON Schema контракт.
- `../../caseflow/static/legal-case-map.html` — універсальна офлайн-в’юха.

Генератор повинен замінювати лише JSON-вміст елемента
`script#varta-map-data`, попередньо екранувавши послідовність `</script>`.
HTML не редагується як авторитетне джерело даних.

Snapshot містить окремі колекції `proceedings`, `actors`, `files`,
`documents`, `events`, `claims`, `relations`, `sourceReferences`,
`reviewDecisions` та `exclusions`. Додавання нового довільного поля без
оновлення JSON Schema не допускається.

Для інтегрованого режиму цей самий контракт може передаватися через локальний
API. Для sealed export snapshot вбудовується в копію HTML, після чого
обчислюється SHA-256 готового артефакту.
