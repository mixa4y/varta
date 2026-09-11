"""SQLite adapter for the C10 durable processing job port."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from case_docket.application.errors import ConflictError, NotFoundError, ValidationError
from case_docket.application.jobs import (
    Job,
    JobClaim,
    JobEvent,
    JobStatus,
    ProcessorError,
    ProcessorRequest,
    ProcessorResult,
    TRANSITIONS,
)

from .migrations import MigrationRunner
from .sqlite_connection import SQLiteConnectionFactory, SQLiteConnectionPolicy


_LEGACY_RUN_STATUS = {
    JobStatus.QUEUED: "queued",
    JobStatus.RUNNING: "running",
    JobStatus.SUCCEEDED: "succeeded",
    JobStatus.FAILED: "failed",
    JobStatus.CANCELLED: "failed",
    JobStatus.INTERRUPTED: "partial",
    JobStatus.NOT_AVAILABLE: "not_available",
}


class SQLiteJobStore:
    """One transaction per lifecycle command, with processing_runs as provenance."""

    def __init__(
        self,
        database_path: Path,
        *,
        connection_policy: SQLiteConnectionPolicy | None = None,
        migrations_path: Path | None = None,
    ):
        self.database_path = database_path
        self.connection_policy = connection_policy or SQLiteConnectionPolicy()
        self.migrations_path = migrations_path
        self._factory = SQLiteConnectionFactory(database_path, self.connection_policy)
        connection = self._factory.connect()
        try:
            MigrationRunner(connection, migrations_path).migrate()
        finally:
            connection.close()

    def create(
        self,
        *,
        job_id: str,
        request: ProcessorRequest,
        idempotency_key: str,
        occurred_at: datetime,
    ) -> Job:
        request_json = request.to_json()
        timestamp = occurred_at.isoformat()
        connection = self._factory.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT id, request_json FROM processing_jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["request_json"]) != request_json:
                    raise ConflictError(
                        "idempotency_key уже використано для іншого request",
                        {"resource": "processing_job"},
                    )
                connection.commit()
                job = self.get(str(existing["id"]))
                assert job is not None
                return job

            self._verify_inputs(connection, request)
            connection.execute(
                """
                INSERT INTO processing_runs(
                    id, run_type, tool_name, tool_version, parameters_json,
                    started_at, completed_at, status, error_details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, 'queued', NULL, ?)
                """,
                (
                    job_id,
                    request.processor,
                    request.tool.name,
                    request.tool.version,
                    self._json(
                        {
                            "contract": "varta.processor",
                            "contract_version": 1,
                            "request_sha256": request.sha256,
                            "parameters": dict(request.parameters),
                            "model_name": request.tool.model_name,
                            "model_version": request.tool.model_version,
                            "model_sha256": request.tool.model_sha256,
                            "limits": request.limits.to_dict(),
                        }
                    ),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO processing_jobs(
                    id, processing_run_id, idempotency_key, processor, request_json, result_json,
                    status, attempt, lease_token, lease_expires_at,
                    timeout_seconds, created_at, started_at, completed_at, error_json
                ) VALUES (?, ?, ?, ?, ?, NULL, 'queued', 0, NULL, NULL, ?, ?, NULL, NULL, NULL)
                """,
                (
                    job_id,
                    job_id,
                    idempotency_key,
                    request.processor,
                    request_json,
                    max(1, int(request.limits.timeout_seconds + 0.999)),
                    timestamp,
                ),
            )
            for item in request.inputs:
                connection.execute(
                    """
                    INSERT INTO processing_run_files(processing_run_id, file_id, role)
                    VALUES (?, ?, 'input')
                    """,
                    (job_id, item.file_id),
                )
            self._event(connection, job_id, None, JobStatus.QUEUED, occurred_at, {})
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        job = self.get(job_id)
        assert job is not None
        return job

    def get(self, job_id: str) -> Job | None:
        connection = self._factory.connect()
        try:
            row = connection.execute(
                """
                SELECT id, processing_run_id, idempotency_key, status, attempt, request_json,
                       result_json, error_json, lease_token, lease_expires_at,
                       created_at, started_at, completed_at
                FROM processing_jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            return None if row is None else self._job(row)
        finally:
            connection.close()

    def claim(
        self,
        *,
        job_id: str | None,
        lease_token: str,
        worker_id: str,
        occurred_at: datetime,
        lease_expires_at: datetime,
    ) -> JobClaim | None:
        connection = self._factory.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if job_id is None:
                row = connection.execute(
                    """
                    SELECT id, request_json, attempt FROM processing_jobs
                    WHERE status = 'queued' ORDER BY created_at, id LIMIT 1
                    """
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT id, request_json, attempt FROM processing_jobs
                    WHERE id = ? AND status = 'queued'
                    """,
                    (job_id,),
                ).fetchone()
            if row is None:
                connection.commit()
                if job_id is not None and self.get(job_id) is None:
                    raise NotFoundError("Processing job не знайдено", {"job_id": job_id})
                return None
            request = ProcessorRequest.from_json(str(row["request_json"]))
            if int(row["attempt"]) >= request.limits.max_attempts:
                raise ConflictError(
                    "Processing job вичерпав max_attempts",
                    {"job_id": str(row["id"])},
                )
            selected_id = str(row["id"])
            cursor = connection.execute(
                """
                UPDATE processing_jobs
                SET status = 'running', attempt = attempt + 1,
                    lease_token = ?, lease_expires_at = ?, started_at = ?,
                    completed_at = NULL, result_json = NULL, error_json = NULL
                WHERE id = ? AND status = 'queued'
                """,
                (
                    lease_token,
                    lease_expires_at.isoformat(),
                    occurred_at.isoformat(),
                    selected_id,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            connection.execute(
                """
                UPDATE processing_runs
                SET status = 'running', started_at = ?, completed_at = NULL,
                    error_details = NULL
                WHERE id = ?
                """,
                (occurred_at.isoformat(), selected_id),
            )
            self._event(
                connection,
                selected_id,
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                occurred_at,
                {"worker_id": worker_id, "lease_expires_at": lease_expires_at.isoformat()},
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        job = self.get(selected_id)
        assert job is not None
        return JobClaim(job=job, lease_token=lease_token)

    def heartbeat(
        self,
        job_id: str,
        lease_token: str,
        *,
        occurred_at: datetime,
        lease_expires_at: datetime,
    ) -> None:
        del occurred_at
        connection = self._factory.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE processing_jobs SET lease_expires_at = ?
                WHERE id = ? AND status = 'running' AND lease_token = ?
                """,
                (lease_expires_at.isoformat(), job_id, lease_token),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Lease більше не належить worker", {"job_id": job_id})
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def recover_expired(self, *, occurred_at: datetime) -> int:
        connection = self._factory.connect()
        recovered = 0
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT id FROM processing_jobs
                WHERE status = 'running' AND lease_expires_at < ?
                ORDER BY id
                """,
                (occurred_at.isoformat(),),
            ).fetchall()
            for row in rows:
                job_id = str(row["id"])
                error = ProcessorError(
                    "worker_lease_expired",
                    "Worker lease expired before authoritative finalize",
                    True,
                )
                connection.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'interrupted', lease_token = NULL,
                        lease_expires_at = NULL, completed_at = ?, error_json = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (occurred_at.isoformat(), self._json(error.to_dict()), job_id),
                )
                connection.execute(
                    """
                    UPDATE processing_runs
                    SET status = 'partial', completed_at = ?, error_details = ?
                    WHERE id = ?
                    """,
                    (occurred_at.isoformat(), self._json(error.to_dict()), job_id),
                )
                self._event(
                    connection,
                    job_id,
                    JobStatus.RUNNING,
                    JobStatus.INTERRUPTED,
                    occurred_at,
                    {"error": error.to_dict()},
                )
                recovered += 1
            connection.commit()
            return recovered
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def request_cancel(self, job_id: str, *, occurred_at: datetime) -> Job:
        connection = self._factory.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM processing_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("Processing job не знайдено", {"job_id": job_id})
            status = JobStatus(str(row["status"]))
            if status == JobStatus.QUEUED:
                error = ProcessorError("cancelled", "Job cancelled before worker claim", False)
                self._finish_rows(
                    connection,
                    job_id,
                    status,
                    JobStatus.CANCELLED,
                    None,
                    error,
                    occurred_at,
                )
            elif status == JobStatus.RUNNING:
                existing = connection.execute(
                    """
                    SELECT 1 FROM processing_job_events
                    WHERE job_id = ? AND to_status = 'running'
                      AND json_extract(detail_json, '$.kind') = 'cancel_requested'
                    """,
                    (job_id,),
                ).fetchone()
                if existing is None:
                    self._event(
                        connection,
                        job_id,
                        JobStatus.RUNNING,
                        JobStatus.RUNNING,
                        occurred_at,
                        {"kind": "cancel_requested"},
                    )
            elif status != JobStatus.CANCELLED:
                raise ConflictError(
                    f"Job у status={status.value} не можна cancel",
                    {"job_id": job_id},
                )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        job = self.get(job_id)
        assert job is not None
        return job

    def cancellation_requested(self, job_id: str, lease_token: str) -> bool:
        connection = self._factory.connect()
        try:
            row = connection.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM processing_job_events
                    WHERE job_id = ? AND to_status = 'running'
                      AND json_extract(detail_json, '$.kind') = 'cancel_requested'
                ) AS requested
                FROM processing_jobs
                WHERE id = ? AND status = 'running' AND lease_token = ?
                """,
                (job_id, job_id, lease_token),
            ).fetchone()
            return bool(row is not None and row["requested"])
        finally:
            connection.close()

    def retry(self, job_id: str, *, occurred_at: datetime) -> Job:
        connection = self._factory.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, attempt, request_json, error_json
                FROM processing_jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("Processing job не знайдено", {"job_id": job_id})
            status = JobStatus(str(row["status"]))
            if JobStatus.QUEUED not in TRANSITIONS[status]:
                raise ConflictError(
                    f"Job у status={status.value} не можна retry",
                    {"job_id": job_id},
                )
            request = ProcessorRequest.from_json(str(row["request_json"]))
            if int(row["attempt"]) >= request.limits.max_attempts:
                raise ConflictError("Job вичерпав max_attempts", {"job_id": job_id})
            raw_error = row["error_json"]
            if raw_error is None:
                raise ConflictError("Job не має retryable error", {"job_id": job_id})
            error = ProcessorError.from_dict(json.loads(str(raw_error)))
            if not error.retryable:
                raise ConflictError("Job error позначено non-retryable", {"job_id": job_id})
            connection.execute(
                """
                UPDATE processing_jobs
                SET status = 'queued', result_json = NULL, error_json = NULL,
                    lease_token = NULL, lease_expires_at = NULL,
                    started_at = NULL, completed_at = NULL
                WHERE id = ?
                """,
                (job_id,),
            )
            connection.execute(
                """
                UPDATE processing_runs
                SET status = 'queued', completed_at = NULL, error_details = NULL
                WHERE id = ?
                """,
                (job_id,),
            )
            self._event(connection, job_id, status, JobStatus.QUEUED, occurred_at, {})
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        job = self.get(job_id)
        assert job is not None
        return job

    def finish(
        self,
        job_id: str,
        lease_token: str,
        *,
        status: JobStatus,
        result: ProcessorResult | None,
        error: ProcessorError | None,
        occurred_at: datetime,
    ) -> Job:
        if status not in TRANSITIONS[JobStatus.RUNNING]:
            raise ValidationError("Unsupported terminal status", {"status": status.value})
        connection = self._factory.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM processing_jobs WHERE id = ? AND lease_token = ?",
                (job_id, lease_token),
            ).fetchone()
            if row is None or JobStatus(str(row["status"])) != JobStatus.RUNNING:
                raise ConflictError("Invalid або expired worker lease", {"job_id": job_id})
            self._finish_rows(
                connection,
                job_id,
                JobStatus.RUNNING,
                status,
                result,
                error,
                occurred_at,
            )
            if status == JobStatus.SUCCEEDED and result is not None:
                self._register_artifacts(connection, job_id, result, occurred_at)
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        job = self.get(job_id)
        assert job is not None
        return job

    def events(self, job_id: str) -> tuple[JobEvent, ...]:
        connection = self._factory.connect()
        try:
            rows = connection.execute(
                """
                SELECT sequence, job_id, from_status, to_status, occurred_at, detail_json
                FROM processing_job_events WHERE job_id = ? ORDER BY sequence
                """,
                (job_id,),
            ).fetchall()
            return tuple(self._job_event(row) for row in rows)
        finally:
            connection.close()

    def processing_run(self, job_id: str) -> Mapping[str, Any] | None:
        """Read-back helper used by integration/API adapters."""

        connection = self._factory.connect()
        try:
            row = connection.execute(
                """
                SELECT r.*, j.status AS job_status, j.request_json, j.result_json,
                       j.error_json, j.attempt
                FROM processing_runs AS r
                JOIN processing_jobs AS j ON j.id = r.id
                WHERE r.id = ?
                """,
                (job_id,),
            ).fetchone()
            return None if row is None else dict(row)
        finally:
            connection.close()

    def _finish_rows(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        from_status: JobStatus,
        to_status: JobStatus,
        result: ProcessorResult | None,
        error: ProcessorError | None,
        occurred_at: datetime,
    ) -> None:
        if to_status not in TRANSITIONS[from_status]:
            raise ConflictError(
                f"Недозволений transition {from_status.value}->{to_status.value}",
                {"job_id": job_id},
            )
        result_json = result.to_json() if result is not None else None
        error_json = self._json(error.to_dict()) if error is not None else None
        connection.execute(
            """
            UPDATE processing_jobs
            SET status = ?, result_json = ?, error_json = ?, completed_at = ?,
                lease_token = NULL, lease_expires_at = NULL
            WHERE id = ?
            """,
            (to_status.value, result_json, error_json, occurred_at.isoformat(), job_id),
        )
        connection.execute(
            """
            UPDATE processing_runs
            SET status = ?, completed_at = ?, error_details = ? WHERE id = ?
            """,
            (
                _LEGACY_RUN_STATUS[to_status],
                occurred_at.isoformat(),
                error_json,
                job_id,
            ),
        )
        detail: dict[str, object] = {}
        if result is not None:
            detail["result_manifest_sha256"] = result.manifest_sha256
        if error is not None:
            detail["error"] = error.to_dict()
        self._event(connection, job_id, from_status, to_status, occurred_at, detail)

    def _register_artifacts(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        result: ProcessorResult,
        occurred_at: datetime,
    ) -> None:
        for artifact in result.artifacts:
            connection.execute(
                """
                INSERT INTO file_objects(
                    id, document_file_id, document_id, import_batch_id, kind,
                    original_name, managed_name, source_relative_path,
                    storage_reference, extension, media_type, size_bytes, sha256,
                    integrity_status, review_status, created_at, updated_at
                ) VALUES (?, NULL, NULL, NULL, 'derived', ?, NULL, NULL, ?, ?, ?, ?, ?,
                          'verified', 'unreviewed', ?, ?)
                """,
                (
                    artifact.artifact_id,
                    Path(artifact.relative_path).name,
                    artifact.relative_path,
                    Path(artifact.relative_path).suffix.lstrip(".") or None,
                    artifact.media_type,
                    artifact.size_bytes,
                    artifact.sha256,
                    occurred_at.isoformat(),
                    occurred_at.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO processing_run_files(processing_run_id, file_id, role)
                VALUES (?, ?, 'output')
                """,
                (job_id, artifact.artifact_id),
            )

    @staticmethod
    def _verify_inputs(connection: sqlite3.Connection, request: ProcessorRequest) -> None:
        for item in request.inputs:
            row = connection.execute(
                """
                SELECT sha256, storage_reference, integrity_status
                FROM file_objects WHERE id = ?
                """,
                (item.file_id,),
            ).fetchone()
            if row is None:
                raise ValidationError(
                    "Processor input file_id не знайдено",
                    {"file_id": item.file_id},
                )
            if (
                str(row["sha256"] or "") != item.sha256
                or str(row["storage_reference"] or "") != item.storage_reference
                or str(row["integrity_status"]) != "verified"
            ):
                raise ValidationError(
                    "Processor input не відповідає verified managed file",
                    {"file_id": item.file_id},
                )

    @classmethod
    def _job(cls, row: sqlite3.Row) -> Job:
        result_raw = row["result_json"]
        error_raw = row["error_json"]
        return Job(
            id=str(row["id"]),
            processing_run_id=str(row["processing_run_id"] or row["id"]),
            idempotency_key=str(row["idempotency_key"]),
            status=JobStatus(str(row["status"])),
            attempt=int(row["attempt"]),
            request=ProcessorRequest.from_json(str(row["request_json"])),
            result=(ProcessorResult.from_json(str(result_raw)) if result_raw is not None else None),
            error=(
                ProcessorError.from_dict(json.loads(str(error_raw)))
                if error_raw is not None
                else None
            ),
            lease_token=str(row["lease_token"]) if row["lease_token"] else None,
            lease_expires_at=cls._datetime(row["lease_expires_at"]),
            created_at=cls._required_datetime(row["created_at"]),
            started_at=cls._datetime(row["started_at"]),
            completed_at=cls._datetime(row["completed_at"]),
        )

    @classmethod
    def _job_event(cls, row: sqlite3.Row) -> JobEvent:
        raw_from = row["from_status"]
        detail = json.loads(str(row["detail_json"]))
        if not isinstance(detail, dict):
            detail = {"invalid_detail": True}
        return JobEvent(
            sequence=int(row["sequence"]),
            job_id=str(row["job_id"]),
            from_status=JobStatus(str(raw_from)) if raw_from is not None else None,
            to_status=JobStatus(str(row["to_status"])),
            occurred_at=cls._required_datetime(row["occurred_at"]),
            detail=detail,
        )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        job_id: str,
        from_status: JobStatus | None,
        to_status: JobStatus,
        occurred_at: datetime,
        detail: Mapping[str, object],
    ) -> None:
        connection.execute(
            """
            INSERT INTO processing_job_events(
                job_id, from_status, to_status, occurred_at, detail_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                job_id,
                from_status.value if from_status is not None else None,
                to_status.value,
                occurred_at.isoformat(),
                SQLiteJobStore._json(detail),
            ),
        )

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _datetime(value: object) -> datetime | None:
        return None if value is None else datetime.fromisoformat(str(value))

    @staticmethod
    def _required_datetime(value: object) -> datetime:
        parsed = SQLiteJobStore._datetime(value)
        if parsed is None:
            raise ValueError("Persisted processing timestamp is null")
        return parsed
