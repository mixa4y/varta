# ADR-006: Local HTTP security boundary

| Metadata | Value |
|---|---|
| Status | `APPROVED` |
| Version | `v1.0` |
| Decision date | `2026-08-18` |
| Owner | `C02` |

## Контекст

Loopback зменшує exposure, але сам по собі не захищає від wildcard binding,
DNS rebinding, hostile web origins, CSRF, remote assets або витоку token через
URL/log. Поточний server уже має loopback restriction, mutating-request token
і CSP, але повний target contract потрібно зафіксувати до переведення UI на
`/api/v1`.

## Рішення

Integrated VARTA web surface є **loopback-only**:

- default bind — explicit `127.0.0.1`; `localhost`/`::1` допустимі лише після
  перевірки, що всі resolved/bound addresses є loopback;
- `0.0.0.0`, `::`, LAN interface, port forwarding і remote mode заборонені;
- `Host` перевіряється за allowlist фактичного loopback host + bound port;
- browser mutations приймаються лише з exact allowed `Origin` та правильним
  cryptographically random per-launch CSRF token у header;
- token не передається в query string, не потрапляє до logs і змінюється при
  новому запуску;
- CORS вимкнено за замовчуванням; unknown/missing browser origin для mutation
  не отримує implicit trust;
- CSP використовує local/self assets і забороняє remote scripts, fonts,
  frames та unsafe network fallbacks; remote assets відсутні за замовчуванням;
- sensitive API/bootstrap responses мають `Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` і
  frame protection через CSP;
- static/API path normalization відхиляє traversal, encoded traversal і
  доступ поза allowlisted roots;
- optional OAuth callback може існувати лише на loopback з перевіреним
  state/PKCE contract свого adapter і не послаблює основний Host/Origin gate.

OS account permissions і workspace ACL є boundary для локальних файлів.
HTTP token не замінює disk encryption, Windows sign-in або secret storage.
TLS не вимагається для loopback-only v1; будь-яке network exposure,
multi-user auth або remote access потребує нового ADR із TLS/auth/session
model та threat review.

## Відхилені альтернативи

1. **Wildcard/LAN bind із попередженням.** Попередження не створює security
   boundary.
2. **Перевіряти лише client IP.** Не захищає від DNS rebinding/host confusion.
3. **Довіряти будь-якому Origin на localhost.** Дозволяє hostile browser page
   викликати local API.
4. **CSRF token у URL або довгоживучий static token.** Витікає через history,
   logs і копіювання links.
5. **CDN/remote fonts/scripts by default.** Порушує offline/privacy та CSP.
6. **Вважати loopback повною authentication model.** Не враховує інші local
   processes/users і доступ до workspace.

## Наслідки

Bookmarks не повинні містити secrets. Інтеграційні/browser tests мають
перевіряти accepted/rejected Host, Origin, CSRF, CSP, traversal та zero remote
assets. Remote use не вмикається configuration flag без нового ADR.

Поточна реалізація є лише partial evidence: C02 затверджує target contract,
але не заявляє, що всі headers/negative cases уже реалізовані.

## Вплив на міграцію

- `C03` визначає versioned HTTP error/DTO boundary без LAN mode;
- `C12` переносить handlers на application services і реалізує/тестує повний
  Host/Origin/CSRF/CSP contract;
- `C15` повторює boundary tests для packaged application;
- `C16` виконує privacy/security acceptance, включно з hostile origin/path
  cases.

## Пов'язані рішення

- [ADR-001](ADR-001-system-architecture.md)
