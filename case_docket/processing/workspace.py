"""Managed path and integrity boundary for isolated processing workers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from case_docket.application.jobs import (
    JobClaim,
    JobContractError,
    ProcessorArtifact,
    ProcessorResult,
)
from case_docket.storage.errors import StorageIntegrityError, UnsafePathError
from case_docket.storage.paths import (
    WorkspaceLayout,
    assert_not_reparse,
    native_path,
    resolve_managed_reference,
    validate_relative_path,
)


@dataclass(frozen=True, slots=True)
class ProcessingAttempt:
    job_id: str
    attempt: int
    root: Path
    request_path: Path
    result_path: Path
    stdout_path: Path
    stderr_path: Path
    original_hashes: tuple[tuple[str, str], ...]


class ManagedProcessingWorkspace:
    """Workers can read verified originals and write only to one attempt root."""

    def __init__(self, workspace_root: Path, *, chunk_size: int = 1024 * 1024):
        if chunk_size < 1:
            raise ValueError("chunk_size має бути додатним")
        self.layout = WorkspaceLayout(workspace_root)
        self.layout.initialize()
        self._chunk_size = chunk_size

    def prepare(self, claim: JobClaim) -> ProcessingAttempt:
        attempt_root = (
            self.layout.zone("working") / claim.job.id / f"attempt-{claim.job.attempt:04d}"
        )
        if attempt_root.exists():
            raise UnsafePathError("Processing attempt path вже існує")
        attempt_root.mkdir(parents=True)
        assert_not_reparse(attempt_root)

        resolved_inputs: list[dict[str, str]] = []
        snapshots: list[tuple[str, str]] = []
        for item in claim.job.request.inputs:
            target = resolve_managed_reference(
                self.layout.managed_root,
                item.storage_reference,
            )
            metadata = assert_not_reparse(target)
            if not stat.S_ISREG(metadata.st_mode):
                raise StorageIntegrityError("Processor input не є regular managed file")
            if bool(metadata.st_mode & stat.S_IWUSR):
                raise StorageIntegrityError("Processor input original не є read-only")
            actual = self._sha256(target)
            if actual != item.sha256:
                raise StorageIntegrityError("Processor input original SHA-256 mismatch")
            snapshots.append((item.file_id, actual))
            resolved_inputs.append(
                {
                    "file_id": item.file_id,
                    "sha256": item.sha256,
                    "storage_reference": item.storage_reference,
                    "read_path": str(target),
                }
            )

        request_path = attempt_root / "request.json"
        result_path = attempt_root / "result.json"
        envelope = {
            "contract": "varta.processor-envelope",
            "contract_version": 1,
            "processing_run_id": claim.job.processing_run_id,
            "attempt": claim.job.attempt,
            "request": claim.job.request.to_dict(),
            "inputs": resolved_inputs,
            "write_root": str(attempt_root),
            "result_path": str(result_path),
        }
        self._write_json(request_path, envelope)
        return ProcessingAttempt(
            job_id=claim.job.id,
            attempt=claim.job.attempt,
            root=attempt_root,
            request_path=request_path,
            result_path=result_path,
            stdout_path=attempt_root / "stdout.log",
            stderr_path=attempt_root / "stderr.log",
            original_hashes=tuple(snapshots),
        )

    def read_result(self, attempt: ProcessingAttempt, *, max_bytes: int) -> ProcessorResult:
        try:
            metadata = assert_not_reparse(attempt.result_path)
        except UnsafePathError as exc:
            raise JobContractError("Worker result manifest відсутній або unsafe") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise JobContractError("Worker result manifest не є regular file")
        if metadata.st_size > max_bytes:
            raise JobContractError("Worker result manifest перевищує max_result_bytes")
        try:
            text = attempt.result_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise JobContractError("Worker result manifest не читається") from exc
        return ProcessorResult.from_json(text)

    def verify_and_finalize_artifacts(
        self,
        attempt: ProcessingAttempt,
        result: ProcessorResult,
    ) -> tuple[ProcessorArtifact, ...]:
        verified: list[tuple[ProcessorArtifact, Path, Path]] = []
        destinations: set[Path] = set()
        for artifact in result.artifacts:
            artifact_id_components = validate_relative_path(artifact.artifact_id)
            if len(artifact_id_components) != 1:
                raise JobContractError("artifact_id має бути одним safe path component")
            components = validate_relative_path(artifact.relative_path)
            if components[0] != "artifacts":
                raise JobContractError("Worker artifact має бути у artifacts/")
            source = attempt.root.joinpath(*components)
            self._assert_under(source, attempt.root)
            self._assert_chain(source, attempt.root)
            metadata = assert_not_reparse(source)
            if not stat.S_ISREG(metadata.st_mode):
                raise JobContractError("Worker artifact не є regular file")
            if metadata.st_size != artifact.size_bytes:
                raise JobContractError("Worker artifact size mismatch")
            actual = self._sha256(source)
            if actual != artifact.sha256:
                raise JobContractError("Worker artifact SHA-256 mismatch")
            destination = (
                self.layout.zone("derived")
                / "v1"
                / attempt.job_id
                / artifact.artifact_id
                / source.name
            )
            if destination in destinations or destination.exists():
                raise JobContractError("Derived artifact destination collision")
            destinations.add(destination)
            verified.append((artifact, source, destination))

        finalized: list[ProcessorArtifact] = []
        for artifact, source, destination in verified:
            destination.parent.mkdir(parents=True, exist_ok=False)
            assert_not_reparse(destination.parent)
            os.rename(native_path(source), native_path(destination))
            self._set_readonly(destination)
            if self._sha256(destination) != artifact.sha256:
                raise StorageIntegrityError("Finalized derived artifact SHA-256 mismatch")
            finalized.append(
                ProcessorArtifact(
                    artifact_id=artifact.artifact_id,
                    role=artifact.role,
                    relative_path=destination.relative_to(self.layout.managed_root).as_posix(),
                    sha256=artifact.sha256,
                    size_bytes=artifact.size_bytes,
                    media_type=artifact.media_type,
                    source_file_ids=artifact.source_file_ids,
                )
            )
        return tuple(finalized)

    def assert_originals_unchanged(self, attempt: ProcessingAttempt, claim: JobClaim) -> None:
        expected = dict(attempt.original_hashes)
        for item in claim.job.request.inputs:
            target = resolve_managed_reference(
                self.layout.managed_root,
                item.storage_reference,
            )
            metadata = assert_not_reparse(target)
            if not stat.S_ISREG(metadata.st_mode) or bool(metadata.st_mode & stat.S_IWUSR):
                raise StorageIntegrityError("Processor змінив original permissions/type")
            if self._sha256(target) != expected[item.file_id]:
                raise StorageIntegrityError("Processor змінив immutable original bytes")

    def quarantine(self, attempt: ProcessingAttempt) -> str:
        destination = (
            self.layout.zone("quarantine") / attempt.job_id / f"attempt-{attempt.attempt:04d}"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise UnsafePathError("Quarantine attempt path вже існує")
        if attempt.root.exists():
            self._rename_directory_with_retry(attempt.root, destination)
        return destination.relative_to(self.layout.managed_root).as_posix()

    def cleanup(self, attempt: ProcessingAttempt) -> None:
        self._assert_under(attempt.root, self.layout.zone("working"))
        if attempt.root.exists():
            shutil.rmtree(attempt.root)
        parent = attempt.root.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()

    def read_summary(self, path: Path, *, max_chars: int) -> str:
        if not path.exists():
            return ""
        metadata = assert_not_reparse(path)
        if not stat.S_ISREG(metadata.st_mode):
            return ""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                return stream.read(max_chars)
        except OSError:
            return ""

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(self._chunk_size), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        temporary = path.with_suffix(".tmp")
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(
                value,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(native_path(temporary), native_path(path))

    @staticmethod
    def _assert_under(path: Path, root: Path) -> None:
        absolute = Path(os.path.abspath(os.fspath(path)))
        absolute_root = Path(os.path.abspath(os.fspath(root)))
        if absolute != absolute_root and absolute_root not in absolute.parents:
            raise UnsafePathError("Processing path виходить за managed root")

    @staticmethod
    def _assert_chain(path: Path, root: Path) -> None:
        current = root
        assert_not_reparse(current)
        for component in path.relative_to(root).parts:
            current /= component
            assert_not_reparse(current)

    @staticmethod
    def _set_readonly(path: Path) -> None:
        mode = os.stat(native_path(path), follow_symlinks=False).st_mode
        os.chmod(native_path(path), mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))

    @staticmethod
    def _rename_directory_with_retry(source: Path, destination: Path) -> None:
        deadline = time.monotonic() + 2.0
        while True:
            try:
                os.rename(native_path(source), native_path(destination))
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
