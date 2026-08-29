from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator, ValidationError as SchemaValidationError

from .errors import NotFoundError, ValidationError
from .profile_ports import CaseProfileDTO, CaseProfileUnitOfWorkFactory


class UnknownCaseError(NotFoundError):
    code = "unknown_case"


class MissingProfileError(NotFoundError):
    code = "missing_profile"


class MissingProfileVersionError(NotFoundError):
    code = "missing_profile_version"


class InvalidProfileError(ValidationError):
    code = "invalid_profile"


@dataclass(frozen=True, slots=True)
class GetCaseProfileQuery:
    case_id: str
    profile_version: str


class CaseProfileService:
    def __init__(
        self,
        unit_of_work_factory: CaseProfileUnitOfWorkFactory,
        *,
        schema_path: Path | None = None,
    ):
        self._uow_factory = unit_of_work_factory
        self._schema_path = (
            schema_path
            or Path(__file__).parents[2] / "config" / "schemas" / "case-profile.schema.json"
        )

    def get(self, query: GetCaseProfileQuery) -> CaseProfileDTO:
        if not query.case_id.strip():
            raise ValidationError("case_id є обов'язковим", {"field": "case_id"})
        if not query.profile_version.strip():
            raise ValidationError("profile_version є обов'язковим", {"field": "profile_version"})
        with self._uow_factory(write=False) as uow:
            if not uow.case_profiles.case_exists(query.case_id):
                raise UnknownCaseError("Справу не знайдено", {"case_id": query.case_id})
            profile = uow.case_profiles.get(query.case_id, query.profile_version)
            available_versions = uow.case_profiles.versions(query.case_id)
        if profile is None:
            if available_versions:
                raise MissingProfileVersionError(
                    "Версію профілю не знайдено",
                    {
                        "case_id": query.case_id,
                        "profile_version": query.profile_version,
                    },
                )
            raise MissingProfileError(
                "Профіль справи не знайдено",
                {
                    "case_id": query.case_id,
                    "profile_version": query.profile_version,
                },
            )
        self._validate(profile.profile, query)
        return profile

    def _validate(self, profile: Mapping[str, object], query: GetCaseProfileQuery) -> None:
        try:
            schema = json.loads(self._schema_path.read_text(encoding="utf-8"))
            Draft202012Validator(schema).validate(profile)
        except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
            raise InvalidProfileError(
                "Профіль не відповідає case-profile schema",
                {
                    "case_id": query.case_id,
                    "profile_version": query.profile_version,
                },
            ) from exc
        if profile.get("profileVersion") != query.profile_version:
            raise InvalidProfileError(
                "profileVersion профілю не збігається із запитом",
                {
                    "expected": query.profile_version,
                    "actual": profile.get("profileVersion"),
                },
            )
        case = profile.get("case")
        if not isinstance(case, Mapping) or case.get("id") != query.case_id:
            raise InvalidProfileError(
                "case.id профілю не збігається із запитом",
                {"expected": query.case_id},
            )
