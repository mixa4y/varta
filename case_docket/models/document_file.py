"""
case_docket.models.document_file
====================================
DocumentFile — окремий фізичний файл, що належить Document (ADR-001,
Рек.1). Один Document може мати кілька DocumentFile різного призначення
(kind): основний вміст, підпис, OCR-текст, транскрипт, знімок метаданих.

Приклад: Document "Позовна заява" -> DocumentFile(kind=content, .pdf),
DocumentFile(kind=signature, .p7s), DocumentFile(kind=ocr_text).
"""

from __future__ import annotations

from dataclasses import dataclass

_VALID_KINDS = frozenset({
    "content",             # сам файл (pdf/docx/xlsx/...)
    "signature",            # КЕП/ЄЦП контейнер або XML підпису
    "ocr_text",              # результат OCR
    "transcript",             # результат STT (аудіо/відео -> текст)
    "metadata_snapshot",       # знімок файлових метаданих на момент імпорту
})


@dataclass
class DocumentFile:
    id: str
    document_id: str                  # -> Document.id
    kind: str                          # одне з _VALID_KINDS
    path: str                           # шлях у файловій системі (originals/working)
    file_hash: str | None = None          # SHA-256, обов'язковий для kind="content"
    mime_type: str | None = None
    confidence: float | None = None        # Рек.3: ЛИШЕ якщо є реальний вимірюваний
                                             # алгоритм (OCR engine score, STT confidence).
                                             # Заборонено вигадувати число "на око" —
                                             # немає джерела -> None, не placeholder.

    def __post_init__(self) -> None:
        if self.kind not in _VALID_KINDS:
            raise ValueError(f"Невалидний kind: {self.kind!r}. Дозволено: {sorted(_VALID_KINDS)}")
        if self.kind == "content" and self.file_hash is None:
            raise ValueError("DocumentFile(kind='content') повинен мати file_hash (SHA-256)")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence має бути в межах [0.0, 1.0] або None")
