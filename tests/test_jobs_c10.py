from __future__ import annotations

import hashlib
import http.client
import json
import os
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from case_docket.application import (
    AcceptOriginalCommand,
    OriginalStorageService,
    SystemClock,
    UuidProvider,
)
from case_docket.application.errors import ConflictError
from case_docket.application.jobs import (
    JobContractError,
    JobService,
    JobStatus,
    ProcessorError,
    ProcessorInput,
    ProcessorRequest,
    ProcessorTool,
    ResourceLimits,
    TRANSITIONS,
    synthetic_reference_processor,
)
from case_docket.plugins.base import CapabilityStatus, discover_plugins
from case_docket.processing import IsolatedWorkerSupervisor, ManagedProcessingWorkspace
from case_docket.repository import SQLiteUnitOfWorkFactory
from case_docket.repository.sqlite_jobs import SQLiteJobStore
from case_docket.storage import ManagedFilesystem
from caseflow.server import CaseFlowState, Handler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
FILE_ID = "11111111-1111-4111-8111-111111111111"


class SequenceIds:
    def __init__(self, *values: str):
        self._values = iter(values)

    def new_id(self) -> str:
        return next(self._values)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)


@dataclass(slots=True)
class C10Runtime:
    root: Path
    database: Path
    original_path: Path
    original_bytes: bytes
    request: ProcessorRequest
    store: SQLiteJobStore
    service: JobService
    supervisor: IsolatedWorkerSupervisor


def make_runtime(
    tmp_path: Path,
    *,
    parameters: dict[str, object] | None = None,
    limits: ResourceLimits | None = None,
) -> C10Runtime:
    root = tmp_path / "synthetic-workspace"
    source_root = tmp_path / "synthetic-source"
    source_root.mkdir()
    original_bytes = b"synthetic immutable original\n"
    (source_root / "original.txt").write_bytes(original_bytes)
    filesystem = ManagedFilesystem(root)
    database = filesystem.layout.zone("database") / "varta.sqlite3"
    unit_of_work_factory = SQLiteUnitOfWorkFactory(database)
    originals = OriginalStorageService(
        unit_of_work_factory,
        filesystem,
        SequenceIds(FILE_ID),
        FixedClock(),
    )
    accepted = originals.accept(
        AcceptOriginalCommand(
            source_root=source_root,
            source_relative_path="original.txt",
            managed_name="syntetychnyi_oryhinal.txt",
            kind="content",
        )
    )
    request = ProcessorRequest(
        processor="synthetic-reference",
        inputs=(
            ProcessorInput(
                file_id=accepted.file_id,
                sha256=accepted.sha256,
                storage_reference=accepted.storage_reference,
            ),
        ),
        parameters=parameters or {"mode": "success", "artifact_text": "synthetic output"},
        tool=ProcessorTool("synthetic-reference", "1.0.0"),
        limits=limits or ResourceLimits(),
    )
    store = SQLiteJobStore(database)
    service = JobService(store, UuidProvider(), SystemClock())
    supervisor = IsolatedWorkerSupervisor(
        service,
        ManagedProcessingWorkspace(root),
    )
    original_path = root / ".varta" / Path(*accepted.storage_reference.split("/"))
    return C10Runtime(
        root,
        database,
        original_path,
        original_bytes,
        request,
        store,
        service,
        supervisor,
    )


def submit(runtime: C10Runtime, key: str = "synthetic-request") -> str:
    return runtime.service.submit(runtime.request, key)


def wait_for_status(runtime: C10Runtime, job_id: str, status: JobStatus) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = runtime.service.require(job_id)
        if job.status == status:
            return
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {status.value}")


def test_state_machine_is_explicit_and_terminal_success_has_no_transition() -> None:
    assert set(TRANSITIONS) == set(JobStatus)
    assert TRANSITIONS[JobStatus.QUEUED] == {
        JobStatus.RUNNING,
        JobStatus.CANCELLED,
        JobStatus.NOT_AVAILABLE,
    }
    assert TRANSITIONS[JobStatus.SUCCEEDED] == set()
    assert JobStatus.QUEUED in TRANSITIONS[JobStatus.FAILED]
    assert JobStatus.QUEUED in TRANSITIONS[JobStatus.INTERRUPTED]


