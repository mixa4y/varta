"""Durable supervisor for one isolated local processor subprocess."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from case_docket.application.jobs import (
    JobClaim,
    JobContractError,
    JobService,
    JobStatus,
    ProcessorError,
    ProcessorResult,
)
from case_docket.plugins.base import (
    CapabilityStatus,
    PluginCapability,
    discover_plugins,
)
from case_docket.storage.errors import ManagedStorageError

from .workspace import ManagedProcessingWorkspace, ProcessingAttempt


@dataclass(frozen=True, slots=True)
class SupervisorOutcome:
    job_id: str | None
    status: JobStatus | None
    returncode: int | None
    quarantine_reference: str | None = None


class IsolatedWorkerSupervisor:
    """Claim one durable job, supervise a subprocess, then finalize via JobService."""

    def __init__(
        self,
        service: JobService,
        workspace: ManagedProcessingWorkspace,
        *,
        worker_command_prefix: Sequence[str] | None = None,
        poll_interval: float = 0.02,
        lease_seconds: float = 60.0,
        heartbeat_interval: float = 10.0,
    ):
        if poll_interval <= 0:
            raise ValueError("poll_interval має бути додатним")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds має бути додатним")
        if heartbeat_interval <= 0 or heartbeat_interval >= lease_seconds:
            raise ValueError("heartbeat_interval має бути між нулем і lease_seconds")
        self.service = service
        self.workspace = workspace
        self.poll_interval = poll_interval
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self._worker_command_prefix = (
            tuple(worker_command_prefix)
            if worker_command_prefix is not None
            else self._default_worker_command()
        )

    def capability(self) -> PluginCapability:
        discovered = discover_plugins(
            {"synthetic-reference": "case_docket.processing.synthetic_worker"}
        )["synthetic-reference"]
        if not self._worker_command_prefix:
            return PluginCapability(
                name=discovered.name,
                status=CapabilityStatus.UNAVAILABLE_DEPENDENCY,
                contract_version=discovered.contract_version,
                plugin_version=discovered.plugin_version,
                detail="frozen companion worker command is not configured",
            )
        return discovered

    def run_once(self, job_id: str | None = None) -> SupervisorOutcome:
        self.service.recover_expired()
        claim = self.service.claim(job_id, lease_seconds=self.lease_seconds)
        if claim is None:
            return SupervisorOutcome(None, None, None)

        capability = self.capability()
        if capability.status != CapabilityStatus.AVAILABLE:
            error = ProcessorError(
                "processor_not_available",
                "Requested local processor capability is unavailable",
                True,
                {"capability_status": capability.status.value},
            )
            job = self.service.mark_not_available(claim, error)
            return SupervisorOutcome(job.id, job.status, None)

        attempt: ProcessingAttempt | None = None
        process: subprocess.Popen[bytes] | None = None
        try:
            attempt = self.workspace.prepare(claim)
            command = [*self._worker_command_prefix, "--request", str(attempt.request_path)]
            started = time.monotonic()
            heartbeat_at = 0.0
            with attempt.stdout_path.open("wb") as stdout, attempt.stderr_path.open("wb") as stderr:
                process = subprocess.Popen(
                    command,
                    cwd=attempt.root,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    env=self._worker_environment(),
                )
                while process.poll() is None:
                    if self.service.cancellation_requested(claim):
                        self._terminate(process)
                        stdout.close()
                        stderr.close()
                        quarantine = self.workspace.quarantine(attempt)
                        error = ProcessorError(
                            "cancelled",
                            "Processing job cancelled by request",
                            False,
                            {"quarantine_reference": quarantine},
                        )
                        job = self.service.finish_cancelled(claim, error)
                        return SupervisorOutcome(
                            job.id,
                            job.status,
                            process.returncode,
                            quarantine,
                        )
                    elapsed = time.monotonic() - started
                    if elapsed >= claim.job.request.limits.timeout_seconds:
                        self._terminate(process)
                        stdout.close()
                        stderr.close()
                        error = ProcessorError(
                            "timeout",
                            "Processing worker exceeded its wall-clock timeout",
                            True,
                            {"timeout_seconds": claim.job.request.limits.timeout_seconds},
                        )
                        quarantine = self.workspace.quarantine(attempt)
                        error = self._with_quarantine(error, quarantine)
                        job = self.service.fail(claim, error)
                        return SupervisorOutcome(
                            job.id,
                            job.status,
                            process.returncode,
                            quarantine,
                        )
                    if elapsed - heartbeat_at >= self.heartbeat_interval:
                        self.service.heartbeat(claim, lease_seconds=self.lease_seconds)
                        heartbeat_at = elapsed
                    time.sleep(self.poll_interval)

            returncode = process.returncode
            if returncode != 0:
                quarantine = self.workspace.quarantine(attempt)
                error = ProcessorError(
                    "worker_crashed",
                    "Processing worker exited before authoritative finalize",
                    True,
                    {"returncode": returncode, "quarantine_reference": quarantine},
                )
                job = self.service.interrupt(claim, error)
                return SupervisorOutcome(job.id, job.status, returncode, quarantine)

            result = self.workspace.read_result(
                attempt,
                max_bytes=claim.job.request.limits.max_result_bytes,
            )
            result.verify_digest()
            result.verify_request(claim.job.request, claim.job.processing_run_id)
            stdout_summary = self.workspace.read_summary(
                attempt.stdout_path,
                max_chars=claim.job.request.limits.max_stdout_chars,
            )
            stderr_summary = self.workspace.read_summary(
                attempt.stderr_path,
                max_chars=claim.job.request.limits.max_stderr_chars,
            )
            result = replace(
                result,
                stdout_summary=stdout_summary,
                stderr_summary=stderr_summary,
                manifest_sha256=None,
            ).seal()
            if result.status == JobStatus.FAILED:
                assert result.error is not None
                job = self.service.fail(claim, result.error, result=result)
                self.workspace.cleanup(attempt)
                return SupervisorOutcome(job.id, job.status, returncode)
            if result.status == JobStatus.NOT_AVAILABLE:
                assert result.error is not None
                job = self.service.mark_not_available(claim, result.error)
                self.workspace.cleanup(attempt)
                return SupervisorOutcome(job.id, job.status, returncode)

            self._check_artifact_limits(claim, result)
            self.workspace.assert_originals_unchanged(attempt, claim)
            artifacts = self.workspace.verify_and_finalize_artifacts(attempt, result)
            self.workspace.assert_originals_unchanged(attempt, claim)
            finalized = replace(
                result,
                artifacts=artifacts,
                manifest_sha256=None,
            ).seal()
            job = self.service.succeed(claim, finalized)
            self.workspace.cleanup(attempt)
            return SupervisorOutcome(job.id, job.status, returncode)
        except (JobContractError, ManagedStorageError, OSError, ValueError) as exc:
            quarantine_reference: str | None = None
            if attempt is not None and attempt.root.exists():
                quarantine_reference = self.workspace.quarantine(attempt)
            error = ProcessorError(
                "invalid_worker_result",
                "Worker output failed contract, path or integrity validation",
                True,
                {
                    "failure_type": type(exc).__name__,
                    "quarantine_reference": quarantine_reference,
                },
            )
            job = self.service.fail(claim, error)
            return SupervisorOutcome(
                job.id,
                job.status,
                process.returncode if process is not None else None,
                quarantine_reference,
            )

    @staticmethod
    def _check_artifact_limits(claim: JobClaim, result: ProcessorResult) -> None:
        limit = claim.job.request.limits.max_artifact_bytes
        if any(artifact.size_bytes > limit for artifact in result.artifacts):
            raise JobContractError("Worker artifact перевищує max_artifact_bytes")
        if sum(artifact.size_bytes for artifact in result.artifacts) > limit:
            raise JobContractError("Worker artifacts перевищують aggregate byte limit")

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            if process.poll() is not None:
                return
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    @staticmethod
    def _with_quarantine(error: ProcessorError, reference: str) -> ProcessorError:
        return ProcessorError(
            error.code,
            error.message,
            error.retryable,
            {**error.details, "quarantine_reference": reference},
        )

    @staticmethod
    def _worker_environment() -> dict[str, str]:
        allowed = {
            "COMSPEC",
            "PATH",
            "PATHEXT",
            "SystemDrive",
            "SystemRoot",
            "TEMP",
            "TMP",
            "WINDIR",
        }
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.casefold() in {name.casefold() for name in allowed}
        }
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        environment["VARTA_PROCESSOR_NETWORK"] = "disabled"
        return environment

    @staticmethod
    def _default_worker_command() -> tuple[str, ...]:
        if getattr(sys, "frozen", False):
            configured = os.environ.get("VARTA_PROCESSOR_WORKER")
            return (configured,) if configured else ()
        return (
            sys.executable,
            "-m",
            "case_docket.processing.synthetic_worker",
        )
