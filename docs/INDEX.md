# Індекс документації VARTA

## Канонічні документи baseline 0.1.0

1. `../README.md` — назва, межа продукту, структура й запуск.
2. `../PROJECT_STATUS.md` — підтверджений поточний стан і відкриті рішення.
3. `../AGENTS.md` — правила роботи в репозиторії та privacy boundary.
4. `blueprints/evidence-map-blueprint.md` — універсальна специфікація мапи.
5. `source-inventory.md` — що перенесено й що свідомо виключено.
6. `../config/schemas/case-profile.schema.json` — контракт профілю справи.
7. `../config/schemas/map-data.schema.json` — контракт snapshot мапи.
8. `../templates/case/case-profile.example.json` — порожній профіль.
9. `../templates/evidence-map/map-data.example.json` — порожній snapshot.
10. `../caseflow/static/legal-case-map.html` — дизайн офлайн-в’юхи.

## Імпортовані матеріали для звірки

Каталог `architecture/` містить успадкований пакет проєктної документації
CMSD. Його файли не стають автоматично погодженими лише через перенесення.
Якщо правило суперечить канонічним документам вище, до окремого рішення діє
канонічний baseline VARTA.

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
