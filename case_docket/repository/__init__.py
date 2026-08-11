"""Repository Layer (ADR-001, Рек.8) — бізнес-логіка не знає, де фізично зберігаються дані."""

from .base import Repository
from .migrations import MigrationError, MigrationRunner
from .sqlite_repository import SQLiteRepository

__all__ = ["MigrationError", "MigrationRunner", "Repository", "SQLiteRepository"]
