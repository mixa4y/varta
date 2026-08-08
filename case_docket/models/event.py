"""
case_docket.models.event
===========================
Event — канонічна модель часової події (ADR-001, Рек.4): подія є
ПЕРВИННОЮ сутністю, документ — можливий наслідок ("породжений") події,
а не навпаки. Одна Event може породжувати кілька Document
(наприклад: судове засідання -> протокол + ухвала одночасно).

Напрямок зв'язку формалізовано як канонічний:
Event.produced_document_ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from case_docket import dictionaries as dct


@dataclass
class Event:
    id: str
    case_id: str
    proceeding_id: str
    workflow_status: str                    # dictionaries: workflow_status
    interaction_type: str | None = None       # вільна форма взаємодії (напр. "Судове засідання") — не жорсткий словник
    event_date: str | None = None              # ISO 8601
    sender_id: str | None = None                # -> Actor.id
    recipient_id: str | None = None
    produced_document_ids: list[str] = field(default_factory=list)  # Event -> Document (Рек.4)

    def __post_init__(self) -> None:
        if not dct.is_valid("workflow_status", self.workflow_status):
            raise ValueError(f"Невалидний workflow_status: {self.workflow_status!r}")
