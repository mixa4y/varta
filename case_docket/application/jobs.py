"""Versioned C10 processing contracts and the application job service.

The module is deliberately infrastructure-free.  SQLite, managed paths and
subprocesses are outward adapters which implement the ports declared here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Mapping, Protocol

from .errors import ConflictError, NotFoundError, ValidationError
from .ports import Clock, IdProvider


CONTRACT_NAME = "varta.processor"
CONTRACT_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    NOT_AVAILABLE = "not_available"


STATUSES = frozenset(status.value for status in JobStatus)
TRANSITIONS: Mapping[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.NOT_AVAILABLE}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.INTERRUPTED,
            JobStatus.NOT_AVAILABLE,
        }
    ),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.INTERRUPTED: frozenset({JobStatus.QUEUED}),
    JobStatus.NOT_AVAILABLE: frozenset({JobStatus.QUEUED}),
}


class JobContractError(ValidationError):
    """A request/result does not satisfy the stable processor contract."""


class InvalidJobTransition(ConflictError):
    """The persisted state machine rejects the requested transition."""


@dataclass(frozen=True, slots=True)
class ProcessorInput:
    file_id: str
    sha256: str
    storage_reference: str

    def __post_init__(self) -> None:
        _non_empty(self.file_id, "file_id")
        _sha256(self.sha256, "input.sha256")
        _non_empty(self.storage_reference, "input.storage_reference")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "file_id": self.file_id,
            "sha256": self.sha256,
            "storage_reference": self.storage_reference,
        }

    @classmethod
    def from_dict(cls, value: object) -> ProcessorInput:
        item = _mapping(value, "input")
        return cls(
            file_id=_string(item, "file_id"),
            sha256=_string(item, "sha256"),
            storage_reference=_string(item, "storage_reference"),
        )


@dataclass(frozen=True, slots=True)
class ProcessorTool:
    name: str
    version: str
    model_name: str | None = None
    model_version: str | None = None
    model_sha256: str | None = None

    def __post_init__(self) -> None:
        _non_empty(self.name, "tool.name")
        _non_empty(self.version, "tool.version")
        if self.model_sha256 is not None:
            _sha256(self.model_sha256, "tool.model_sha256")
        if (self.model_name is None) != (self.model_version is None):
            raise JobContractError(
                "model_name і model_version мають задаватися разом",
                {"field": "tool.model"},
            )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "version": self.version,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_sha256": self.model_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> ProcessorTool:
        item = _mapping(value, "tool")
        return cls(
            name=_string(item, "name"),
            version=_string(item, "version"),
            model_name=_optional_string(item, "model_name"),
            model_version=_optional_string(item, "model_version"),
            model_sha256=_optional_string(item, "model_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    max_result_bytes: int = 1_000_000
    max_artifact_bytes: int = 10_000_000
    max_artifacts: int = 32
    max_stdout_chars: int = 4_000
    max_stderr_chars: int = 4_000

    def __post_init__(self) -> None:
        if not 0.05 <= self.timeout_seconds <= 86_400:
            raise JobContractError(
                "timeout_seconds має бути в межах 0.05..86400",
                {"field": "limits.timeout_seconds"},
            )
        for name, value, maximum in (
            ("max_attempts", self.max_attempts, 100),
            ("max_result_bytes", self.max_result_bytes, 100_000_000),
            ("max_artifact_bytes", self.max_artifact_bytes, 10_000_000_000),
            ("max_artifacts", self.max_artifacts, 10_000),
            ("max_stdout_chars", self.max_stdout_chars, 1_000_000),
            ("max_stderr_chars", self.max_stderr_chars, 1_000_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise JobContractError(
                    f"{name} має бути integer у межах 1..{maximum}",
                    {"field": f"limits.{name}"},
                )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "max_result_bytes": self.max_result_bytes,
            "max_artifact_bytes": self.max_artifact_bytes,
            "max_artifacts": self.max_artifacts,
            "max_stdout_chars": self.max_stdout_chars,
            "max_stderr_chars": self.max_stderr_chars,
        }

    @classmethod
    def from_dict(cls, value: object) -> ResourceLimits:
        item = _mapping(value, "limits")
        try:
            return cls(
                timeout_seconds=_number(item, "timeout_seconds"),
                max_attempts=_integer(item, "max_attempts"),
                max_result_bytes=_integer(item, "max_result_bytes"),
                max_artifact_bytes=_integer(item, "max_artifact_bytes"),
                max_artifacts=_integer(item, "max_artifacts"),
                max_stdout_chars=_integer(item, "max_stdout_chars"),
                max_stderr_chars=_integer(item, "max_stderr_chars"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise JobContractError("Некоректний limits manifest") from exc


@dataclass(frozen=True, slots=True)
class ProcessorRequest:
    processor: str
    inputs: tuple[ProcessorInput, ...]
    parameters: Mapping[str, JsonValue]
    tool: ProcessorTool
    limits: ResourceLimits = field(default_factory=ResourceLimits)

    def __post_init__(self) -> None:
        _non_empty(self.processor, "processor")
        if not self.inputs:
            raise JobContractError("Processor request потребує хоча б один input")
        if len({item.file_id for item in self.inputs}) != len(self.inputs):
            raise JobContractError("Processor request містить duplicate input file_id")
        _canonical_json(dict(self.parameters))

    @property
    def input_ids(self) -> tuple[str, ...]:
        return tuple(item.file_id for item in self.inputs)

    @property
    def input_hashes(self) -> tuple[str, ...]:
        return tuple(item.sha256 for item in self.inputs)

    @property
    def tool_version(self) -> str:
        return self.tool.version

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "contract": CONTRACT_NAME,
            "contract_version": CONTRACT_VERSION,
            "processor": self.processor,
            "inputs": [item.to_dict() for item in self.inputs],
            "parameters": dict(self.parameters),
            "tool": self.tool.to_dict(),
            "limits": self.limits.to_dict(),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> ProcessorRequest:
        item = _mapping(value, "request")
        _contract_header(item)
        raw_inputs = item.get("inputs")
        if not isinstance(raw_inputs, list):
            raise JobContractError("request.inputs має бути array")
        raw_parameters = item.get("parameters")
        if not isinstance(raw_parameters, dict):
            raise JobContractError("request.parameters має бути object")
        return cls(
            processor=_string(item, "processor"),
            inputs=tuple(ProcessorInput.from_dict(value) for value in raw_inputs),
            parameters=raw_parameters,
            tool=ProcessorTool.from_dict(item.get("tool")),
            limits=ResourceLimits.from_dict(item.get("limits")),
        )

    @classmethod
    def from_json(cls, value: str) -> ProcessorRequest:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise JobContractError("Processor request не є валідним JSON") from exc
        return cls.from_dict(decoded)


@dataclass(frozen=True, slots=True)
class ProcessorArtifact:
    artifact_id: str
    role: str
    relative_path: str
    sha256: str
    size_bytes: int
    media_type: str
    source_file_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _non_empty(self.artifact_id, "artifact.artifact_id")
        _non_empty(self.role, "artifact.role")
        _non_empty(self.relative_path, "artifact.relative_path")
        _sha256(self.sha256, "artifact.sha256")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise JobContractError("artifact.size_bytes має бути integer")
        if self.size_bytes < 0:
            raise JobContractError("artifact.size_bytes не може бути від’ємним")
        _non_empty(self.media_type, "artifact.media_type")
        if not self.source_file_ids:
            raise JobContractError("Artifact потребує source_file_ids")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "artifact_id": self.artifact_id,
            "role": self.role,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "source_file_ids": list(self.source_file_ids),
        }

    @classmethod
    def from_dict(cls, value: object) -> ProcessorArtifact:
        item = _mapping(value, "artifact")
        sources = item.get("source_file_ids")
        if not isinstance(sources, list) or not all(isinstance(value, str) for value in sources):
            raise JobContractError("artifact.source_file_ids має бути string array")
        return cls(
            artifact_id=_string(item, "artifact_id"),
            role=_string(item, "role"),
            relative_path=_string(item, "relative_path"),
            sha256=_string(item, "sha256"),
            size_bytes=_integer(item, "size_bytes"),
            media_type=_string(item, "media_type"),
            source_file_ids=tuple(sources),
        )


@dataclass(frozen=True, slots=True)
class ProcessorFinding:
    code: str
    message: str
    confidence: float | None
    source_file_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _non_empty(self.code, "finding.code")
        _non_empty(self.message, "finding.message")
        _confidence(self.confidence, "finding.confidence")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "message": self.message,
            "confidence": self.confidence,
            "source_file_ids": list(self.source_file_ids),
        }

    @classmethod
    def from_dict(cls, value: object) -> ProcessorFinding:
        item = _mapping(value, "finding")
        sources = item.get("source_file_ids")
        if not isinstance(sources, list) or not all(isinstance(value, str) for value in sources):
            raise JobContractError("finding.source_file_ids має бути string array")
        raw_confidence = item.get("confidence")
        confidence = _optional_number(raw_confidence, "finding.confidence")
        return cls(
            code=_string(item, "code"),
            message=_string(item, "message"),
            confidence=confidence,
            source_file_ids=tuple(sources),
        )


@dataclass(frozen=True, slots=True)
class ProcessorError:
    code: str
    message: str
    retryable: bool
    details: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _non_empty(self.code, "error.code")
        _non_empty(self.message, "error.message")
        if not isinstance(self.retryable, bool):
            raise JobContractError("error.retryable має бути boolean")
        _canonical_json(dict(self.details))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, value: object) -> ProcessorError:
        item = _mapping(value, "error")
        details = item.get("details", {})
        if not isinstance(details, dict):
            raise JobContractError("error.details має бути object")
        retryable = item.get("retryable")
        if not isinstance(retryable, bool):
            raise JobContractError("error.retryable має бути boolean")
        return cls(
            code=_string(item, "code"),
            message=_string(item, "message"),
            retryable=retryable,
            details=details,
        )


@dataclass(frozen=True, slots=True)
class ProcessorResult:
    processing_run_id: str
    status: JobStatus
    processor: str
    request_sha256: str
    input_ids: tuple[str, ...]
    input_hashes: tuple[str, ...]
    parameters_sha256: str
    tool: ProcessorTool
    started_at: datetime
    completed_at: datetime
    stdout_summary: str
    stderr_summary: str
    artifacts: tuple[ProcessorArtifact, ...]
    findings: tuple[ProcessorFinding, ...]
    confidence: float | None
    error: ProcessorError | None
    manifest_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.NOT_AVAILABLE,
        }:
            raise JobContractError("Result status має бути terminal processor status")
        _non_empty(self.processing_run_id, "result.processing_run_id")
        _non_empty(self.processor, "result.processor")
        _sha256(self.request_sha256, "result.request_sha256")
        _sha256(self.parameters_sha256, "result.parameters_sha256")
        for digest in self.input_hashes:
            _sha256(digest, "result.input_hashes")
        _aware(self.started_at, "result.started_at")
        _aware(self.completed_at, "result.completed_at")
        if self.completed_at < self.started_at:
            raise JobContractError("result.completed_at передує started_at")
        _confidence(self.confidence, "result.confidence")
        if self.status == JobStatus.SUCCEEDED and self.error is not None:
            raise JobContractError("Successful result не може містити error")
        if self.status != JobStatus.SUCCEEDED and self.error is None:
            raise JobContractError("Non-success result має містити error")
        if len({artifact.artifact_id for artifact in self.artifacts}) != len(self.artifacts):
            raise JobContractError("Result містить duplicate artifact_id")
        if self.manifest_sha256 is not None:
            _sha256(self.manifest_sha256, "result.manifest_sha256")

    def to_dict(self, *, include_digest: bool = True) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "contract": CONTRACT_NAME,
            "contract_version": CONTRACT_VERSION,
            "processing_run_id": self.processing_run_id,
            "status": self.status.value,
            "processor": self.processor,
            "request_sha256": self.request_sha256,
            "input_ids": list(self.input_ids),
            "input_hashes": list(self.input_hashes),
            "parameters_sha256": self.parameters_sha256,
            "tool": self.tool.to_dict(),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "stdout_summary": self.stdout_summary,
            "stderr_summary": self.stderr_summary,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "findings": [finding.to_dict() for finding in self.findings],
            "confidence": self.confidence,
            "error": self.error.to_dict() if self.error is not None else None,
        }
        if include_digest:
            payload["manifest_sha256"] = self.manifest_sha256
        return payload

    def seal(self) -> ProcessorResult:
        digest = hashlib.sha256(
            _canonical_json(self.to_dict(include_digest=False)).encode("utf-8")
        ).hexdigest()
        return ProcessorResult(
            processing_run_id=self.processing_run_id,
            status=self.status,
            processor=self.processor,
            request_sha256=self.request_sha256,
            input_ids=self.input_ids,
            input_hashes=self.input_hashes,
            parameters_sha256=self.parameters_sha256,
            tool=self.tool,
            started_at=self.started_at,
            completed_at=self.completed_at,
            stdout_summary=self.stdout_summary,
            stderr_summary=self.stderr_summary,
            artifacts=self.artifacts,
            findings=self.findings,
            confidence=self.confidence,
            error=self.error,
            manifest_sha256=digest,
        )

    def verify_digest(self) -> None:
        if self.manifest_sha256 is None:
            raise JobContractError("Result manifest не має SHA-256")
        expected = self.seal().manifest_sha256
        if self.manifest_sha256 != expected:
            raise JobContractError("Result manifest SHA-256 mismatch")

    def verify_request(self, request: ProcessorRequest, processing_run_id: str) -> None:
        failures: list[str] = []
        if self.processing_run_id != processing_run_id:
            failures.append("processing_run_id")
        if self.processor != request.processor:
            failures.append("processor")
        if self.request_sha256 != request.sha256:
            failures.append("request_sha256")
        if self.input_ids != request.input_ids:
            failures.append("input_ids")
        if self.input_hashes != request.input_hashes:
            failures.append("input_hashes")
        if self.parameters_sha256 != _json_sha256(dict(request.parameters)):
            failures.append("parameters_sha256")
        if self.tool != request.tool:
            failures.append("tool")
        if len(self.artifacts) > request.limits.max_artifacts:
            failures.append("max_artifacts")
        if len(self.stdout_summary) > request.limits.max_stdout_chars:
            failures.append("max_stdout_chars")
        if len(self.stderr_summary) > request.limits.max_stderr_chars:
            failures.append("max_stderr_chars")
        unknown_sources = {
            source
            for artifact in self.artifacts
            for source in artifact.source_file_ids
            if source not in request.input_ids
        }
        unknown_sources.update(
            source
            for finding in self.findings
            for source in finding.source_file_ids
            if source not in request.input_ids
        )
        if unknown_sources:
            failures.append("source_file_ids")
        if failures:
            raise JobContractError(
                "Result manifest не відповідає request",
                {"fields": failures},
            )

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> ProcessorResult:
        item = _mapping(value, "result")
        _contract_header(item)
        raw_artifacts = item.get("artifacts")
        raw_findings = item.get("findings")
        if not isinstance(raw_artifacts, list) or not isinstance(raw_findings, list):
            raise JobContractError("Result artifacts/findings мають бути arrays")
        raw_input_ids = item.get("input_ids")
        raw_input_hashes = item.get("input_hashes")
        if not isinstance(raw_input_ids, list) or not all(
            isinstance(value, str) for value in raw_input_ids
        ):
            raise JobContractError("result.input_ids має бути string array")
        if not isinstance(raw_input_hashes, list) or not all(
            isinstance(value, str) for value in raw_input_hashes
        ):
            raise JobContractError("result.input_hashes має бути string array")
        raw_error = item.get("error")
        raw_confidence = item.get("confidence")
        try:
            status = JobStatus(_string(item, "status"))
            started_at = datetime.fromisoformat(_string(item, "started_at"))
            completed_at = datetime.fromisoformat(_string(item, "completed_at"))
            confidence = _optional_number(raw_confidence, "result.confidence")
        except ValueError as exc:
            raise JobContractError("Result status/timestamp/confidence некоректний") from exc
        return cls(
            processing_run_id=_string(item, "processing_run_id"),
            status=status,
            processor=_string(item, "processor"),
            request_sha256=_string(item, "request_sha256"),
            input_ids=tuple(raw_input_ids),
            input_hashes=tuple(raw_input_hashes),
            parameters_sha256=_string(item, "parameters_sha256"),
            tool=ProcessorTool.from_dict(item.get("tool")),
            started_at=started_at,
            completed_at=completed_at,
            stdout_summary=_string_allow_empty(item, "stdout_summary"),
            stderr_summary=_string_allow_empty(item, "stderr_summary"),
            artifacts=tuple(ProcessorArtifact.from_dict(value) for value in raw_artifacts),
            findings=tuple(ProcessorFinding.from_dict(value) for value in raw_findings),
            confidence=confidence,
            error=None if raw_error is None else ProcessorError.from_dict(raw_error),
            manifest_sha256=_optional_string(item, "manifest_sha256"),
        )

    @classmethod
    def from_json(cls, value: str) -> ProcessorResult:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise JobContractError("Processor result не є валідним JSON") from exc
        return cls.from_dict(decoded)


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    processing_run_id: str
    idempotency_key: str
    status: JobStatus
    attempt: int
    request: ProcessorRequest
    result: ProcessorResult | None
    error: ProcessorError | None
    lease_token: str | None
    lease_expires_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class JobClaim:
    job: Job
    lease_token: str


@dataclass(frozen=True, slots=True)
class JobEvent:
    sequence: int
    job_id: str
    from_status: JobStatus | None
    to_status: JobStatus
    occurred_at: datetime
    detail: Mapping[str, JsonValue]


class JobStorePort(Protocol):
    def create(
        self,
        *,
        job_id: str,
        request: ProcessorRequest,
        idempotency_key: str,
        occurred_at: datetime,
    ) -> Job: ...

    def get(self, job_id: str) -> Job | None: ...

    def claim(
        self,
        *,
        job_id: str | None,
        lease_token: str,
        worker_id: str,
        occurred_at: datetime,
        lease_expires_at: datetime,
    ) -> JobClaim | None: ...

    def heartbeat(
        self,
        job_id: str,
        lease_token: str,
        *,
        occurred_at: datetime,
        lease_expires_at: datetime,
    ) -> None: ...

    def recover_expired(self, *, occurred_at: datetime) -> int: ...

    def request_cancel(self, job_id: str, *, occurred_at: datetime) -> Job: ...

    def cancellation_requested(self, job_id: str, lease_token: str) -> bool: ...

    def retry(self, job_id: str, *, occurred_at: datetime) -> Job: ...

    def finish(
        self,
        job_id: str,
        lease_token: str,
        *,
        status: JobStatus,
        result: ProcessorResult | None,
        error: ProcessorError | None,
        occurred_at: datetime,
    ) -> Job: ...

    def events(self, job_id: str) -> tuple[JobEvent, ...]: ...


class JobService:
    """Authoritative application lifecycle; all persistence is delegated to a port."""

    def __init__(self, store: JobStorePort, ids: IdProvider, clock: Clock):
        self._store = store
        self._ids = ids
        self._clock = clock

    def submit(self, request: ProcessorRequest, idempotency_key: str) -> str:
        _non_empty(idempotency_key, "idempotency_key")
        job = self._store.create(
            job_id=self._ids.new_id(),
            request=request,
            idempotency_key=idempotency_key,
            occurred_at=self._clock.now(),
        )
        return job.id

    def get(self, job_id: str) -> Job | None:
        return self._store.get(job_id)

    def require(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job is None:
            raise NotFoundError("Processing job не знайдено", {"job_id": job_id})
        return job

    def claim(
        self,
        job_id: str | None = None,
        *,
        lease_seconds: float = 30.0,
        worker_id: str = "local-supervisor",
    ) -> JobClaim | None:
        if lease_seconds <= 0:
            raise JobContractError("lease_seconds має бути додатним")
        now = self._clock.now()
        return self._store.claim(
            job_id=job_id,
            lease_token=self._ids.new_id(),
            worker_id=worker_id,
            occurred_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )

    def heartbeat(self, claim: JobClaim, *, lease_seconds: float) -> None:
        if lease_seconds <= 0:
            raise JobContractError("lease_seconds має бути додатним")
        now = self._clock.now()
        self._store.heartbeat(
            claim.job.id,
            claim.lease_token,
            occurred_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )

    def recover_expired(self) -> int:
        return self._store.recover_expired(occurred_at=self._clock.now())

    def cancel(self, job_id: str) -> Job:
        return self._store.request_cancel(job_id, occurred_at=self._clock.now())

    def cancellation_requested(self, claim: JobClaim) -> bool:
        return self._store.cancellation_requested(claim.job.id, claim.lease_token)

    def retry(self, job_id: str) -> Job:
        return self._store.retry(job_id, occurred_at=self._clock.now())

    def succeed(self, claim: JobClaim, result: ProcessorResult) -> Job:
        result.verify_digest()
        result.verify_request(claim.job.request, claim.job.processing_run_id)
        if result.status != JobStatus.SUCCEEDED:
            raise JobContractError("succeed потребує result.status=succeeded")
        return self._store.finish(
            claim.job.id,
            claim.lease_token,
            status=JobStatus.SUCCEEDED,
            result=result,
            error=None,
            occurred_at=self._clock.now(),
        )

    def fail(
        self,
        claim: JobClaim,
        error: ProcessorError,
        *,
        result: ProcessorResult | None = None,
    ) -> Job:
        if result is not None:
            result.verify_digest()
            result.verify_request(claim.job.request, claim.job.processing_run_id)
            if result.status != JobStatus.FAILED or result.error != error:
                raise JobContractError("fail result status/error не відповідає command")
        return self._store.finish(
            claim.job.id,
            claim.lease_token,
            status=JobStatus.FAILED,
            result=result,
            error=error,
            occurred_at=self._clock.now(),
        )

    def interrupt(self, claim: JobClaim, error: ProcessorError) -> Job:
        return self._store.finish(
            claim.job.id,
            claim.lease_token,
            status=JobStatus.INTERRUPTED,
            result=None,
            error=error,
            occurred_at=self._clock.now(),
        )

    def finish_cancelled(self, claim: JobClaim, error: ProcessorError) -> Job:
        return self._store.finish(
            claim.job.id,
            claim.lease_token,
            status=JobStatus.CANCELLED,
            result=None,
            error=error,
            occurred_at=self._clock.now(),
        )

    def mark_not_available(self, claim: JobClaim, error: ProcessorError) -> Job:
        return self._store.finish(
            claim.job.id,
            claim.lease_token,
            status=JobStatus.NOT_AVAILABLE,
            result=None,
            error=error,
            occurred_at=self._clock.now(),
        )

    def events(self, job_id: str) -> tuple[JobEvent, ...]:
        self.require(job_id)
        return self._store.events(job_id)


def synthetic_reference_processor(
    request: ProcessorRequest,
    processing_run_id: str,
    *,
    started_at: datetime,
    completed_at: datetime,
    artifacts: tuple[ProcessorArtifact, ...] = (),
    findings: tuple[ProcessorFinding, ...] = (),
    confidence: float | None = 1.0,
) -> ProcessorResult:
    """Deterministic-contract synthetic result; no OCR/КЕП/STT algorithm."""

    return ProcessorResult(
        processing_run_id=processing_run_id,
        status=JobStatus.SUCCEEDED,
        processor=request.processor,
        request_sha256=request.sha256,
        input_ids=request.input_ids,
        input_hashes=request.input_hashes,
        parameters_sha256=_json_sha256(dict(request.parameters)),
        tool=request.tool,
        started_at=started_at,
        completed_at=completed_at,
        stdout_summary="",
        stderr_summary="",
        artifacts=artifacts,
        findings=findings,
        confidence=confidence,
        error=None,
    ).seal()


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise JobContractError("Manifest містить не-JSON value") from exc


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise JobContractError(f"{field_name} має бути JSON object")
    return value


def _string(item: Mapping[str, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise JobContractError(f"{key} має бути non-empty string")
    return value


def _string_allow_empty(item: Mapping[str, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str):
        raise JobContractError(f"{key} має бути string")
    return value


def _optional_string(item: Mapping[str, object], key: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise JobContractError(f"{key} має бути non-empty string або null")
    return value


def _integer(item: Mapping[str, object], key: str) -> int:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise JobContractError(f"{key} має бути integer")
    return value


def _number(item: Mapping[str, object], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobContractError(f"{key} має бути number")
    return float(value)


def _optional_number(
    value: object,
    field_name: str,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobContractError(f"{field_name} має бути number")
    return float(value)


def _non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise JobContractError(f"{field_name} має бути non-empty string")


def _sha256(value: str, field_name: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise JobContractError(f"{field_name} має бути lowercase SHA-256")


def _confidence(value: float | None, field_name: str) -> None:
    if value is not None and not 0.0 <= value <= 1.0:
        raise JobContractError(f"{field_name} має бути в межах 0..1 або null")


def _aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise JobContractError(f"{field_name} має містити timezone")


def _contract_header(item: Mapping[str, object]) -> None:
    if item.get("contract") != CONTRACT_NAME or item.get("contract_version") != CONTRACT_VERSION:
        raise JobContractError("Непідтримувана processor contract version")
