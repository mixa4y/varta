from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ListContactsQuery:
    search: str | None = None


@dataclass(frozen=True, slots=True)
class GetContactQuery:
    contact_id: str


@dataclass(frozen=True, slots=True)
class GetContactsContextQuery:
    """Return case/proceeding choices used by the existing contacts card."""