def test_processing_run_and_job_are_created_atomically_and_read_after_restart(
    tmp_path: Path,
) -> None:
    runtime = make_runtime(tmp_path)
    job_id = submit(runtime)
    assert runtime.service.submit(runtime.request, "synthetic-request") == job_id
    queued = runtime.service.require(job_id)
    assert queued.processing_run_id == job_id
    assert queued.status == JobStatus.QUEUED

    claim = runtime.service.claim(job_id)
    assert claim is not None
    now = datetime.now(timezone.utc)
    result = synthetic_reference_processor(
        runtime.request,
        job_id,
        started_at=now,
        completed_at=now,
        artifacts=(),
    )
    runtime.service.succeed(claim, result)

    restarted_store = SQLiteJobStore(runtime.database)
    restarted = JobService(restarted_store, UuidProvider(), SystemClock())
    completed = restarted.require(job_id)
    assert completed.status == JobStatus.SUCCEEDED
    assert completed.result == result
    run = restarted_store.processing_run(job_id)
    assert run is not None
    assert run["status"] == "succeeded"
    assert json.loads(str(run["parameters_json"]))["request_sha256"] == runtime.request.sha256
    assert [event.to_status for event in restarted.events(job_id)] == [
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.SUCCEEDED,
    ]
    with sqlite3.connect(runtime.database) as connection:
        linked_run = connection.execute(
            "SELECT processing_run_id FROM processing_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        assert linked_run == (job_id,)
        with pytest.raises(sqlite3.IntegrityError, match="run link is immutable"):
            connection.execute(
                "UPDATE processing_jobs SET processing_run_id = ? WHERE id = ?",
                ("22222222-2222-4222-8222-222222222222", job_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="events are append-only"):
            connection.execute(
                "UPDATE processing_job_events SET detail_json = '{}' WHERE job_id = ?",
                (job_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="events are append-only"):
            connection.execute("DELETE FROM processing_job_events WHERE job_id = ?", (job_id,))
    with pytest.raises(ConflictError):
        restarted.retry(job_id)


def test_duplicate_key_with_different_request_is_conflict(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    submit(runtime, "same-key")
    changed = ProcessorRequest(
        processor=runtime.request.processor,
        inputs=runtime.request.inputs,
        parameters={"mode": "fail"},
        tool=runtime.request.tool,
        limits=runtime.request.limits,
    )
    with pytest.raises(ConflictError, match="idempotency_key"):
        runtime.service.submit(changed, "same-key")


def test_isolated_worker_success_registers_verified_derived_artifact_and_provenance(
    tmp_path: Path,
) -> None:
    runtime = make_runtime(tmp_path)
    original_before = hashlib.sha256(runtime.original_path.read_bytes()).hexdigest()
    job_id = submit(runtime)

    outcome = runtime.supervisor.run_once(job_id)

    assert outcome.status == JobStatus.SUCCEEDED
    job = runtime.service.require(job_id)
    assert job.result is not None
    job.result.verify_digest()
    job.result.verify_request(runtime.request, job_id)
    assert len(job.result.artifacts) == 1
    artifact = job.result.artifacts[0]
    artifact_path = runtime.root / ".varta" / Path(*artifact.relative_path.split("/"))
    assert artifact_path.read_text(encoding="utf-8") == "synthetic output"
    assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == artifact.sha256
    assert not bool(artifact_path.stat().st_mode & stat.S_IWUSR)
    assert job_id in job.result.stdout_summary
    assert runtime.original_path.read_bytes() == runtime.original_bytes
    assert hashlib.sha256(runtime.original_path.read_bytes()).hexdigest() == original_before

    connection = sqlite3.connect(runtime.database)
    try:
        rows = connection.execute(
            """
            SELECT role, file_id FROM processing_run_files
            WHERE processing_run_id = ? ORDER BY role
            """,
            (job_id,),
        ).fetchall()
        output = connection.execute(
            "SELECT kind, sha256, integrity_status FROM file_objects WHERE id = ?",
            (artifact.artifact_id,),
        ).fetchone()
    finally:
        connection.close()
    assert rows == [("input", FILE_ID), ("output", artifact.artifact_id)]
    assert output == ("derived", artifact.sha256, "verified")


def test_failure_is_retryable_and_second_attempt_succeeds(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path, parameters={"mode": "fail_once"})
    job_id = submit(runtime)
    first = runtime.supervisor.run_once(job_id)
    assert first.status == JobStatus.FAILED
    failed = runtime.service.require(job_id)
    assert failed.attempt == 1
    assert failed.error is not None and failed.error.code == "synthetic_failure"

    retried = runtime.service.retry(job_id)
    assert retried.status == JobStatus.QUEUED
    second = runtime.supervisor.run_once(job_id)
    assert second.status == JobStatus.SUCCEEDED
    assert runtime.service.require(job_id).attempt == 2


def test_non_retryable_failure_cannot_be_requeued(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    job_id = submit(runtime)
    claim = runtime.service.claim(job_id)
    assert claim is not None
    runtime.service.fail(
        claim,
        ProcessorError("synthetic_terminal_failure", "Synthetic terminal failure", False),
    )

    with pytest.raises(ConflictError, match="non-retryable"):
        runtime.service.retry(job_id)


@pytest.mark.parametrize("_repeat", range(3))
def test_timeout_terminates_worker_and_quarantines_attempt(
    tmp_path: Path,
    _repeat: int,
) -> None:
    runtime = make_runtime(
        tmp_path,
        parameters={"mode": "hang"},
        limits=ResourceLimits(timeout_seconds=0.2),
    )
    job_id = submit(runtime)
    outcome = runtime.supervisor.run_once(job_id)
    job = runtime.service.require(job_id)
    assert outcome.status == JobStatus.FAILED
    assert job.error is not None and job.error.code == "timeout"
    assert outcome.quarantine_reference is not None
    assert (runtime.root / ".varta" / outcome.quarantine_reference).is_dir()
    assert runtime.original_path.read_bytes() == runtime.original_bytes


def test_worker_heartbeats_keep_a_short_lease_alive(tmp_path: Path) -> None:
    runtime = make_runtime(
        tmp_path,
        parameters={
            "mode": "success",
            "sleep_seconds": 0.4,
            "artifact_text": "synthetic heartbeat output",
        },
    )
    runtime.supervisor = IsolatedWorkerSupervisor(
        runtime.service,
        ManagedProcessingWorkspace(runtime.root),
        poll_interval=0.01,
        lease_seconds=0.15,
        heartbeat_interval=0.03,
    )
    job_id = submit(runtime)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runtime.supervisor.run_once, job_id)
        wait_for_status(runtime, job_id, JobStatus.RUNNING)
        time.sleep(0.25)
        restarted = JobService(SQLiteJobStore(runtime.database), UuidProvider(), SystemClock())
        assert restarted.recover_expired() == 0
        outcome = future.result(timeout=5)

    assert outcome.status == JobStatus.SUCCEEDED
    assert runtime.service.require(job_id).status == JobStatus.SUCCEEDED


def test_worker_environment_does_not_inherit_parent_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_key = "VARTA_SYNTHETIC_CREDENTIAL_FOR_C10_TEST"
    monkeypatch.setenv(environment_key, "synthetic-secret-must-not-cross-worker-boundary")
    runtime = make_runtime(
        tmp_path,
        parameters={
            "mode": "success",
            "assert_environment_absent": environment_key,
        },
    )
    job_id = submit(runtime)

    assert runtime.supervisor.run_once(job_id).status == JobStatus.SUCCEEDED


def test_running_worker_can_be_cancelled_durably(tmp_path: Path) -> None:
    runtime = make_runtime(
        tmp_path,
        parameters={"mode": "success", "sleep_seconds": 2},
        limits=ResourceLimits(timeout_seconds=5),
    )
    job_id = submit(runtime)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runtime.supervisor.run_once, job_id)
        wait_for_status(runtime, job_id, JobStatus.RUNNING)
        pending = runtime.service.cancel(job_id)
        assert pending.status == JobStatus.RUNNING
        outcome = future.result(timeout=5)
    assert outcome.status == JobStatus.CANCELLED
    assert runtime.service.require(job_id).status == JobStatus.CANCELLED
    assert runtime.original_path.read_bytes() == runtime.original_bytes


def test_worker_crash_is_interrupted_and_retryable(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path, parameters={"mode": "crash"})
    job_id = submit(runtime)
    outcome = runtime.supervisor.run_once(job_id)
    assert outcome.status == JobStatus.INTERRUPTED
    assert runtime.service.require(job_id).error.code == "worker_crashed"  # type: ignore[union-attr]
    assert runtime.service.retry(job_id).status == JobStatus.QUEUED


def test_expired_lease_is_recovered_after_controller_restart(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    job_id = submit(runtime)
    claim = runtime.service.claim(job_id, lease_seconds=0.05)
    assert claim is not None
    time.sleep(0.08)

    restarted_store = SQLiteJobStore(runtime.database)
    restarted = JobService(restarted_store, UuidProvider(), SystemClock())
    assert restarted.recover_expired() == 1
    interrupted = restarted.require(job_id)
    assert interrupted.status == JobStatus.INTERRUPTED
    assert interrupted.error is not None
    assert interrupted.error.code == "worker_lease_expired"
    assert restarted.retry(job_id).status == JobStatus.QUEUED


@pytest.mark.parametrize(
    "mode",
    ["invalid_manifest", "manifest_digest_mismatch", "hash_mismatch"],
)
def test_invalid_manifest_or_hash_mismatch_is_quarantined(
    tmp_path: Path,
    mode: str,
) -> None:
    runtime = make_runtime(tmp_path, parameters={"mode": mode})
    job_id = submit(runtime)
    outcome = runtime.supervisor.run_once(job_id)
    job = runtime.service.require(job_id)
    assert outcome.status == JobStatus.FAILED
    assert job.error is not None and job.error.code == "invalid_worker_result"
    assert outcome.quarantine_reference is not None
    quarantine = runtime.root / ".varta" / outcome.quarantine_reference
    assert quarantine.is_dir()
    assert runtime.original_path.read_bytes() == runtime.original_bytes
    connection = sqlite3.connect(runtime.database)
    try:
        outputs = connection.execute(
            "SELECT COUNT(*) FROM processing_run_files WHERE processing_run_id = ? AND role = 'output'",
            (job_id,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert outputs == 0


def test_artifact_resource_limit_is_enforced(tmp_path: Path) -> None:
    runtime = make_runtime(
        tmp_path,
        parameters={"mode": "success", "artifact_text": "x" * 128},
        limits=ResourceLimits(max_artifact_bytes=32),
    )
    job_id = submit(runtime)
    outcome = runtime.supervisor.run_once(job_id)
    assert outcome.status == JobStatus.FAILED
    assert runtime.service.require(job_id).error.code == "invalid_worker_result"  # type: ignore[union-attr]


def test_plugin_discovery_has_explicit_available_unavailable_and_failed_states() -> None:
    capabilities = discover_plugins(
        {
            "synthetic-reference": "case_docket.processing.synthetic_worker",
            "missing": "case_docket.plugins.missing_dependency_for_test",
            "invalid-scaffold": "case_docket.plugins.ocr",
        }
    )
    assert capabilities["synthetic-reference"].status == CapabilityStatus.AVAILABLE
    assert capabilities["synthetic-reference"].plugin_version == "1.0.0"
    assert capabilities["missing"].status == CapabilityStatus.UNAVAILABLE_DEPENDENCY
    assert capabilities["invalid-scaffold"].status == CapabilityStatus.FAILED


def test_installed_worker_capability_and_frozen_hidden_import_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "case_docket.processing.synthetic_worker",
            "--capabilities",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    capability = json.loads(completed.stdout)
    assert capability["status"] == "available"
    assert capability["network_required"] is False
    build_script = (ROOT / "tools" / "windows" / "build_caseflow_exe.ps1").read_text(
        encoding="utf-8"
    )
    assert '"--hidden-import", "case_docket.processing.synthetic_worker"' in build_script

    runtime = make_runtime(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("VARTA_PROCESSOR_WORKER", raising=False)
    frozen = IsolatedWorkerSupervisor(
        runtime.service,
        ManagedProcessingWorkspace(runtime.root),
    )
    assert frozen.capability().status == CapabilityStatus.UNAVAILABLE_DEPENDENCY
    configured_frozen = IsolatedWorkerSupervisor(
        runtime.service,
        ManagedProcessingWorkspace(runtime.root),
        worker_command_prefix=(
            sys.executable,
            "-m",
            "case_docket.processing.synthetic_worker",
        ),
    )
    assert configured_frozen.capability().status == CapabilityStatus.AVAILABLE


def test_server_remains_responsive_while_isolated_worker_runs(tmp_path: Path) -> None:
    runtime = make_runtime(
        tmp_path,
        parameters={"mode": "success", "sleep_seconds": 0.6},
        limits=ResourceLimits(timeout_seconds=5),
    )
    job_id = submit(runtime)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    state = CaseFlowState(runtime.root, "127.0.0.1", port)
    state.prepare_database()
    server.state = state  # type: ignore[attr-defined]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            worker = executor.submit(runtime.supervisor.run_once, job_id)
            wait_for_status(runtime, job_id, JobStatus.RUNNING)
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                connection.request("GET", "/api/v1/status")
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                connection.close()
            assert response.status == 200
            assert payload["apiVersion"] == "v1"
            assert worker.result(timeout=5).status == JobStatus.SUCCEEDED
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        state.close()


def test_request_and_result_contract_reject_malformed_hashes(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    with pytest.raises(JobContractError, match="SHA-256"):
        ProcessorInput(FILE_ID, "not-a-hash", runtime.request.inputs[0].storage_reference)
    job_id = submit(runtime)
    claim = runtime.service.claim(job_id)
    assert claim is not None
    now = datetime.now(timezone.utc)
    result = synthetic_reference_processor(
        runtime.request,
        job_id,
        started_at=now,
        completed_at=now,
        artifacts=(),
    )
    payload = result.to_dict()
    payload["request_sha256"] = "0" * 64
    tampered = json.dumps(payload)
    parsed = type(result).from_json(tampered)
    with pytest.raises(JobContractError, match="SHA-256 mismatch"):
        parsed.verify_digest()


def test_powershell_build_script_parses() -> None:
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "'D:\\VARTA\\tools\\windows\\build_caseflow_exe.ps1',"
        "[ref]$tokens,[ref]$errors) | Out-Null; "
        "if($errors.Count -gt 0){$errors | ForEach-Object {$_.Message}; exit 1}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
