"""
case_docket.models.dates
===========================
DocumentDates — три дати документа (Патч 2): date_sent, date_delivered,
date_registered. Перевірка логічної послідовності НЕ кидає виняток —
порушення позначається (sequence_violation), бо саме такі порушення
часто і є доказом, а не помилкою введення, яку варто "проковтнути".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class DocumentDates:
    date_sent: date | None = None
    date_delivered: date | None = None
    date_registered: date | None = None

    def sequence_violation(self) -> str | None:
        """
        Опис порушення послідовності дат, або None якщо все гаразд.
        Правило: date_sent <= date_delivered <= date_registered
        (виняток: подання напряму в канцелярію -> date_sent == date_delivered).
        """
        if self.date_sent and self.date_delivered and self.date_sent > self.date_delivered:
            return f"date_sent ({self.date_sent}) > date_delivered ({self.date_delivered})"
        if self.date_delivered and self.date_registered and self.date_delivered > self.date_registered:
            return f"date_delivered ({self.date_delivered}) > date_registered ({self.date_registered})"
        return None

    def filename_date(self) -> date | None:
        """Дата для шаблону імені файлу (Патч 3): date_registered -> date_sent -> None
        (якщо None — рівень вище підставляє дату імпорту з позначкою 'приблизна')."""
        return self.date_registered or self.date_sent
