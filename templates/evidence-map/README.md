# Evidence Map template

- `map-data.example.json` — порожній privacy-safe приклад snapshot.
- `../../config/schemas/map-data.schema.json` — формальний JSON Schema контракт.
- `../../caseflow/static/legal-case-map.html` — універсальна офлайн-в’юха.

Генератор повинен замінювати лише JSON-вміст елемента
`script#varta-map-data`, попередньо екранувавши послідовність `</script>`.
HTML не редагується як авторитетне джерело даних.

Для інтегрованого режиму цей самий контракт може передаватися через локальний
API. Для sealed export snapshot вбудовується в копію HTML, після чого
обчислюється SHA-256 готового артефакту.
