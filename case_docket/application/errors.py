from __future__ import annotations

from typing import ClassVar, Mapping


class ApplicationError(Exception):
    code: ClassVar[str] = "application_error"

    def __init__(self, message: str, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


class ValidationError(ApplicationError):
    code = "validation_error"


class NotFoundError(ApplicationError):
    code = "not_found"


class ConflictError(ApplicationError):
    code = "conflict"
