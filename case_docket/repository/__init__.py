"""Repository Layer (ADR-001, Рек.8) — бізнес-логіка не знає, де фізично зберігаються дані."""

from .base import Repository
from .migrations import MigrationError, MigrationRunner
from .sqlite_repository import SQLiteRepository
from .sqlite_uow import SQLiteUnitOfWork, SQLiteUnitOfWorkFactory

__all__ = [
    "MigrationError",
    "MigrationRunner",
    "Repository",
    "SQLiteRepository",
    "SQLiteUnitOfWork",
    "SQLiteUnitOfWorkFactory",
]
