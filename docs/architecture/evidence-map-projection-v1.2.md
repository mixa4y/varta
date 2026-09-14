# C11 — Evidence Map projection 1.2

## Межа й сумісність

`EvidenceMapProjectionService` читає виключно `EvidenceMapSourceQueryService`.
`project()` не має audit port і не виконує SQL, записів файлів або commit.
`export()` використовує той самий generator і явно переданий audit port;
транзакцією, commit та rollback керує caller. UI-caller тут означає application
consumer, а не реалізований браузерний UI C12.

Нова схема `config/schemas/map-data-v1.2.schema.json` зберігає findings,
їхні decisions, automatic/review versions, membership IDs та справжній
`caseProfileId`. Невідомий номер провадження залишається null.
Попередня `map-data.schema.json` 1.1.0 незмінна: старі snapshots не мігруються.
Case profile залишається 1.1.0; audit adapter явно дозволяє пару profile 1.1.0 /
snapshot 1.2.0, не довільну несумісність версій. Нові consumers мають обрати 1.2.

## Детермінізм і достовірність

Усі масиви цієї проєкції — множини/мультимножини, нормалізовані за canonical JSON.
Ключі впорядковані; UTF-8, compact separators, finite numbers, UTC timestamps.
Хеш не включає `exportId`, `generatedAt` і власне `sourceSnapshotSha256`.
Він включає source revision, exact profile identity/version, схему й export mode.
`generatedAt` дорівнює persisted data cutoff, а не часу відкриття екрана.
Hash не є цифровим підписом або доказом автентичності зовнішнього snapshot.

До повернення результату обов'язкові source graph validation, JSON Schema з
format checks, projected reference/basis checks та hash verification.
Source errors не підмінюються порожньою мапою. Реєстровий SHA джерела має
відповідати реєстровому SHA файла. Байти originals не читаються/не змінюються;
це не повторна фізична перевірка КЕП чи сховища. Відомий integrity status
файлів зберігається. Непідтверджені твердження та exclusions залишаються видимими.
`documentId` файла заповнюється лише для одного однозначного власника;
many-to-many зв'язки залишаються у documents.fileIds.

Поля, яких немає в typed source (signature/derivation/processing associations,
процесуальні ролі проваджень), не вгадуються; export містить limitations.
Inventory рахує поточну проєкцію, не історичні заявлені обсяги.
`missingSourceCount` — claims/relations без basis/source; manual review count —
entities/dispositions зі статусами manual_review_required, in_review або open.

## Режими й безпека

- `full_local`: повна локальна проєкція; не означає дозвіл публікації.
- `metadata_only`: немає excerpts, claim text, notes, summaries/descriptions та
  storage/source paths. Назви, ID й інша metadata залишаються: це **не анонімізація**.
- `redacted`: fail closed до появи явної перевіреної redaction policy; не можна
  просто змінити назву режиму й видати приватні дані за знеособлені.

`sealed=false` завжди: C11 не сертифікує sealed packaging C14.
Генератор не відкриває HTML, не публікує справу й не створює export-файлів.

## Composition і запуск

Startup/migrations відокремлені від проєкції. Потрібно підготувати й повторно
використовувати один `SQLiteUnitOfWorkFactory` перед відкриттям audit transaction:

```python
factory = SQLiteUnitOfWorkFactory(database)
factory.prepare()
source = EvidenceMapSourceQueryService(SQLiteEvidenceMapSourcePorts(factory))
generator = EvidenceMapProjectionService(source)
snapshot = generator.project(request, export_id="local-view")
with factory(write=True) as uow:
    snapshot = generator.export(
        request, export_id="explicit-export", generated_by=reviewer,
        audit=uow.evidence_map_exports,
    )
    uow.commit()
```

Не ініціалізувати другий непідготовлений factory всередині write transaction:
його startup намагатиметься взяти SQLite write lock. Відповідальність за
серіалізацію конкурентних змін під час багатоопераційного source query лишається
у composition layer; C11 не називає це атомарним snapshot довільно змінюваної БД.

## Докази

`tests/test_evidence_map_projection_c11.py`: populated synthetic golden, restart,
order/hash, projection DB invariance, UI/export parity, persisted/idempotent audit,
conflict/rollback, schema/links/basis/timestamps, exclusions і privacy modes.
Golden fixture `tests/fixtures/c11/populated.json` перевіряє весь результат,
включно з findings, обома reviews та реальною для fixture ідентичністю профілю.
Результати gates і fingerprints — локальний C11 checkpoint, не цей опис.
