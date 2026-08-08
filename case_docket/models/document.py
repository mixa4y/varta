"""
case_docket.models.document
==============================
Document — сутність-КОНТЕЙНЕР (ADR-001, Рек.1): один документ може мати
кілька файлів (див. document_file.DocumentFile) — основний контент,
підпис, OCR-текст, транскрипт. "Документ = один файл" — модель, від
якої свідомо відмовились після архітектурного рев'ю.

СТАТУС: чорновий каркас Патча 0/4. Поля відповідають рішенням,
зафіксованим у розмові (категорія, джерело, формат), але вважати
остаточним лише після завершення Патча 4.

Технічне обмеження середовища: pydantic недоступний офлайн (немає
мережі для встановлення) — dataclass із валідацією в __post_init__
навмисно дублює той самий набір полів/типів, який матиме Pydantic-модель,
щоб міграція пізніше була рефактором, а не переписуванням.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from case_docket import dictionaries as dct


@dataclass
class Document:
    id: str
    case_id: str
    proceeding_id: str
    category: str                       # dictionaries: category (main/atch/tech)
    doc_type: str                        # dictionaries: doc_type_main/attachment/tech (перевіряється окремо, залежно від category)
    title: str
    source: str                           # dictionaries: document_source (user_original/court_registered)
    origin_format: str = "typed"           # dictionaries: origin_format
    requires_manual_review: bool = False
    source_archive: str | None = None       # ім'я zip, з якого імпортовано
    file_ids: list[str] = field(default_factory=list)  # -> DocumentFile.id (Рек.1)

    _CATEGORY_TO_DOC_TYPE_DICT = {
        "main": "doc_type_main",
        "atch": "doc_type_attachment",
        "tech": "doc_type_tech",
    }

    def __post_init__(self) -> None:
        if not dct.is_valid("category", self.category):
            raise ValueError(f"Невалидна category: {self.category!r}")
        if not dct.is_valid("document_source", self.source):
            raise ValueError(f"Невалидне source: {self.source!r}")
        if not dct.is_valid("origin_format", self.origin_format):
            raise ValueError(f"Невалидний origin_format: {self.origin_format!r}")

        doc_type_dict = self._CATEGORY_TO_DOC_TYPE_DICT[self.category]
        if not dct.is_valid(doc_type_dict, self.doc_type):
            raise ValueError(
                f"doc_type {self.doc_type!r} не належить словнику {doc_type_dict!r} "
                f"(category={self.category!r})"
            )
