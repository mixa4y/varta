"""
case_docket.models.actor
===========================
Actor — суб'єкт справи (Патч 5, піднятий вище за первинним планом —
без нього sender_id/recipient_id довелось би зберігати як вільний текст).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from case_docket import dictionaries as dct


@dataclass
class Actor:
    id: str
    name: str
    role: str                             # dictionaries: actor_role
    proceeding_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not dct.is_valid("actor_role", self.role):
            raise ValueError(f"Невалидна role: {self.role!r}")
