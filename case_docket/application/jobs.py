"""C10 durable jobs: SQLite is the authority; workers receive JSON only."""

from __future__ import annotations
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUSES = frozenset(
    {"queued", "running", "succeeded", "failed", "cancelled", "interrupted", "not_available"}
)
TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled", "interrupted"},
    "interrupted": {"queued", "cancelled"},
    "failed": {"queued"},
    "not_available": {"queued"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ProcessorRequest:
    processor: str
    input_ids: tuple[str, ...]
    input_hashes: tuple[str, ...]
    parameters: dict[str, Any]
    tool_version: str
    timeout_seconds: int = 30

    def to_json(self) -> str:
        return json.dumps(
            {
                "contract_version": 1,
                "input_ids": self.input_ids,
                "input_hashes": self.input_hashes,
                "parameters": self.parameters,
                "tool_version": self.tool_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    status: str
    attempt: int
    result: dict[str, Any] | None


class JobService:
    def __init__(self, database_path: Path):
        import importlib
        connection = importlib.import_module("case_docket.repository.sqlite_connection")
        migrations = importlib.import_module("case_docket.repository.migrations")
        self.factory = connection.SQLiteConnectionFactory(database_path)
        with self.factory.connect() as db:
            migrations.MigrationRunner(db).migrate()

    def submit(self, request: ProcessorRequest, idempotency_key: str) -> str:
        if request.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        job_id = str(uuid.uuid4())
        now = _now()
        with self.factory.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM processing_jobs WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if row:
                db.commit()
                return str(row[0])
            db.execute(
                "INSERT INTO processing_jobs(id,idempotency_key,processor,request_json,status,timeout_seconds,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    job_id,
                    idempotency_key,
                    request.processor,
                    request.to_json(),
                    "queued",
                    request.timeout_seconds,
                    now,
                ),
            )
            db.execute(
                "INSERT INTO processing_job_events(job_id,to_status,occurred_at) VALUES(?,?,?)",
                (job_id, "queued", now),
            )
            db.commit()
        return job_id

    def claim(self, job_id: str, lease_seconds: int = 30) -> tuple[str, str]:
        token = str(uuid.uuid4())
        now = _now()
        with self.factory.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,attempt FROM processing_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row or row[0] not in ("queued", "interrupted", "failed"):
                raise ValueError("job is not claimable")
            db.execute(
                "UPDATE processing_jobs SET status='running',attempt=attempt+1,lease_token=?,lease_expires_at=?,started_at=? WHERE id=?",
                (
                    token,
                    datetime.fromtimestamp(
                        datetime.now().timestamp() + lease_seconds, timezone.utc
                    ).isoformat(),
                    now,
                    job_id,
                ),
            )
            db.execute(
                "INSERT INTO processing_job_events(job_id,from_status,to_status,occurred_at) VALUES(?,?,?,?)",
                (job_id, row[0], "running", now),
            )
            db.commit()
        return token, job_id

    def finalize(
        self, job_id: str, token: str, result: dict[str, Any], *, status: str = "succeeded"
    ) -> None:
        if status not in ("succeeded", "failed", "cancelled"):
            raise ValueError("invalid terminal status")
        payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
        now = _now()
        with self.factory.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status FROM processing_jobs WHERE id=? AND lease_token=?", (job_id, token)
            ).fetchone()
            if not row or row[0] != "running":
                raise ValueError("invalid or expired lease")
            db.execute(
                "UPDATE processing_jobs SET status=?,result_json=?,completed_at=?,lease_token=NULL WHERE id=?",
                (status, payload, now, job_id),
            )
            db.execute(
                "INSERT INTO processing_job_events(job_id,from_status,to_status,occurred_at) VALUES(?,?,?,?)",
                (job_id, "running", status, now),
            )
            db.commit()

    def recover_expired(self) -> int:
        with self.factory.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT id FROM processing_jobs WHERE status='running' AND lease_expires_at < ?",
                (_now(),),
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE processing_jobs SET status='interrupted',lease_token=NULL WHERE id=?",
                    (row[0],),
                )
                db.execute(
                    "INSERT INTO processing_job_events(job_id,from_status,to_status,occurred_at) VALUES(?,?,?,?)",
                    (row[0], "running", "interrupted", _now()),
                )
            db.commit()
            return len(rows)

    def get(self, job_id: str) -> Job | None:
        with self.factory.connect() as db:
            row = db.execute(
                "SELECT id,status,attempt,result_json FROM processing_jobs WHERE id=?", (job_id,)
            ).fetchone()
            return (
                None
                if not row
                else Job(
                    str(row[0]), str(row[1]), int(row[2]), json.loads(row[3]) if row[3] else None
                )
            )


def synthetic_reference_processor(request: ProcessorRequest) -> dict[str, Any]:
    digest = hashlib.sha256(request.to_json().encode()).hexdigest()
    return {
        "contract_version": 1,
        "processor": request.processor,
        "tool_version": request.tool_version,
        "input_ids": list(request.input_ids),
        "input_hashes": list(request.input_hashes),
        "parameters": request.parameters,
        "artifacts": [],
        "findings": [],
        "confidence": 1.0,
        "result_digest": digest,
    }
