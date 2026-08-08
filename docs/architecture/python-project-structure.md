# Python Project Structure

| Metadata | Value |
|---|---|
| Status | `DRAFT` |
| Version | `v0.1` |
| Date | `2026-07-24` |

## Рекомендована структура

```text
csmd/
├── pyproject.toml
├── README.md
├── AGENTS.md
├── src/
│   └── csmd/
│       ├── domain/
│       ├── application/
│       ├── infrastructure/
│       ├── presentation/
│       ├── config/
│       └── __main__.py
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docs/
│   ├── adr/
│   ├── specification/
│   └── data-model/
└── tools/
```

## Межі шарів

### `domain`

Сутності, value objects, доменні правила й типи результатів. Не залежить від SQLite, UI, файлової системи або зовнішніх SDK.

### `application`

Use cases, команди, запити, orchestration і порти. Координує domain та інфраструктурні інтерфейси.

### `infrastructure`

SQLite repositories, filesystem storage, parsers, hashing, OCR, signature tools, logging та adapters.

### `presentation`

CLI, desktop або local web UI. Не містить доменної логіки.

## Модулі можливостей

Можливості `intake`, `inventory`, `metadata`, `classification`, `signatures`, `matching`, `attachments`, `timeline`, `relationships`, `transcription`, `reporting` та `audit` можуть бути підпакетами відповідного шару. Фінальне групування визначається після першого вертикального use case.

## Інженерні правила

- `pathlib`, type hints і docstrings для публічних API.
- Явна обробка помилок без порожніх `except`.
- Структуровані logs без секретів.
- Міграції SQLite під контролем версій.
- Unit tests для domain, integration tests для SQLite і файлового сховища.
- Залежності додаються лише з поясненням і ліцензійною перевіркою.

## Assumptions

- Використовується `src` layout.
- Конкретні framework, ORM, migration tool, CLI та UI ще не обрані.

## Open questions

- Мінімальна версія Python?
- Чи потрібен ORM, чи достатньо явного SQL?
- Який формат конфігурації та dependency injection?
