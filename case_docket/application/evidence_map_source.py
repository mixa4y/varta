from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, Protocol, TypeVar

from .evidence_ports import (
    ClaimRecord,
    EvidenceActorRecord,
    EvidenceDocumentRecord,
    EvidenceEventRecord,
    EvidenceRelationRecord,
    FindingRecord,
    ReviewDecisionRecord,
    SourceReferenceRecord,
)
from .ports import ManagedFileRecord
from .profile import GetCaseProfileQuery
from .profile_ports import CaseProfileDTO
from .workspace_ports import WorkspaceCaseRecord, WorkspaceProceedingRecord


type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

_EXPORT_PROFILES = frozenset({"full_local", "redacted", "metadata_only"})
_TIMESTAMP_FIELDS = frozenset(
    {
        "activated_at",
        "created_at",
        "decided_at",
        "first_observed_at",
        "last_observed_at",
        "updated_at",
    }
)
_REQUIRED_PROVIDERS = (
    "get_case",
    "get_profile",
    "list_proceedings",
    "list_files",
    "list_actors",
    "list_documents",
    "list_events",
    "list_source_references",
    "list_claims",
    "list_relations",
    "list_reviews",
    "list_findings",
    "list_exclusions",
)

SourceRecord = TypeVar("SourceRecord")
SourceRecordCovariant = TypeVar("SourceRecordCovariant", covariant=True)


