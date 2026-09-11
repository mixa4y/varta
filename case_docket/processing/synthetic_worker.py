"""Synthetic reference processor used to prove the C10 worker contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from case_docket.application.jobs import (
    JobStatus,
    ProcessorArtifact,
    ProcessorError,
    ProcessorRequest,
    ProcessorResult,
    synthetic_reference_processor,
)


PLUGIN_CONTRACT_VERSION = 1
PLUGIN_VERSION = "1.0.0"
PLUGIN_NAME = "synthetic-reference"


def capabilities() -> dict[str, object]:
    return {
        "contract": "varta.processor-capability",
        "contract_version": PLUGIN_CONTRACT_VERSION,
        "name": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
        "status": "available",
        "network_required": False,
        "algorithms": ["synthetic"],
    }


def run(request_path: Path) -> int:
    try:
        envelope = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Synthetic worker request envelope is unreadable") from exc
    if not isinstance(envelope, dict):
        raise RuntimeError("Synthetic worker envelope must be an object")
    if (
        envelope.get("contract") != "varta.processor-envelope"
        or envelope.get("contract_version") != 1
    ):
        raise RuntimeError("Synthetic worker envelope contract is unsupported")
    request = ProcessorRequest.from_dict(envelope.get("request"))
    if request.processor != PLUGIN_NAME:
        raise RuntimeError("Synthetic worker received a different processor")
    processing_run_id = str(envelope.get("processing_run_id") or "")
    attempt = int(envelope.get("attempt") or 0)
    write_root = Path(str(envelope.get("write_root") or ""))
    result_path = Path(str(envelope.get("result_path") or ""))
    if result_path.parent != write_root or request_path.parent != write_root:
        raise RuntimeError("Synthetic worker write paths escape the attempt root")

    inputs = envelope.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != len(request.inputs):
        raise RuntimeError("Synthetic worker input envelope does not match request")
    for descriptor, expected in zip(inputs, request.inputs, strict=True):
        if not isinstance(descriptor, dict):
            raise RuntimeError("Synthetic worker input descriptor is invalid")
        if descriptor.get("file_id") != expected.file_id:
            raise RuntimeError("Synthetic worker file_id mismatch")
        read_path = Path(str(descriptor.get("read_path") or ""))
        if _sha256(read_path) != expected.sha256:
            raise RuntimeError("Synthetic worker input SHA-256 mismatch")

    mode = str(request.parameters.get("mode", "success"))
    raw_sleep_seconds = request.parameters.get("sleep_seconds", 0.0)
    if isinstance(raw_sleep_seconds, bool) or not isinstance(raw_sleep_seconds, (int, float)):
        raise RuntimeError("Synthetic sleep_seconds must be numeric")
    sleep_seconds = float(raw_sleep_seconds)
    absent_environment_key = request.parameters.get("assert_environment_absent")
    if absent_environment_key is not None:
        if not isinstance(absent_environment_key, str) or not absent_environment_key:
            raise RuntimeError("assert_environment_absent must be a non-empty string")
        if absent_environment_key in os.environ:
            raise RuntimeError("Synthetic worker inherited a forbidden environment value")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    if mode == "crash":
        os._exit(70)
    if mode == "hang":
        time.sleep(max(request.limits.timeout_seconds * 5, 2.0))
    if mode == "invalid_manifest":
        result_path.write_text('{"contract":"invalid"}', encoding="utf-8")
        return 0

    started_at = datetime.now(timezone.utc)
    artifacts: tuple[ProcessorArtifact, ...] = ()
    if mode in {"success", "hash_mismatch"}:
        artifact_text = str(request.parameters.get("artifact_text", "synthetic output"))
        artifact_bytes = artifact_text.encode("utf-8")
        artifact_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"varta:{processing_run_id}:{request.sha256}:synthetic-text",
            )
        )
        relative_path = f"artifacts/{artifact_id}.txt"
        artifact_path = write_root / "artifacts" / f"{artifact_id}.txt"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(artifact_bytes)
        digest = hashlib.sha256(artifact_bytes).hexdigest()
        if mode == "hash_mismatch":
            digest = "0" * 64
        artifacts = (
            ProcessorArtifact(
                artifact_id=artifact_id,
                role="synthetic_text",
                relative_path=relative_path,
                sha256=digest,
                size_bytes=len(artifact_bytes),
                media_type="text/plain",
                source_file_ids=request.input_ids,
            ),
        )

    completed_at = datetime.now(timezone.utc)
    if mode == "fail" or (mode == "fail_once" and attempt == 1):
        error = ProcessorError(
            "synthetic_failure",
            "Synthetic processor failed by explicit test parameter",
            True,
        )
        result = ProcessorResult(
            processing_run_id=processing_run_id,
            status=JobStatus.FAILED,
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
            artifacts=(),
            findings=(),
            confidence=None,
            error=error,
        ).seal()
    else:
        result = synthetic_reference_processor(
            request,
            processing_run_id,
            started_at=started_at,
            completed_at=completed_at,
            artifacts=artifacts,
        )
    if mode == "manifest_digest_mismatch":
        payload = result.to_dict()
        payload["manifest_sha256"] = "0" * 64
        result_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    else:
        _write_result(result_path, result)
    print(
        json.dumps(
            {"processing_run_id": processing_run_id, "status": result.status.value},
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VARTA synthetic processor worker")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--capabilities", action="store_true")
    args = parser.parse_args(argv)
    if args.capabilities:
        print(json.dumps(capabilities(), sort_keys=True))
        return 0
    if args.request is None:
        parser.error("--request is required unless --capabilities is used")
    return run(args.request)


def _write_result(path: Path, result: ProcessorResult) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(result.to_json())
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - exercised through subprocess
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
