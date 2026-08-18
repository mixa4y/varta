# Індекс документації VARTA

## Канонічні документи baseline 0.1.0

1. `../README.md` — назва, межа продукту, структура й запуск.
2. `../PROJECT_STATUS.md` — підтверджений поточний стан і відкриті рішення.
3. `../AGENTS.md` — правила роботи в репозиторії та privacy boundary.
4. `architecture/architecture-decision-log.md` — approved ADR-реєстр C02.
5. `architecture/technical-specification.md` — approved target/acceptance spec.
6. `architecture/open-questions.md` — versioned owner/gate routing.
7. `action-algorithm.md` — порядок оцінки, рішень, реалізації та приймання.
8. `interactive/varta-action-map.html` — інтерактивне подання етапів `A0`–`A12`.
9. `chat-roadmap.md` — канонічні work packages `C01`–`C16`/`P01`–`P04`.
10. `interactive/varta-chat-roadmap.html` — статичне/live companion-подання.
11. `roadmap-controller.md` — execution/Git checkpoint contract.
12. `blueprints/evidence-map-blueprint.md` — універсальна специфікація мапи.
13. `airtable-sql-migration.md` — повне відображення Airtable у SQLite.
14. `source-inventory.md` — що перенесено й що свідомо виключено.
15. `../config/schemas/case-profile.schema.json` — контракт профілю справи.
16. `../config/schemas/map-data.schema.json` — контракт snapshot мапи.
17. `../templates/case/case-profile.example.json` — порожній профіль.
18. `../templates/evidence-map/map-data.example.json` — порожній snapshot.
19. `../caseflow/static/legal-case-map.html` — дизайн офлайн-в’юхи.

## Імпортовані матеріали для звірки

Каталог `architecture/` містить approved C02 ADR/spec package та успадковані
detail drafts. Лише файли зі статусом `APPROVED`/`ACTIVE` у manifest входять
до чинної architecture boundary. За суперечності draft поступається ADR.

## Порядок спільного перегляду

1. структура папок і privacy boundary;
2. змінні та case profile;
3. сутності й зв’язки;
4. файлова ієрархія та транслітеровані назви;
5. Evidence Map contract і статуси доказів;
6. маршрути, кнопки й збереження контексту у в’юсі;
7. SQLite/XLSX migration adapter;
8. Windows install/release/update.

Після погодження пункт отримує окреме рішення або нову версію документа.
Попередній варіант позначається `SUPERSEDED`, а не переписується мовчки.