class EvidenceMapSourceError(RuntimeError):
    """The authoritative case-scoped source is incomplete or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class EvidenceMapSourceQuery:
    case_id: str
    profile_version: str
    export_profile: str
    page_size: int = 100


@dataclass(frozen=True, slots=True)
class CaseScopedSourceItem(Generic[SourceRecordCovariant]):
    case_id: str
    record: SourceRecordCovariant


@dataclass(frozen=True, slots=True)
class EvidenceMapExclusionDTO:
    entity_type: str
    entity_id: str
    reason_code: str
    reason: str
    source_reference_ids: tuple[str, ...]
    review_status: str


@dataclass(frozen=True, slots=True)
class EvidenceMapEvidenceDTO:
    actors: tuple[CaseScopedSourceItem[EvidenceActorRecord], ...]
    documents: tuple[CaseScopedSourceItem[EvidenceDocumentRecord], ...]
    events: tuple[CaseScopedSourceItem[EvidenceEventRecord], ...]
    source_references: tuple[CaseScopedSourceItem[SourceReferenceRecord], ...]
    claims: tuple[CaseScopedSourceItem[ClaimRecord], ...]
    relations: tuple[CaseScopedSourceItem[EvidenceRelationRecord], ...]


@dataclass(frozen=True, slots=True)
class EvidenceMapSourceDTO:
    case_id: str
    profile_version: str
    export_profile: str
    case: WorkspaceCaseRecord
    profile: CaseProfileDTO
    proceedings: tuple[CaseScopedSourceItem[WorkspaceProceedingRecord], ...]
    files: tuple[CaseScopedSourceItem[ManagedFileRecord], ...]
    evidence: EvidenceMapEvidenceDTO
    reviews: tuple[CaseScopedSourceItem[ReviewDecisionRecord], ...]
    findings: tuple[CaseScopedSourceItem[FindingRecord], ...]
    exclusions: tuple[CaseScopedSourceItem[EvidenceMapExclusionDTO], ...]
    source_revision: str
    data_cutoff: str


class PagedSourceProvider(Protocol[SourceRecordCovariant]):
    def __call__(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[SourceRecordCovariant], ...]: ...


class EvidenceMapSourcePorts(Protocol):
    """Every provider is required; an empty result must come from an explicit provider call."""

    def get_case(self, case_id: str) -> WorkspaceCaseRecord | None: ...

    def get_profile(self, query: GetCaseProfileQuery) -> CaseProfileDTO: ...

    def list_proceedings(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[WorkspaceProceedingRecord], ...]: ...

    def list_files(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[ManagedFileRecord], ...]: ...

    def list_actors(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[EvidenceActorRecord], ...]: ...

    def list_documents(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[EvidenceDocumentRecord], ...]: ...

    def list_events(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[EvidenceEventRecord], ...]: ...

    def list_source_references(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[SourceReferenceRecord], ...]: ...

    def list_claims(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[ClaimRecord], ...]: ...

    def list_relations(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[EvidenceRelationRecord], ...]: ...

    def list_reviews(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[ReviewDecisionRecord], ...]: ...

    def list_findings(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[FindingRecord], ...]: ...

    def list_exclusions(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[CaseScopedSourceItem[EvidenceMapExclusionDTO], ...]: ...


class EvidenceMapSourceQueryService:
    """Build one deterministic source DTO without generating map-data.json."""

    def __init__(self, ports: EvidenceMapSourcePorts):
        self._ports = ports

    def query(self, request: EvidenceMapSourceQuery) -> EvidenceMapSourceDTO:
        case_id = self._required_text(request.case_id, "case_id")
        profile_version = self._required_text(request.profile_version, "profile_version")
        export_profile = self._required_text(request.export_profile, "export_profile")
        if export_profile not in _EXPORT_PROFILES:
            raise EvidenceMapSourceError("Unsupported export_profile")
        if request.page_size < 1 or request.page_size > 1000:
            raise EvidenceMapSourceError("page_size must be in range 1..1000")
        self._require_providers()

        case = self._ports.get_case(case_id)
        if case is None:
            raise EvidenceMapSourceError("Required case provider returned no case")
        if case.case_id != case_id:
            raise EvidenceMapSourceError("case provider returned another case")

        profile = self._ports.get_profile(GetCaseProfileQuery(case_id, profile_version))
        if profile.case_id != case_id:
            raise EvidenceMapSourceError("profile provider returned another case")
        if profile.profile_version != profile_version:
            raise EvidenceMapSourceError("profile provider returned another version")

        proceedings = self._all_pages(
            self._ports.list_proceedings,
            case_id,
            request.page_size,
            "proceedings",
        )
        files = self._all_pages(self._ports.list_files, case_id, request.page_size, "files")
        evidence = EvidenceMapEvidenceDTO(
            actors=self._all_pages(self._ports.list_actors, case_id, request.page_size, "actors"),
            documents=self._all_pages(
                self._ports.list_documents, case_id, request.page_size, "documents"
            ),
            events=self._all_pages(self._ports.list_events, case_id, request.page_size, "events"),
            source_references=self._all_pages(
                self._ports.list_source_references,
                case_id,
                request.page_size,
                "source_references",
            ),
            claims=self._all_pages(self._ports.list_claims, case_id, request.page_size, "claims"),
            relations=self._all_pages(
                self._ports.list_relations, case_id, request.page_size, "relations"
            ),
        )
        reviews = self._all_pages(self._ports.list_reviews, case_id, request.page_size, "reviews")
        findings = self._all_pages(
            self._ports.list_findings, case_id, request.page_size, "findings"
        )
        exclusions = self._all_pages(
            self._ports.list_exclusions, case_id, request.page_size, "exclusions"
        )

        source_payload = {
            "case": case,
            "profile": profile,
            "proceedings": proceedings,
            "files": files,
            "evidence": evidence,
            "reviews": reviews,
            "findings": findings,
            "exclusions": exclusions,
        }
        encoded = self._canonical_json(source_payload)
        source_revision = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        data_cutoff = self._data_cutoff(source_payload)
        return EvidenceMapSourceDTO(
            case_id=case_id,
            profile_version=profile_version,
            export_profile=export_profile,
            case=case,
            profile=profile,
            proceedings=proceedings,
            files=files,
            evidence=evidence,
            reviews=reviews,
            findings=findings,
            exclusions=exclusions,
            source_revision=source_revision,
            data_cutoff=data_cutoff,
        )

    def _require_providers(self) -> None:
        for provider_name in _REQUIRED_PROVIDERS:
            provider = getattr(self._ports, provider_name, None)
            if not callable(provider):
                raise EvidenceMapSourceError(
                    f"Required provider is missing or not callable: {provider_name}"
                )

    @classmethod
    def _all_pages(
        cls,
        provider: PagedSourceProvider[SourceRecord],
        case_id: str,
        page_size: int,
        component: str,
    ) -> tuple[CaseScopedSourceItem[SourceRecord], ...]:
        if not callable(provider):
            raise EvidenceMapSourceError(
                f"Required provider is missing or not callable: {component}"
            )
        result: list[CaseScopedSourceItem[SourceRecord]] = []
        seen_full_pages: set[str] = set()
        offset = 0
        while True:
            page = provider(case_id, limit=page_size, offset=offset)
            if not isinstance(page, tuple):
                raise EvidenceMapSourceError(f"{component} provider must return a tuple page")
            if len(page) > page_size:
                raise EvidenceMapSourceError(f"{component} provider exceeded requested page size")
            cls._check_scope(page, case_id, component)
            result.extend(page)
            if len(page) < page_size:
                break
            page_signature = hashlib.sha256(cls._canonical_json(page).encode("utf-8")).hexdigest()
            if page_signature in seen_full_pages:
                raise EvidenceMapSourceError(f"{component} pagination did not advance")
            seen_full_pages.add(page_signature)
            offset += page_size
        return tuple(sorted(result, key=cls._canonical_json))

    @staticmethod
    def _check_scope(
        values: tuple[CaseScopedSourceItem[SourceRecord], ...],
        case_id: str,
        component: str,
    ) -> None:
        for value in values:
            if value.case_id != case_id:
                raise EvidenceMapSourceError(f"{component} provider returned another case")

    @staticmethod
    def _required_text(value: str, field_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise EvidenceMapSourceError(f"{field_name} is required")
        return normalized

    @classmethod
    def _canonical_json(cls, value: object) -> str:
        return json.dumps(
            cls._canonical_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _canonical_value(cls, value: object) -> JsonValue:
        if value is None or isinstance(value, (bool, int, str)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise EvidenceMapSourceError("Source contains a non-finite number")
            return value
        if isinstance(value, datetime):
            return cls._utc_timestamp(value).isoformat()
        dataclass_fields = getattr(value, "__dataclass_fields__", None)
        if isinstance(dataclass_fields, Mapping):
            return {
                str(name): cls._canonical_value(getattr(value, str(name)))
                for name in sorted(dataclass_fields, key=str)
            }
        if isinstance(value, Mapping):
            result: dict[str, JsonValue] = {}
            for key in sorted(value, key=str):
                if not isinstance(key, str):
                    raise EvidenceMapSourceError("Source mapping keys must be strings")
                result[key] = cls._canonical_value(value[key])
            return result
        if isinstance(value, (tuple, list)):
            return [cls._canonical_value(item) for item in value]
        raise EvidenceMapSourceError(f"Unsupported source value type: {type(value).__name__}")

    @classmethod
    def _data_cutoff(cls, value: object) -> str:
        timestamps: list[datetime] = []
        cls._collect_timestamps(value, timestamps)
        if not timestamps:
            raise EvidenceMapSourceError("Source contains no persisted timestamps")
        return max(timestamps).isoformat()

    @classmethod
    def _collect_timestamps(cls, value: object, result: list[datetime]) -> None:
        dataclass_fields = getattr(value, "__dataclass_fields__", None)
        if isinstance(dataclass_fields, Mapping):
            for name in dataclass_fields:
                field_name = str(name)
                field_value = getattr(value, field_name)
                if field_name in _TIMESTAMP_FIELDS and field_value is not None:
                    result.append(cls._parse_timestamp(field_value, field_name))
                cls._collect_timestamps(field_value, result)
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                field_name = str(key)
                if field_name in _TIMESTAMP_FIELDS and item is not None:
                    result.append(cls._parse_timestamp(item, field_name))
                cls._collect_timestamps(item, result)
            return
        if isinstance(value, (tuple, list)):
            for item in value:
                cls._collect_timestamps(item, result)

    @classmethod
    def _parse_timestamp(cls, value: object, field_name: str) -> datetime:
        if isinstance(value, datetime):
            return cls._utc_timestamp(value)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise EvidenceMapSourceError(
                    f"Persisted {field_name} is not an ISO timestamp"
                ) from exc
            return cls._utc_timestamp(parsed)
        raise EvidenceMapSourceError(f"Persisted {field_name} has invalid type")

    @staticmethod
    def _utc_timestamp(value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
