from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Self


@dataclass(frozen=True, slots=True)
class CaseProfileDTO:
    case_id: str
    profile_version: str
    schema_version: str
    profile: dict[str, object]
    profile_sha256: str
    status: str
    created_by: str
    created_at: str
    activated_at: str | None


class CaseProfileRepositoryPort(Protocol):
    def get(self, case_id: str, profile_version: str) -> CaseProfileDTO | None: ...

    def case_exists(self, case_id: str) -> bool: ...

    def versions(self, case_id: str) -> tuple[str, ...]: ...


class CaseProfileUnitOfWork(Protocol):
    @property
    def case_profiles(self) -> CaseProfileRepositoryPort: ...

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    def rollback(self) -> None: ...


class CaseProfileUnitOfWorkFactory(Protocol):
    def __call__(self, *, write: bool = False) -> CaseProfileUnitOfWork: ...
