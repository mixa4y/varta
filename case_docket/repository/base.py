"""
case_docket.repository.base
=============================
Абстрактний шар доступу до даних (ADR-001, Рек.8).

Бізнес-логіка (naming, compliance, version_check, workflow, ...) звертається
ЛИШЕ до цього інтерфейсу, ніколи напряму до SQLite чи Airtable. Це дозволяє
замінити сховище (SQLite → PostgreSQL) без зміни жодного рядка бізнес-логіки.

Чому це взагалі існує: оригінальні вимоги CSMD (п.7, п.9) від самого
початку визначали SQLite як основну локальну БД, а Airtable — як таке,
що НЕ є частиною основної архітектури. Ця абстракція — повернення до
того вихідного рішення після дрейфу в бік Airtable-як-джерела-правди.

СТАТУС: каркас Патча 0. Generic CRUD + обов'язковий audit log реалізовано
повністю. Специфічні для сутностей методи (find_by_hash, find_by_proceeding
тощо) з'являться разом із відповідними патчами (Document — Патч 4,
Actor — Патч 5, compliance_flags — Патч 7, version_match — Патч 8) —
додавання нового методу до абстракції не ламає наявні реалізації.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Optional


class Repository(ABC):
    """Мінімальний контракт сховища. Кожна конкретна реалізація
    (SQLiteRepository або майбутній локальний адаптер) має його дотримуватись."""

    # --- generic record access ------------------------------------------------
    @abstractmethod
    def insert(self, table: str, record: dict[str, Any]) -> str:
        """Вставляє запис у таблицю, повертає id (згенерований, якщо не заданий)."""

    @abstractmethod
    def get(self, table: str, record_id: str) -> Optional[dict[str, Any]]:
        """Повертає запис за id, або None."""

    @abstractmethod
    def update(self, table: str, record_id: str, fields: dict[str, Any]) -> None:
        """Часткове оновлення полів запису. Кидає KeyError, якщо запис не існує."""

    @abstractmethod
    def query(self, table: str, where: Optional[dict[str, Any]] = None) -> Iterable[dict[str, Any]]:
        """Повертає записи таблиці, опційно відфільтровані за точним співпадінням полів."""

    # --- audit log (обов'язковий для БУДЬ-ЯКОЇ реалізації — п.11 CSMD) --------
    @abstractmethod
    def record_audit_event(
        self,
        action: str,
        entity_table: str,
        entity_id: Optional[str],
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Append-only запис у журнал дій. Ніколи не редагується і не видаляється —
        це саме та відтворюваність, якої вимагає п.11 оригінальних інструкцій CSMD.
        """

    @abstractmethod
    def get_audit_log(
        self,
        entity_table: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> Iterable[dict[str, Any]]:
        """Повертає журнал дій, опційно відфільтрований за таблицею/записом."""
