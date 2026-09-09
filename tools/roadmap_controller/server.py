from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse


APP_NAME = "VARTA Roadmap Controller"
APP_VERSION = "0.5.0"
CANONICAL_REPOSITORY_VISIBILITY = "PUBLIC"
STATE_SCHEMA_VERSION = 1
DEFAULT_EXECUTION_MODEL = "gpt-5.6-sol"
LATEST_EXECUTION_MODEL = "gpt-6-astra"
DEFAULT_REASONING_EFFORT = "high"
GIT_EXECUTION_MODEL = "gpt-5.4-mini"
GIT_REASONING_EFFORT = "high"
DISALLOWED_QUALITY_PROFILES = frozenset({("gpt-5.6-luna", "low")})
EXECUTION_MODEL_OPTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": LATEST_EXECUTION_MODEL,
        "label": "GPT-6 Astra · остання",
        "efforts": ("low", "medium", "high", "xhigh", "max", "ultra"),
    },
    {
        "id": "gpt-5.6-sol",
        "label": "Sol 5.6",
        "efforts": ("low", "medium", "high", "xhigh", "max", "ultra"),
    },
    {
        "id": "gpt-5.6-terra",
        "label": "Terra 5.6",
        "efforts": ("low", "medium", "high", "xhigh", "max", "ultra"),
    },
    {
        "id": "gpt-5.6-luna",
        "label": "Luna 5.6",
        "efforts": ("low", "medium", "high", "xhigh", "max"),
    },
    {
        "id": "gpt-5.5",
        "label": "GPT-5.5",
        "efforts": ("low", "medium", "high", "xhigh"),
    },
    {
        "id": "gpt-5.4",
        "label": "GPT-5.4",
        "efforts": ("low", "medium", "high", "xhigh"),
    },
    {
        "id": "gpt-5.4-mini",
        "label": "GPT-5.4 mini",
        "efforts": ("low", "medium", "high", "xhigh"),
    },
)
EXECUTION_MODEL_EFFORTS = {
    str(option["id"]): frozenset(str(value) for value in option["efforts"])
    for option in EXECUTION_MODEL_OPTIONS
}
ACTIVE_STATUSES = frozenset({"starting", "running", "waiting"})
TERMINAL_STATUSES = frozenset(
    {"completed", "blocked", "failed", "interrupted", "needs_review"}
)
TECHNICAL_RECHECK_GIT_STATUSES = frozenset({"blocked", "needs_review"})
RESULT_PATTERN = re.compile(
    r"<VARTA_STAGE_RESULT>\s*(\{.*?\})\s*</VARTA_STAGE_RESULT>",
    re.DOTALL,
)
GIT_RESULT_PATTERN = re.compile(
    r"<VARTA_GIT_RESULT>\s*(\{.*?\})\s*</VARTA_GIT_RESULT>",
    re.DOTALL,
)
REVIEW_RESULT_PATTERN = re.compile(
    r"<VARTA_REVIEW_RESULT>\s*(\{.*?\})\s*</VARTA_REVIEW_RESULT>",
    re.DOTALL,
)
CHECKPOINT_PATTERN = re.compile(
    r"<VARTA_CHECKPOINT>\s*(\{.*?\})\s*</VARTA_CHECKPOINT>",
    re.DOTALL,
)
PROGRESS_PATTERN = re.compile(
    r"<VARTA_PROGRESS>\s*(\{.*?\})\s*</VARTA_PROGRESS>",
    re.DOTALL,
)
WINDOWS_RUNTIME_FILES = (
    "codex.exe",
    "codex-code-mode-host.exe",
    "codex-command-runner.exe",
    "codex-windows-sandbox-setup.exe",
)


def is_active_writer_conflict(value: object) -> bool:
    """Return whether Codex rejected a resume because another client owns it."""

    return "already has an active writer" in str(value).casefold()


def active_writer_retry_notice(thread_id: object) -> str:
    short_id = str(thread_id)[:8] if thread_id else "невідомий"
    return (
        f"Канонічний task {short_id}… уже відкритий іншим Codex Desktop writer. "
        "Другий writer не створено, TECH PASS збережено. Повністю завершіть "
        "попередній Codex Desktop session, після чого повторіть Git checkpoint."
    )


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_catalog(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        raise ValueError("Unsupported roadmap catalog schema")
    raw_stages = payload.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise ValueError("Roadmap catalog has no stages")

    stages: list[dict[str, Any]] = []
    known_ids: set[str] = set()
    for raw in raw_stages:
        if not isinstance(raw, dict):
            raise ValueError("Every roadmap stage must be an object")
        stage = copy.deepcopy(raw)
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not re.fullmatch(r"[CPR]\d{2}", stage_id):
            raise ValueError(f"Invalid roadmap stage id: {stage_id!r}")
        if stage_id in known_ids:
            raise ValueError(f"Duplicate roadmap stage id: {stage_id}")
        for key in ("title", "topic", "planningStatus", "prompt", "group"):
            if not isinstance(stage.get(key), str) or not stage[key].strip():
                raise ValueError(f"Stage {stage_id} has invalid {key}")
        dependencies = stage.get("dependencies")
        if not isinstance(dependencies, list) or not all(
            isinstance(item, str) for item in dependencies
        ):
            raise ValueError(f"Stage {stage_id} has invalid dependencies")
        if not isinstance(stage.get("order"), int):
            raise ValueError(f"Stage {stage_id} has invalid order")
        known_ids.add(stage_id)
        stages.append(stage)

    for stage in stages:
        unknown = sorted(set(stage["dependencies"]) - known_ids)
        if unknown:
            raise ValueError(f"Stage {stage['id']} has unknown dependencies: {unknown}")
        if stage["id"] in stage["dependencies"]:
            raise ValueError(f"Stage {stage['id']} depends on itself")
    return sorted(stages, key=lambda item: item["order"])


def _limited_string(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def default_codex_sessions_root() -> Path:
    configured_root = os.environ.get("CODEX_HOME")
    codex_root = Path(configured_root) if configured_root else Path.home() / ".codex"
    return codex_root / "sessions"


def load_session_execution_settings(
    sessions_root: Path,
    thread_ids: set[str],
) -> dict[tuple[str, str], dict[str, str]]:
    """Read actual model metadata for known Codex turns from local sessions."""

    settings: dict[tuple[str, str], dict[str, str]] = {}
    if not thread_ids or not sessions_root.is_dir():
        return settings
    for path in sessions_root.rglob("*.jsonl"):
        thread_id = next(
            (candidate for candidate in thread_ids if path.stem.endswith(candidate)),
            None,
        )
        if thread_id is None:
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict) or record.get("type") != "turn_context":
                        continue
                    payload = record.get("payload")
                    if not isinstance(payload, dict):
                        continue
                    turn_id = _limited_string(payload.get("turn_id"), limit=100)
                    model = _limited_string(payload.get("model"), limit=100)
                    effort = _limited_string(payload.get("effort"), limit=40)
                    if turn_id and model and effort:
                        settings[(thread_id, turn_id)] = {
                            "model": model,
                            "reasoningEffort": effort,
                        }
        except OSError:
            continue
    return settings


def parse_progress_update(
    text: str,
    expected_stage_id: str,
    expected_kind: str,
) -> dict[str, Any] | None:
    """Return the latest complete, stage-scoped progress marker.

    Progress is reported by the active Codex turn at evidence-backed milestones.
    It is deliberately not inferred from elapsed time or tool-call counts.
    """

    matches = list(PROGRESS_PATTERN.finditer(text or ""))
    if not matches:
        return None
    try:
        raw = json.loads(matches[-1].group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("stage_id") != expected_stage_id or raw.get("kind") != expected_kind:
        return None
    percent = raw.get("percent")
    if not isinstance(percent, int) or isinstance(percent, bool) or not 1 <= percent <= 99:
        return None
    phase = _limited_string(raw.get("phase"), limit=160)
    detail = _limited_string(raw.get("detail"), limit=1200)
    if not phase or not detail:
        return None
    return {
        "percent": percent,
        "phase": phase,
        "detail": detail,
        "source": "reported",
    }


def _blank_progress() -> dict[str, Any]:
    return {
        "percent": 0,
        "phase": "Не розпочато",
        "detail": "Пакет ще не запускався.",
        "source": "lifecycle",
        "updatedAt": None,
        "events": [],
    }


def _normalise_progress(value: Any) -> dict[str, Any]:
    progress = _blank_progress()
    if isinstance(value, dict):
        progress.update(value)
    percent = progress.get("percent")
    if not isinstance(percent, int) or isinstance(percent, bool):
        percent = 0
    progress["percent"] = max(0, min(100, percent))
    progress["phase"] = _limited_string(progress.get("phase"), limit=160) or "Немає даних"
    progress["detail"] = (
        _limited_string(progress.get("detail"), limit=1200)
        or "Детальний progress checkpoint ще не отримано."
    )
    if progress.get("source") not in {"lifecycle", "reported", "controller"}:
        progress["source"] = "lifecycle"
    if not isinstance(progress.get("events"), list):
        progress["events"] = []
    progress["events"] = [
        copy.deepcopy(item)
        for item in progress["events"][-40:]
        if isinstance(item, dict)
    ]
    return progress


def _set_progress(
    progress: dict[str, Any],
    *,
    percent: int,
    phase: str,
    detail: str,
    source: str,
    timestamp: str | None = None,
    allow_regression: bool = False,
) -> bool:
    """Update a progress record and append a de-duplicated process event."""

    current = progress.get("percent", 0)
    current_percent = current if isinstance(current, int) and not isinstance(current, bool) else 0
    bounded = max(0, min(100, percent))
    if not allow_regression and bounded < current_percent:
        return False
    clean_phase = _limited_string(phase, limit=160)
    clean_detail = _limited_string(detail, limit=1200)
    if not clean_phase or not clean_detail:
        return False
    if source not in {"lifecycle", "reported", "controller"}:
        return False
    if (
        bounded == current_percent
        and progress.get("phase") == clean_phase
        and progress.get("detail") == clean_detail
        and progress.get("source") == source
    ):
        return False
    event_at = timestamp or utc_now()
    progress.update(
        {
            "percent": bounded,
            "phase": clean_phase,
            "detail": clean_detail,
            "source": source,
            "updatedAt": event_at,
        }
    )
    events = progress.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        progress["events"] = events
    event = {
        "percent": bounded,
        "phase": clean_phase,
        "detail": clean_detail,
        "source": source,
        "at": event_at,
    }
    if not events or events[-1] != event:
        events.append(event)
        del events[:-40]
    return True


def _parse_machine_json_object(payload: str) -> dict[str, Any] | None:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        # A model may occasionally leave one trailing comma or stray quote before
        # the final brace. Repair only that exact terminal defect; all semantic
        # validation and live Git verification still run afterwards.
        repaired, substitutions = re.subn(
            r",\s*(?:\"\s*)?}\s*$",
            "}",
            payload,
            count=1,
        )
        if substitutions != 1:
            return None
        try:
            raw = json.loads(repaired)
        except json.JSONDecodeError:
            return None
    return raw if isinstance(raw, dict) else None


def parse_stage_result(text: str, expected_stage_id: str) -> dict[str, Any] | None:
    matches = list(RESULT_PATTERN.finditer(text or ""))
    if not matches:
        return None
    raw = _parse_machine_json_object(matches[-1].group(1))
    if raw is None or raw.get("stage_id") != expected_stage_id:
        return None

    outcome = raw.get("outcome")
    if outcome not in {"passed", "blocked", "failed"}:
        return None
    summary = _limited_string(raw.get("summary"), limit=4000)
    gate = _limited_string(raw.get("gate"), limit=4000)
    if not summary or not gate:
        return None

    tests_raw = raw.get("tests", [])
    if not isinstance(tests_raw, list) or len(tests_raw) > 100:
        return None
    tests: list[dict[str, str]] = []
    for item in tests_raw:
        if not isinstance(item, dict):
            return None
        name = _limited_string(item.get("name"), limit=500)
        status = item.get("status")
        evidence = _limited_string(item.get("evidence"), limit=2000)
        if not name or status not in {"passed", "failed", "not_run", "not_applicable"}:
            return None
        tests.append({"name": name, "status": status, "evidence": evidence})

    if outcome == "passed":
        if not tests or any(item["status"] in {"failed", "not_run"} for item in tests):
            return None

    changed_raw = raw.get("changed_files", [])
    if not isinstance(changed_raw, list) or len(changed_raw) > 200:
        return None
    changed_files: list[str] = []
    for item in changed_raw:
        value = _limited_string(item, limit=1000)
        if not value:
            return None
        changed_files.append(value)

    return {
        "stage_id": expected_stage_id,
        "outcome": outcome,
        "summary": summary,
        "tests": tests,
        "changed_files": changed_files,
        "gate": gate,
        "next_stage": _limited_string(raw.get("next_stage"), limit=20),
    }


def parse_git_checkpoint_result(
    text: str, expected_stage_id: str
) -> dict[str, Any] | None:
    matches = list(GIT_RESULT_PATTERN.finditer(text or ""))
    if not matches:
        return None
    raw = _parse_machine_json_object(matches[-1].group(1))
    if raw is None or raw.get("stage_id") != expected_stage_id:
        return None

    outcome = raw.get("outcome")
    if outcome not in {"synced", "blocked", "failed"}:
        return None
    summary = _limited_string(raw.get("summary"), limit=4000)
    gate = _limited_string(raw.get("gate"), limit=4000)
    if not summary or not gate:
        return None

    checks_raw = raw.get("checks", [])
    if not isinstance(checks_raw, list) or len(checks_raw) > 100:
        return None
    checks: list[dict[str, str]] = []
    for item in checks_raw:
        if not isinstance(item, dict):
            return None
        name = _limited_string(item.get("name"), limit=500)
        status = item.get("status")
        evidence = _limited_string(item.get("evidence"), limit=2000)
        if not name or status not in {"passed", "failed", "not_run", "not_applicable"}:
            return None
        checks.append({"name": name, "status": status, "evidence": evidence})

    staged_raw = raw.get("staged_files", [])
    if not isinstance(staged_raw, list) or len(staged_raw) > 300:
        return None
    staged_files: list[str] = []
    for item in staged_raw:
        value = _limited_string(item, limit=1000)
        if not value:
            return None
        staged_files.append(value)

    branch = _limited_string(raw.get("branch"), limit=300)
    commit = _limited_string(raw.get("commit"), limit=40)
    remote = _limited_string(raw.get("remote"), limit=100)
    pr_url = _limited_string(raw.get("pr_url"), limit=1000)
    visibility = _limited_string(raw.get("visibility"), limit=20).upper()
    pushed = raw.get("pushed") is True
    commit_created = raw.get("commit_created") is True

    if outcome == "synced":
        if not checks or any(item["status"] in {"failed", "not_run"} for item in checks):
            return None
        if (
            not re.fullmatch(r"codex/[A-Za-z0-9][A-Za-z0-9._/-]*", branch)
            or ".." in branch
            or "//" in branch
            or branch.endswith(("/", "."))
        ):
            return None
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
            return None
        if (
            remote != "origin"
            or not pushed
            or visibility != CANONICAL_REPOSITORY_VISIBILITY
        ):
            return None
        if not re.fullmatch(
            r"https://github\.com/mixa4y/varta/pull/\d+", pr_url, re.IGNORECASE
        ):
            return None

    return {
        "stage_id": expected_stage_id,
        "outcome": outcome,
        "summary": summary,
        "checks": checks,
        "staged_files": staged_files,
        "branch": branch,
        "commit": commit,
        "commit_created": commit_created,
        "remote": remote,
        "pushed": pushed,
        "visibility": visibility,
        "pr_url": pr_url,
        "gate": gate,
    }


def parse_review_result(text: str, expected_stage_id: str) -> dict[str, Any] | None:
    matches = list(REVIEW_RESULT_PATTERN.finditer(text or ""))
    if not matches:
        return None
    raw = _parse_machine_json_object(matches[-1].group(1))
    if raw is None or raw.get("stage_id") != expected_stage_id:
        return None
    outcome = raw.get("outcome")
    if outcome not in {"passed", "blocked", "failed"}:
        return None
    summary = _limited_string(raw.get("summary"), limit=4000)
    contract = _limited_string(raw.get("contract"), limit=4000)
    required_gates = raw.get("required_gates")
    inputs = raw.get("inputs")
    if not summary or not contract:
        return None
    if not isinstance(required_gates, list) or not required_gates or len(required_gates) > 100:
        return None
    if not isinstance(inputs, list) or not inputs or len(inputs) > 200:
        return None
    clean_gates = [_limited_string(item, limit=500) for item in required_gates]
    clean_inputs = [_limited_string(item, limit=1000) for item in inputs]
    if not all(clean_gates) or not all(clean_inputs):
        return None
    return {
        "stage_id": expected_stage_id,
        "outcome": outcome,
        "summary": summary,
        "contract": contract,
        "required_gates": clean_gates,
        "inputs": clean_inputs,
    }


def parse_checkpoint_updates(
    text: str, expected_stage_id: str, expected_kind: str
) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for match in CHECKPOINT_PATTERN.finditer(text or ""):
        raw = _parse_machine_json_object(match.group(1))
        if raw is None:
            continue
        if raw.get("stage_id") != expected_stage_id or raw.get("kind") != expected_kind:
            continue
        step_id = _limited_string(raw.get("step_id"), limit=80)
        status = raw.get("status")
        summary = _limited_string(raw.get("summary"), limit=2000)
        command = _limited_string(raw.get("command"), limit=4000)
        next_step = _limited_string(raw.get("next_step"), limit=500)
        inputs = raw.get("inputs")
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", step_id)
            or status not in {"running", "passed", "failed", "interrupted", "invalidated"}
            or not summary
            or not isinstance(inputs, list)
            or len(inputs) > 200
        ):
            continue
        clean_inputs = [_limited_string(item, limit=1000).replace("\\", "/") for item in inputs]
        if any(not item or item.startswith(("/", "../")) or "/../" in item for item in clean_inputs):
            continue
        updates.append(
            {
                "stepId": step_id,
                "kind": expected_kind,
                "status": status,
                "summary": summary,
                "command": command,
                "inputs": clean_inputs,
                "nextStep": next_step,
            }
        )
    return updates


def _path_fingerprint(root: Path, relative_path: str) -> str | None:
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    digest = hashlib.sha256()
    if target.is_file():
        digest.update(target.read_bytes())
        return digest.hexdigest()
    if target.is_dir():
        for child in sorted(item for item in target.rglob("*") if item.is_file()):
            rel = child.relative_to(target).as_posix().encode("utf-8")
            digest.update(len(rel).to_bytes(4, "big"))
            digest.update(rel)
            digest.update(child.read_bytes())
        return digest.hexdigest()
    return None


def fingerprint_inputs(root: Path, inputs: list[str]) -> dict[str, str] | None:
    fingerprints: dict[str, str] = {}
    for relative_path in inputs:
        normalized = relative_path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized == ".varta/roadmap-controller" or normalized.startswith(
            ".varta/roadmap-controller/"
        ):
            # Controller state and rendered checkpoint reports change while a
            # checkpoint is being recorded. Fingerprinting them would make a
            # successful checkpoint invalidate itself during finalization.
            return None
        value = _path_fingerprint(root, relative_path)
        if value is None:
            return None
        fingerprints[relative_path] = value
    return fingerprints


def verify_checkpoint_scope(
    root: Path,
    stage_id: str,
    result: Mapping[str, Any],
    stage_result: Mapping[str, Any] | None,
) -> tuple[bool, str]:
    """Fail closed on commit scope, protected ownership and obvious private artifacts."""

    expected = set(stage_result.get("changed_files", [])) if isinstance(stage_result, Mapping) else set()
    staged = set(result.get("staged_files", []))
    commit = str(result.get("commit", ""))
    scope_paths = staged
    try:
        if result.get("commit_created"):
            if staged != expected:
                return False, "Git manifest не збігається з exact changed_files технічного PASS."
            committed = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            ).stdout.splitlines()
            if set(committed) != staged:
                return False, "Commit manifest не збігається зі staged_files."
        elif staged:
            return False, "Git result декларує staged files без створення commit."
        elif expected:
            committed = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            ).stdout.splitlines()
            if set(committed) != expected:
                return False, "Existing commit manifest не збігається з exact changed_files технічного PASS."
            scope_paths = set(committed)
        ownership_path = root / "config" / "file-ownership.json"
        ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
        exact = {item["path"]: item for item in ownership.get("exactPaths", [])}
        for path in scope_paths:
            entry = exact.get(path)
            if entry:
                package_owners = {owner for owner in entry.get("owners", []) if re.fullmatch(r"[CPR]\d{2}", owner)}
                if package_owners and stage_id not in package_owners:
                    return False, f"Ownership registry відносить {path} до іншого package."
            lowered = path.casefold()
            if lowered.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".p7s", ".db", ".sqlite", ".sqlite3", ".rar", ".7z")):
                return False, f"Заборонений тип файла у commit: {path}."
            blob = subprocess.run(
                ["git", "show", f"{commit}:{path}"],
                cwd=root,
                capture_output=True,
                check=True,
            ).stdout
            if b"\x00" in blob[:8192]:
                return False, f"Binary blob не дозволений автоматичним privacy gate: {path}."
            text = blob.decode("utf-8", errors="ignore")
            if re.search(r"(?:sk-proj-|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)", text):
                return False, f"Secret/private-key pattern знайдено у {path}."
            if re.search(r"(?i)(?:C:\\Users\\[^\\\s]+|/home/[^/\s]+)", text):
                return False, f"User-specific path знайдено у {path}."
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as exc:
        return False, f"Automated ownership/privacy verification failed: {exc}"
    return True, "Controller підтвердив exact commit scope, ownership registry і privacy boundary."


class StateStore:
    def __init__(self, path: Path, stage_ids: list[str]) -> None:
        self.path = path
        self.stage_ids = stage_ids
        self._lock = threading.RLock()
        self._state = self._load()

    @staticmethod
    def _blank_git_checkpoint() -> dict[str, Any]:
        return {
            "status": "not_ready",
            "attempt": 0,
            "threadId": None,
            "turnId": None,
            "model": None,
            "reasoningEffort": None,
            "executionSource": "unknown",
            "startedAt": None,
            "updatedAt": None,
            "completedAt": None,
            "lastMessage": "",
            "result": None,
            "error": None,
            "retryNotice": None,
            "history": [],
            "progress": _blank_progress(),
        }

    @staticmethod
    def _blank_contract_review() -> dict[str, Any]:
        return {
            "status": "not_started",
            "attempt": 0,
            "turnId": None,
            "startedAt": None,
            "updatedAt": None,
            "completedAt": None,
            "result": None,
            "error": None,
            "lastMessage": "",
        }

    @staticmethod
    def _blank_stage() -> dict[str, Any]:
        return {
            "seriesId": None,
            "seriesStartedAt": None,
            "runStatus": "not_started",
            "attempt": 0,
            "threadId": None,
            "turnId": None,
            "model": None,
            "reasoningEffort": None,
            "executionSource": "unknown",
            "startedAt": None,
            "updatedAt": None,
            "completedAt": None,
            "lastMessage": "",
            "result": None,
            "error": None,
            "history": [],
            "gitBaseline": None,
            "progress": _blank_progress(),
            "checkpoints": [],
            "contractReview": StateStore._blank_contract_review(),
            "git": StateStore._blank_git_checkpoint(),
        }

    def _load(self) -> dict[str, Any]:
        state: dict[str, Any]
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or loaded.get("schemaVersion") != STATE_SCHEMA_VERSION:
                raise ValueError("Unsupported roadmap runtime-state schema")
            state = loaded
        else:
            state = {
                "schemaVersion": STATE_SCHEMA_VERSION,
                "updatedAt": utc_now(),
                "stages": {},
            }
        raw_stages = state.setdefault("stages", {})
        if not isinstance(raw_stages, dict):
            raise ValueError("Roadmap runtime state has invalid stages")
        for stage_id in self.stage_ids:
            existing = raw_stages.get(stage_id)
            if not isinstance(existing, dict):
                raw_stages[stage_id] = self._blank_stage()
                continue
            blank = self._blank_stage()
            blank.update(existing)
            if not isinstance(blank.get("history"), list):
                blank["history"] = []
            known_starts = [
                value
                for value in (
                    blank.get("startedAt"),
                    *(entry.get("startedAt") for entry in blank["history"] if isinstance(entry, dict)),
                )
                if isinstance(value, str) and value
            ]
            if known_starts:
                earliest_start = min(known_starts)
                if not isinstance(blank.get("seriesStartedAt"), str) or earliest_start < blank["seriesStartedAt"]:
                    blank["seriesStartedAt"] = earliest_start
                    blank["seriesId"] = f"{stage_id}-{earliest_start}"
            if not isinstance(blank.get("checkpoints"), list):
                blank["checkpoints"] = []
            had_review = isinstance(existing.get("contractReview"), dict)
            review = self._blank_contract_review()
            if isinstance(blank.get("contractReview"), dict):
                review.update(blank["contractReview"])
            if not had_review and blank.get("runStatus") == "completed":
                review.update(
                    {
                        "status": "legacy_passed",
                        "completedAt": blank.get("completedAt"),
                        "lastMessage": "Historical completed package migrated without retroactive review.",
                    }
                )
            blank["contractReview"] = review
            blank["progress"] = _normalise_progress(blank.get("progress"))
            if (
                blank.get("runStatus") == "completed"
                and blank["progress"].get("percent", 0) < 100
            ):
                _set_progress(
                    blank["progress"],
                    percent=100,
                    phase="TECH PASS",
                    detail="Legacy state підтверджує завершений package.",
                    source="controller",
                    timestamp=blank.get("completedAt") or blank.get("updatedAt"),
                )
            git_checkpoint = self._blank_git_checkpoint()
            existing_git = blank.get("git")
            if isinstance(existing_git, dict):
                git_checkpoint.update(existing_git)
            if not isinstance(git_checkpoint.get("history"), list):
                git_checkpoint["history"] = []
            git_checkpoint["progress"] = _normalise_progress(
                git_checkpoint.get("progress")
            )
            if (
                git_checkpoint.get("status") == "synced"
                and git_checkpoint["progress"].get("percent", 0) < 100
            ):
                _set_progress(
                    git_checkpoint["progress"],
                    percent=100,
                    phase="GITHUB SYNCED",
                    detail="Legacy state підтверджує синхронізований Git checkpoint.",
                    source="controller",
                    timestamp=(
                        git_checkpoint.get("completedAt")
                        or git_checkpoint.get("updatedAt")
                    ),
                )
            blank["git"] = git_checkpoint
            raw_stages[stage_id] = blank
        for stale_id in set(raw_stages) - set(self.stage_ids):
            del raw_stages[stale_id]
        return state

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def stage(self, stage_id: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state["stages"][stage_id])

    def update_stage(
        self,
        stage_id: str,
        updater: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        with self._lock:
            updater(self._state["stages"][stage_id])
            self._state["updatedAt"] = utc_now()
            self._write_locked()
            return copy.deepcopy(self._state["stages"][stage_id])

    def interrupt_stale_active_runs(self) -> None:
        changed = False
        with self._lock:
            for stage in self._state["stages"].values():
                if stage.get("runStatus") in ACTIVE_STATUSES:
                    stage["runStatus"] = "interrupted"
                    stage["completedAt"] = utc_now()
                    stage["updatedAt"] = stage["completedAt"]
                    stage["error"] = (
                        "Контролер було перезапущено під час активного turn; "
                        "перевірте task у Codex перед повторним запуском."
                    )
                    progress = _normalise_progress(stage.get("progress"))
                    _set_progress(
                        progress,
                        percent=int(progress["percent"]),
                        phase="Виконання перервано",
                        detail=stage["error"],
                        source="controller",
                        timestamp=stage["updatedAt"],
                    )
                    stage["progress"] = progress
                    changed = True
                review = stage.get("contractReview")
                if isinstance(review, dict) and review.get("status") in ACTIVE_STATUSES:
                    review["status"] = "interrupted"
                    review["completedAt"] = utc_now()
                    review["updatedAt"] = review["completedAt"]
                    review["error"] = (
                        "Контролер було перезапущено під час contract review; "
                        "огляд не вважається пройденим."
                    )
                    review["lastMessage"] = "Contract review перервано перезапуском."
                    changed = True
                git_checkpoint = stage.get("git")
                if (
                    isinstance(git_checkpoint, dict)
                    and git_checkpoint.get("status") in ACTIVE_STATUSES
                ):
                    git_checkpoint["status"] = "interrupted"
                    git_checkpoint["completedAt"] = utc_now()
                    git_checkpoint["updatedAt"] = git_checkpoint["completedAt"]
                    git_checkpoint["error"] = (
                        "Контролер було перезапущено під час GitHub checkpoint; "
                        "перевірте task і Git state перед повторним запуском."
                    )
                    progress = _normalise_progress(git_checkpoint.get("progress"))
                    _set_progress(
                        progress,
                        percent=int(progress["percent"]),
                        phase="Git checkpoint перервано",
                        detail=git_checkpoint["error"],
                        source="controller",
                        timestamp=git_checkpoint["updatedAt"],
                    )
                    git_checkpoint["progress"] = progress
                    changed = True
            if changed:
                self._state["updatedAt"] = utc_now()
                self._write_locked()

    def recover_retryable_writer_conflicts(
        self,
        stage_id: str | None = None,
        *,
        error_message: str | None = None,
    ) -> list[str]:
        """Preserve TECH PASS when a Git turn never acquired the canonical task."""

        recovered: list[str] = []
        with self._lock:
            stage_ids = [stage_id] if stage_id is not None else self.stage_ids
            for candidate_id in stage_ids:
                run = self._state["stages"].get(candidate_id)
                if not isinstance(run, dict) or run.get("runStatus") != "completed":
                    continue
                checkpoint = run.get("git")
                if not isinstance(checkpoint, dict):
                    continue
                conflict = error_message if stage_id == candidate_id else checkpoint.get("error")
                if (
                    checkpoint.get("status") not in {"starting", "failed"}
                    or checkpoint.get("turnId")
                    or not is_active_writer_conflict(conflict)
                ):
                    continue

                now = utc_now()
                failed_progress = _normalise_progress(checkpoint.get("progress"))
                _set_progress(
                    failed_progress,
                    percent=int(failed_progress.get("percent", 5)),
                    phase="Git checkpoint не отримав writer",
                    detail=str(conflict),
                    source="controller",
                    timestamp=now,
                )
                history_entry = {
                    key: copy.deepcopy(checkpoint.get(key))
                    for key in (
                        "attempt",
                        "status",
                        "threadId",
                        "turnId",
                        "model",
                        "reasoningEffort",
                        "executionSource",
                        "startedAt",
                        "completedAt",
                        "result",
                        "error",
                        "progress",
                    )
                }
                history_entry.update(
                    {
                        "status": "failed",
                        "completedAt": checkpoint.get("completedAt") or now,
                        "error": str(conflict),
                        "progress": failed_progress,
                    }
                )
                history = checkpoint.get("history")
                preserved_history = copy.deepcopy(history) if isinstance(history, list) else []
                preserved_history.append(history_entry)

                notice = active_writer_retry_notice(
                    checkpoint.get("threadId") or run.get("threadId")
                )
                ready_progress = _blank_progress()
                _set_progress(
                    ready_progress,
                    percent=0,
                    phase="Очікує повторного Git checkpoint",
                    detail=notice,
                    source="controller",
                    timestamp=now,
                )
                checkpoint.update(
                    {
                        "status": "awaiting_approval",
                        "turnId": None,
                        "startedAt": None,
                        "updatedAt": now,
                        "completedAt": None,
                        "lastMessage": notice,
                        "result": None,
                        "error": None,
                        "retryNotice": notice,
                        "history": preserved_history[-20:],
                        "progress": ready_progress,
                    }
                )
                recovered.append(candidate_id)
            if recovered:
                self._state["updatedAt"] = utc_now()
                self._write_locked()
        return recovered

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        payload = json.dumps(self._state, ensure_ascii=False, indent=2) + "\n"
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)


class AppServerClient(Protocol):
    authenticated: bool

    def start(self) -> None: ...

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...


class AppServerError(RuntimeError):
    pass


def _executable_works(candidate: Path) -> bool:
    try:
        result = subprocess.run(
            [str(candidate), "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def stage_windows_runtime(source_exe: Path, runtime_root: Path) -> Path:
    source_dir = source_exe.parent
    missing = [name for name in WINDOWS_RUNTIME_FILES if not (source_dir / name).is_file()]
    if missing:
        raise AppServerError(f"Bundled Codex runtime is incomplete: {', '.join(missing)}")
    fingerprint_material = "|".join(
        f"{name}:{(source_dir / name).stat().st_size}:{(source_dir / name).stat().st_mtime_ns}"
        for name in WINDOWS_RUNTIME_FILES
    )
    fingerprint = hashlib.sha256(fingerprint_material.encode("utf-8")).hexdigest()[:16]
    target_dir = runtime_root / fingerprint
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in WINDOWS_RUNTIME_FILES:
        source = source_dir / name
        target = target_dir / name
        if target.is_file() and target.stat().st_size == source.stat().st_size:
            continue
        temporary = target.with_name(f"{target.name}.{os.getpid()}.copying")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    executable = target_dir / "codex.exe"
    if not _executable_works(executable):
        raise AppServerError("Staged Codex executable cannot be started")
    return executable


def locate_codex_executable(runtime_root: Path) -> Path:
    candidates: list[Path] = []
    explicit = os.environ.get("VARTA_CODEX_EXE")
    if explicit:
        candidates.append(Path(explicit))
    discovered = shutil.which("codex")
    if discovered:
        candidates.append(Path(discovered))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen and candidate.is_file():
            seen.add(key)
            unique.append(candidate)
    for candidate in unique:
        if _executable_works(candidate):
            return candidate
    if os.name == "nt":
        for candidate in unique:
            if "windowsapps" in str(candidate).casefold() and candidate.name.casefold() == "codex.exe":
                return stage_windows_runtime(candidate, runtime_root)
    raise AppServerError(
        "Не знайдено доступний Codex CLI/App Server. Встановіть Codex CLI або "
        "задайте VARTA_CODEX_EXE."
    )


class CodexAppServer:
    def __init__(
        self,
        executable: Path,
        cwd: Path,
        log_path: Path,
        on_message: Callable[[dict[str, Any]], None],
    ) -> None:
        self.executable = executable
        self.cwd = cwd
        self.log_path = log_path
        self.on_message = on_message
        self.authenticated = False
        self._process: subprocess.Popen[str] | None = None
        self._stderr_handle: Any = None
        self._reader: threading.Thread | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._request_id = 0

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr_handle = self.log_path.open("a", encoding="utf-8")
        self._process = subprocess.Popen(
            [str(self.executable), "app-server"],
            cwd=str(self.cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_handle,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._reader = threading.Thread(
            target=self._reader_loop,
            name="varta-app-server-reader",
            daemon=True,
        )
        self._reader.start()
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "varta_roadmap_controller",
                    "title": APP_NAME,
                    "version": APP_VERSION,
                }
            },
            timeout=20,
        )
        self._write({"method": "initialized", "params": {}})
        account = self.request("account/read", {}, timeout=20).get("account")
        self.authenticated = isinstance(account, dict)
        if not self.authenticated:
            raise AppServerError("Codex App Server не має активної авторизації")

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        process = self._process
        if process is None or process.poll() is not None:
            raise AppServerError("Codex App Server is not running")
        with self._pending_lock:
            self._request_id += 1
            request_id = self._request_id
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        try:
            self._write({"method": method, "id": request_id, "params": dict(params or {})})
            try:
                response = response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise AppServerError(f"Timeout while calling {method}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        error = response.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = _limited_string(error.get("message"), limit=2000)
            raise AppServerError(f"{method} failed ({code}): {message}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise AppServerError(f"{method} returned an invalid response")
        return result

    def _write(self, message: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise AppServerError("Codex App Server input is unavailable")
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._write_lock:
            try:
                process.stdin.write(encoded)
                process.stdin.flush()
            except OSError as exc:
                raise AppServerError("Cannot write to Codex App Server") from exc

    def _reader_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in iter(process.stdout.readline, ""):
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            if isinstance(request_id, int) and "method" not in message:
                with self._pending_lock:
                    target = self._pending.get(request_id)
                if target is not None:
                    target.put(message)
                continue
            if isinstance(request_id, int) and isinstance(message.get("method"), str):
                try:
                    self._write(
                        {
                            "id": request_id,
                            "error": {
                                "code": -32002,
                                "message": (
                                    "Unattended roadmap tasks cannot pause for interactive "
                                    "client input; return a blocked stage result instead."
                                ),
                            },
                        }
                    )
                except AppServerError:
                    pass
            try:
                self.on_message(message)
            except Exception:
                continue
        failure = {"error": {"code": -32000, "message": "App Server stream closed"}}
        with self._pending_lock:
            pending = list(self._pending.values())
        for target in pending:
            try:
                target.put_nowait(failure)
            except queue.Full:
                pass

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is not None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if self._stderr_handle is not None:
            self._stderr_handle.close()
            self._stderr_handle = None


def capture_git_baseline(root: Path) -> dict[str, Any]:
    def read_git(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "git command failed"
            raise RoadmapConflict(_limited_string(message, limit=2000))
        return result.stdout

    head = read_git("rev-parse", "HEAD").strip()
    branch = read_git("branch", "--show-current").strip()
    raw_status = read_git("status", "--porcelain=v1", "-z")
    entries = [item for item in raw_status.split("\0") if item]
    if len(entries) > 2000:
        raise RoadmapConflict("Git working tree має понад 2000 status entries; потрібен ручний аудит.")
    return {
        "capturedAt": utc_now(),
        "head": head,
        "branch": branch,
        "status": entries,
        "statusSha256": hashlib.sha256(raw_status.encode("utf-8")).hexdigest(),
    }


def verify_git_checkpoint_result(
    root: Path, result: Mapping[str, Any]
) -> tuple[bool, str, str | None]:
    def read_command(arguments: list[str], *, timeout: float = 30.0) -> str:
        completed = subprocess.run(
            arguments,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(_limited_string(message, limit=1000) or "command failed")
        return completed.stdout.strip()

    try:
        branch = str(result["branch"])
        current_branch = read_command(["git", "branch", "--show-current"])
        if current_branch != branch:
            return False, "Поточна branch не збігається з VARTA_GIT_RESULT.", None

        local_commit = read_command(
            ["git", "rev-parse", f"{result['commit']}^{{commit}}"]
        ).lower()
        head = read_command(["git", "rev-parse", "HEAD"]).lower()
        if local_commit != head:
            return False, "Result commit не є поточним local HEAD.", None

        origin_url = read_command(["git", "remote", "get-url", "origin"])
        allowed_origin_urls = {
            "https://github.com/mixa4y/varta.git",
            "git@github.com:mixa4y/varta.git",
        }
        if origin_url not in allowed_origin_urls:
            return False, "origin не є canonical mixa4y/varta remote.", None

        remote_line = read_command(
            ["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"],
            timeout=40,
        )
        remote_commit = remote_line.split()[0].lower() if remote_line else ""
        if remote_commit != local_commit:
            return False, "origin branch не містить підтверджений local commit.", None

        repo_payload = json.loads(
            read_command(
                [
                    "gh",
                    "repo",
                    "view",
                    "mixa4y/varta",
                    "--json",
                    "nameWithOwner,visibility",
                ],
                timeout=40,
            )
        )
        if (
            repo_payload.get("nameWithOwner") != "mixa4y/varta"
            or str(repo_payload.get("visibility", "")).upper()
            != CANONICAL_REPOSITORY_VISIBILITY
        ):
            return False, "GitHub repository identity або visibility не підтверджено.", None

        pr_payload = json.loads(
            read_command(
                [
                    "gh",
                    "pr",
                    "view",
                    str(result["pr_url"]),
                    "--json",
                    "url,isDraft,state,headRefName,baseRefName,headRefOid",
                ],
                timeout=40,
            )
        )
        if (
            pr_payload.get("url") != result["pr_url"]
            or pr_payload.get("isDraft") is not True
            or pr_payload.get("state") != "OPEN"
            or pr_payload.get("headRefName") != branch
            or pr_payload.get("baseRefName") != "main"
            or str(pr_payload.get("headRefOid", "")).lower() != local_commit
        ):
            return False, "Draft PR metadata не відповідає branch/commit/base gate.", None
    except (KeyError, OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        message = _limited_string(str(exc), limit=1000) or type(exc).__name__
        return False, f"Live GitHub verification failed: {message}", None

    return (
        True,
        "Controller повторно підтвердив local HEAD, origin branch, PUBLIC repo і Draft PR.",
        local_commit,
    )


def build_contract_review_prompt(stage: Mapping[str, Any]) -> str:
    dependencies = ", ".join(stage["dependencies"]) or "немає"
    return f"""Виконай ранній contract review package {stage['id']} у його канонічному чаті.

Тема: {stage['topic']}
Залежності: {dependencies}
Завдання: {stage['prompt']}

Прочитай D:\\VARTA\\AGENTS.md, package у docs/chat-roadmap.md і чинні contracts,
schemas, migrations та tests, від яких він залежить. Не змінюй файли, не запускай
великі regression/browser/package suites і не виконуй Git операції. Встанови
точний scope, compatibility/privacy invariants, required gates та exact inputs.
Якщо контракт суперечливий або prerequisites не підтверджені, outcome=blocked.

У фінальній відповіді дай короткий звіт і рівно один блок:
<VARTA_REVIEW_RESULT>{{"stage_id":"{stage['id']}","outcome":"passed|blocked|failed","summary":"висновок","contract":"точний контракт реалізації та сумісності","required_gates":["gate"],"inputs":["repo/relative/path"]}}</VARTA_REVIEW_RESULT>
"""


def build_task_prompt(
    stage: Mapping[str, Any],
    git_baseline: Mapping[str, Any] | None = None,
    *,
    technical_recheck: bool = False,
    manual_rerun: bool = False,
    quality_recheck: bool = False,
    resume_from_checkpoint: bool = False,
) -> str:
    dependencies = ", ".join(stage["dependencies"]) or "немає"
    baseline = json.dumps(git_baseline or {}, ensure_ascii=False, indent=2)
    if resume_from_checkpoint:
        mode_instructions = f"""
Режим цього turn: продовження з локального checkpoint після interrupted,
failed або needs_review. Спочатку прочитай
`.varta/roadmap-controller/checkpoints/{stage['id']}.md` і поточний controller
error. Почни з першого invalidated/failed/unfinished step. Не повторюй passed
кроки з незмінними fingerprints. Після виправлення або нового доказу повторно
надішли VARTA_CHECKPOINT для кожного зачепленого step_id, щоб controller
зафіксував актуальні fingerprints. Це той самий package і той самий чат.
"""
    elif quality_recheck:
        mode_instructions = """
Режим цього turn: обов'язковий професійний перепрогін. Попередній TECH PASS
виконано профілем Luna з effort=low, тому controller визнав його недостатнім
для transition gate. Це продовження того самого package, а не новий package.
Повторно перевір повний contract, реалізацію, актуальні tests, typing/formatting,
privacy та exact diff. Не покладайся на старий зелений результат. Виправляй
знайдені дефекти лише в межах package. Git операції тут заборонені; після нового
PASS потрібен окремий повторний Git checkpoint.
"""
    elif manual_rerun:
        mode_instructions = """
Режим цього turn: ручний повний перепрогін уже завершеного package на вибраній
моделі. Це не новий package і не дозвіл на Git-операції. Використай історію
цього самого канонічного чату, але не відповідай лише «вже виконано»: повторно
перевір актуальний scope, реалізацію, усі обов'язкові tests/privacy/diff gates і
поверни новий повний VARTA_STAGE_RESULT. Будь-які виправлення лишаються в межах
цього package. Попередній Git checkpoint більше не є актуальним і після нового
PASS має бути виконаний знову окремим turn у цьому самому чаті.
"""
    elif technical_recheck:
        mode_instructions = """
Режим цього turn: повторна технічна перевірка після заблокованого або
невалідного Git checkpoint. Це не новий package і не дозвіл на Git-операції.
Використовуй збережений original package baseline нижче та історію цього самого
чату, щоб повторно встановити точний stage-owned scope. Не відкидай виправлення,
зроблені попередніми turns цього canonical package chat, лише тому, що вони вже
є у worktree на початку recheck. Повторно виконай обов'язкові tests/privacy/diff
gates і поверни актуальний VARTA_STAGE_RESULT з повним exact changed_files.
"""
    else:
        mode_instructions = ""
    return f"""Ти виконуєш окремий work package дорожньої карти VARTA.

Task ID: {stage['id']}
Тема: {stage['topic']}
Залежності: {dependencies}

Цей Codex-чат є постійним і канонічним для package {stage['id']}. Повторні
спроби, продовження та Git checkpoint мають бути новими turns саме в цьому
чаті; не створюй і не проси створювати додаткові чати для цього package.

Спочатку повністю прочитай D:\\VARTA\\AGENTS.md і відповідний package у
D:\\VARTA\\docs\\chat-roadmap.md. Працюй тільки в D:\\VARTA. Старі каталоги
CaseFlow/CMSD та матеріали справ поза репозиторієм є read-only джерелами.

Завдання package:
{stage['prompt']}

{mode_instructions}

Git baseline, автоматично зафіксований controller перед запуском package:
{baseline}

Обов'язкові правила виконання:
- не видаляй і не переміщуй матеріали справ;
- не змінюй immutable originals;
- не виконуй commit, push, publication, release або remote changes без окремої
  прямої команди користувача;
- не використовуй реальні case-specific дані у fixtures, документації чи Git;
- не починай наступний package;
- не зупиняйся заради необов'язкового уточнення: роби безпечні припущення;
- якщо потрібен новий дозвіл або рішення, не зависай на request-user-input —
  заверши package як blocked і чітко опиши потрібне рішення;
- перед PASS виконай tests/gates, визначені package, і перевір поточний git diff.

Онлайн-прогрес для roadmap UI:
- перед першою предметною дією та після кожної завершеної змістовної контрольної
  точки надішли коротке commentary-повідомлення українською;
- у самому кінці такого commentary додай рівно один машинний marker без Markdown
  code fence:
  <VARTA_PROGRESS>{{"stage_id":"{stage['id']}","kind":"stage","percent":15,"phase":"Коротка назва фази","detail":"Що фактично завершено і що виконується далі"}}</VARTA_PROGRESS>
- percent має бути цілим, доказовим і монотонним у межах 15..95; не оцінюй його
  за витраченим часом. Орієнтири: inventory 15, рішення/план 25, реалізація
  35..75, перевірки 80..95. Значення 100 виставляє controller лише після
  валідного PASS;
- marker не замінює звичайне зрозуміле commentary і не повинен містити секретів
  або case-specific даних.
- у кожному змістовному commentary перед VARTA_PROGRESS додай structured
  checkpoint із точними repo-relative inputs, від яких залежить доказ. Після
  успішного кроку controller запише fingerprints; якщо inputs зміняться, він
  автоматично інвалідує тільки залежний checkpoint:
  <VARTA_CHECKPOINT>{{"stage_id":"{stage['id']}","kind":"stage","step_id":"G01-contract","status":"running|passed|failed|interrupted|invalidated","summary":"фактичний доказ","command":"точна команда або порожній рядок","inputs":["repo/relative/path"],"next_step":"точне місце продовження"}}</VARTA_CHECKPOINT>
- не включай `.varta/roadmap-controller/state.json` або згенеровані файли з
  `.varta/roadmap-controller/checkpoints/` до `inputs`: це mutable controller
  outputs, які змінюються під час lifecycle/checkpoint запису і не є стабільними
  доказовими входами;
- один `step_id` має описувати рівно одну незалежно виконувану перевірку та одну
  точну команду. Не об'єднуй pytest, browser smoke, Ruff, mypy, compileall,
  privacy або diff gates в один checkpoint. Після failure/resume запускай лише
  `failed`, `interrupted`, `invalidated` або відсутні gates; чинні `passed` із
  незмінними fingerprints обов'язково пропускай;
- `.varta/roadmap-controller/state.json`, checkpoint reports, session files і
  весь `.varta/roadmap-controller/` є mutable controller outputs: їх можна
  читати в `command`, але не додавай до `inputs`, бо вони самі змінюються під
  час запису checkpoint. Для `inputs` перелічуй стабільні code/test/config/docs
  файли, від яких залежить висновок;
- mandatory gate обмежуй stage-owned scope, prerequisites і прямо зачепленими
  спільними contracts. Не запускай і не виправляй тести чи файли пізнішого
  downstream package наперед. Випадково виявлений foreign failure зафіксуй
  окремо, але не повертай через нього blocked/failed без доведеного causal link
  до exact diff поточного package;
- перед фінальним PASS усі останні stage checkpoints мають бути passed; хоча б
  один passed checkpoint є обов'язковим. Не включай secrets або case data.

У фінальній відповіді спочатку дай нормальний людський звіт українською. В
самому кінці додай рівно один машинний блок без Markdown code fence:

<VARTA_STAGE_RESULT>{{"stage_id":"{stage['id']}","outcome":"passed|blocked|failed","summary":"короткий підсумок","tests":[{{"name":"назва перевірки","status":"passed|failed|not_run|not_applicable","evidence":"фактичний результат"}}],"changed_files":["відносний/шлях"],"gate":"чому transition gate пройдено або не пройдено","next_stage":"ID або порожній рядок"}}</VARTA_STAGE_RESULT>

Позначай outcome=passed лише коли scope завершений, усі обов'язкові перевірки
виконані й у масиві tests немає failed або not_run.
Машинний JSON має проходити json.loads без trailing comma або зайвої лапки перед
закривальною фігурною дужкою.
"""


def build_git_checkpoint_prompt(
    stage: Mapping[str, Any], run: Mapping[str, Any]
) -> str:
    stage_result = json.dumps(run.get("result") or {}, ensure_ascii=False, indent=2)
    baseline = json.dumps(run.get("gitBaseline") or {}, ensure_ascii=False, indent=2)
    return f"""Ти виконуєш GitHub checkpoint після технічного PASS етапу VARTA.

Stage ID: {stage['id']}
Тема етапу: {stage['topic']}

Це ізольований механічний Git worker без історії технічного task. Працюй лише з
машинним результатом, baseline, checkpoint-файлом і live Git evidence нижче.
Не шукай, не читай і не переказуй контекст технічної розмови stage.

Натискання користувачем кнопки GitHub checkpoint є прямою командою виконати
вузько обмежені stage-owned staging, commit, push у codex/* feature branch
публічного mixa4y/varta та створити або оновити Draft PR. Це НЕ дозвіл на
merge, tag, release, зміну visibility, force-push або публікацію матеріалів
справ.

Спочатку повністю прочитай D:\\VARTA\\AGENTS.md. Працюй тільки в D:\\VARTA.
Старі CaseFlow/CMSD каталоги та матеріали справ поза репозиторієм read-only.

Машинний результат завершеного stage:
{stage_result}

Git baseline перед початком stage:
{baseline}

Обов'язковий порядок:
1. Перевір live git status, HEAD, branch, origin і через gh visibility репозиторію.
2. Дозволена ціль — тільки публічний mixa4y/varta, origin і branch codex/*.
   Заборонені main/master, detached HEAD, інший remote, force-push та remote rewrite.
3. Зістав baseline, changed_files із stage result і поточний diff. Не приписуй
   stage жодної попередньої або сторонньої зміни. Якщо межа ownership не доведена,
   заверши BLOCKED без commit/push.
4. Заборони case materials, XLSX/PDF/DOCX/P7S/archives/databases, credentials,
    OAuth tokens, DPAPI blobs, private keys, реальні case/contact/bank identifiers,
    generated case maps і user-specific paths. Публічний repo робить цю межу
    безумовною: real corpus і case materials ніколи не stage/commit/push.
5. Stage тільки точні дозволені шляхи командою git add -- <paths>. Ніколи не
   використовуй git add ., git add -A або broad glob. Не змінюй чужий index.
6. Перед commit покажи exact staged manifest і виконай щонайменше:
   релевантні tests stage, git diff --cached --check, staged privacy/secret scan,
   forbidden extension/path scan та перевірку staged diff.
7. Створи один commit із повідомленням stage({stage['id']}): <коротка тема>.
   Якщо stage-owned змін немає, не створюй порожній commit: доведи, що поточний
   HEAD уже є на origin branch. У такому existing-commit сценарії machine result
   обов'язково має містити `commit_created=false` і `staged_files=[]`; exact
   manifest наявного commit наведи лише в checks/evidence. Controller відхиляє
   непорожній `staged_files`, якщо цей Git worker не створив commit у своєму turn.
   Поле `pushed` описує postcondition, а не факт запуску команди в цьому turn:
   став `pushed=true`, коли live read-back підтвердив result commit на origin,
   навіть якщо push не знадобився. У checks/evidence окремо вкажи, чи виконувався
   фактичний push.
8. Push тільки поточну codex/* branch до origin без force. Створи Draft PR до
   main або знайди й онови вже відкритий Draft PR цієї branch. Не merge.
9. Після push повторно перевір remote branch commit, PUBLIC visibility, Draft PR
   URL і що index/working tree не були пошкоджені сторонніми змінами.
10. Якщо будь-який gate не пройдено, outcome=blocked або failed; не маскуй помилку.

Онлайн-прогрес для roadmap UI:
- після кожної завершеної контрольної точки надішли коротке commentary і в його
  кінці один marker без Markdown code fence:
  <VARTA_PROGRESS>{{"stage_id":"{stage['id']}","kind":"git","percent":15,"phase":"Коротка назва фази","detail":"Фактичний результат checkpoint і наступна дія"}}</VARTA_PROGRESS>
- percent є доказовим і монотонним у межах 15..95: live audit 15, ownership та
  exact scope 35, tests/privacy 55, commit 75, push/Draft PR 90, controller
  read-back 95. Значення 100 controller виставляє лише після підтвердженого
  GITHUB SYNCED;
- не включай у marker secrets, credentials або case-specific дані.
- разом із кожним progress update додай VARTA_CHECKPOINT з kind=git, стабільним
  step_id, status, summary, exact command, repo-relative inputs і next_step за
  тим самим JSON contract, що в technical turn. Controller зберігає ці записи
  у `.varta/roadmap-controller/checkpoints/{stage['id']}.md`.

У фінальній відповіді спочатку дай людський звіт українською. В самому кінці
додай рівно один машинний блок без Markdown code fence:

<VARTA_GIT_RESULT>{{"stage_id":"{stage['id']}","outcome":"synced|blocked|failed","summary":"короткий підсумок","checks":[{{"name":"назва gate","status":"passed|failed|not_run|not_applicable","evidence":"фактичний результат"}}],"staged_files":["відносний/шлях"],"branch":"codex/...","commit":"40-символьний SHA або короткий SHA","commit_created":true,"remote":"origin","pushed":true,"visibility":"{CANONICAL_REPOSITORY_VISIBILITY}","pr_url":"https://github.com/owner/repo/pull/123","gate":"чому GitHub checkpoint пройдено або ні"}}</VARTA_GIT_RESULT>

Позначай outcome=synced лише коли checks не містять failed/not_run, commit
підтверджено на origin, visibility={CANONICAL_REPOSITORY_VISIBILITY} і Draft PR існує. Для blocked/failed
не вигадуй branch, commit, pushed або PR URL.
Машинний JSON має проходити json.loads без trailing comma або зайвої лапки перед
закривальною фігурною дужкою.
"""


class RoadmapConflict(RuntimeError):
    pass


class RoadmapValidationError(ValueError):
    pass


def validate_execution_settings(model: Any, reasoning_effort: Any) -> tuple[str, str]:
    normalized_model = _limited_string(model, limit=100)
    normalized_effort = _limited_string(reasoning_effort, limit=40)
    if not normalized_model or normalized_model not in EXECUTION_MODEL_EFFORTS:
        raise RoadmapValidationError("Невідома або недоступна модель Codex.")
    if normalized_effort not in EXECUTION_MODEL_EFFORTS[normalized_model]:
        raise RoadmapValidationError(
            f"Модель {normalized_model} не підтримує reasoning effort "
            f"{normalized_effort or '—'}."
        )
    return normalized_model, normalized_effort


def execution_view(run: Mapping[str, Any]) -> dict[str, str | None]:
    model = _limited_string(run.get("model"), limit=100)
    effort = _limited_string(run.get("reasoningEffort"), limit=40)
    source = run.get("executionSource")
    if model and effort and source in {"actual", "planned"}:
        return {
            "model": model,
            "reasoningEffort": effort,
            "source": str(source),
        }
    if run.get("runStatus") == "not_started" and not run.get("attempt"):
        return {
            "model": DEFAULT_EXECUTION_MODEL,
            "reasoningEffort": DEFAULT_REASONING_EFFORT,
            "source": "planned",
        }
    return {"model": None, "reasoningEffort": None, "source": "unknown"}


def requires_quality_recheck(run: Mapping[str, Any]) -> bool:
    """Reject a completed technical result produced by a disallowed profile."""

    def profile(container: Mapping[str, Any]) -> tuple[str, str] | None:
        if container.get("executionSource") != "actual":
            return None
        model = _limited_string(container.get("model"), limit=100)
        effort = _limited_string(container.get("reasoningEffort"), limit=40)
        return (model, effort) if model and effort else None

    if run.get("runStatus") == "completed":
        return profile(run) in DISALLOWED_QUALITY_PROFILES
    history = run.get("history")
    if not isinstance(history, list):
        return False
    for item in reversed(history):
        if not isinstance(item, Mapping) or item.get("runStatus") != "completed":
            continue
        previous_profile = profile(item)
        if previous_profile is not None:
            return previous_profile in DISALLOWED_QUALITY_PROFILES
    return False


class RoadmapController:
    def __init__(
        self,
        root: Path,
        *,
        catalog_path: Path | None = None,
        state_path: Path | None = None,
        runtime_root: Path | None = None,
        sessions_root: Path | None = None,
        client_factory: Callable[[Callable[[dict[str, Any]], None]], AppServerClient]
        | None = None,
        git_verifier: Callable[
            [Mapping[str, Any]], tuple[bool, str, str | None]
        ]
        | None = None,
        scope_verifier: Callable[
            [str, Mapping[str, Any], Mapping[str, Any] | None], tuple[bool, str]
        ]
        | None = None,
    ) -> None:
        self.root = root.resolve()
        self.catalog_path = catalog_path or Path(__file__).with_name("stages.json")
        self.catalog = load_catalog(self.catalog_path)
        self.catalog_by_id = {stage["id"]: stage for stage in self.catalog}
        runtime_base = runtime_root or self.root / ".varta" / "roadmap-controller"
        self.runtime_root = runtime_base
        self.sessions_root = sessions_root or default_codex_sessions_root()
        self.store = StateStore(
            state_path or runtime_base / "state.json",
            [stage["id"] for stage in self.catalog],
        )
        self.store.interrupt_stale_active_runs()
        self.store.recover_retryable_writer_conflicts()
        self.client_factory = client_factory
        self.git_verifier = git_verifier or (
            lambda result: verify_git_checkpoint_result(self.root, result)
        )
        self.scope_verifier = scope_verifier or (
            lambda stage_id, result, stage_result: verify_checkpoint_scope(
                self.root, stage_id, result, stage_result
            )
        )
        self.client: AppServerClient | None = None
        self.codex_ready = False
        self.codex_error: str | None = None
        self._lock = threading.RLock()
        self._thread_to_stage: dict[str, str] = {}
        self._thread_kind: dict[str, str] = {}
        self._thread_to_turn: dict[str, str] = {}
        self._live_messages: dict[str, str] = {}
        self._progress_signatures: dict[tuple[str, str], tuple[Any, ...]] = {}
        self._loaded_threads: set[str] = set()
        self._backfill_execution_metadata()

    def _backfill_execution_metadata(self) -> None:
        state = self.store.snapshot()
        thread_ids: set[str] = set()

        def collect_thread(container: Any, fallback: str | None = None) -> None:
            if not isinstance(container, dict):
                return
            thread_id = container.get("threadId") or fallback
            if isinstance(thread_id, str) and thread_id:
                thread_ids.add(thread_id)

        for run in state["stages"].values():
            canonical_thread = run.get("threadId")
            collect_thread(run)
            for history in run.get("history", []):
                collect_thread(history, canonical_thread)
            git_checkpoint = run.get("git")
            collect_thread(git_checkpoint, canonical_thread)
            if isinstance(git_checkpoint, dict):
                for history in git_checkpoint.get("history", []):
                    collect_thread(history, canonical_thread)

        found = load_session_execution_settings(self.sessions_root, thread_ids)
        if not found:
            return

        def enrich(container: Any, fallback: str | None = None) -> bool:
            if not isinstance(container, dict):
                return False
            thread_id = container.get("threadId") or fallback
            turn_id = container.get("turnId")
            if not isinstance(thread_id, str) or not isinstance(turn_id, str):
                return False
            metadata = found.get((thread_id, turn_id))
            if metadata is None:
                return False
            changed = False
            if not _limited_string(container.get("model"), limit=100):
                container["model"] = metadata["model"]
                changed = True
            if not _limited_string(container.get("reasoningEffort"), limit=40):
                container["reasoningEffort"] = metadata["reasoningEffort"]
                changed = True
            matches_session = (
                container.get("model") == metadata["model"]
                and container.get("reasoningEffort") == metadata["reasoningEffort"]
            )
            if matches_session and container.get("executionSource") != "actual":
                container["executionSource"] = "actual"
                changed = True
            return changed

        for stage_id, original in state["stages"].items():
            run = copy.deepcopy(original)
            canonical_thread = run.get("threadId")
            changed = enrich(run)
            for history in run.get("history", []):
                changed = enrich(history, canonical_thread) or changed
            git_checkpoint = run.get("git")
            changed = enrich(git_checkpoint, canonical_thread) or changed
            if isinstance(git_checkpoint, dict):
                for history in git_checkpoint.get("history", []):
                    changed = enrich(history, canonical_thread) or changed
            if changed:
                def replace_stage(
                    target: dict[str, Any],
                    source: dict[str, Any] = run,
                ) -> None:
                    target.clear()
                    target.update(copy.deepcopy(source))

                self.store.update_stage(stage_id, replace_stage)

    def bootstrap(self) -> None:
        try:
            self._ensure_client()
        except AppServerError as exc:
            self.codex_ready = False
            self.codex_error = _limited_string(str(exc), limit=2000)

    def _ensure_client(self) -> AppServerClient:
        with self._lock:
            if self.client is not None and self.codex_ready:
                return self.client
            if self.client_factory is not None:
                client = self.client_factory(self.handle_app_server_message)
            else:
                executable = locate_codex_executable(self.runtime_root / "runtime")
                client = CodexAppServer(
                    executable,
                    self.root,
                    self.runtime_root / "app-server.log",
                    self.handle_app_server_message,
                )
            self._loaded_threads.clear()
            client.start()
            self.client = client
            self.codex_ready = bool(client.authenticated)
            self.codex_error = None if self.codex_ready else "Codex is not authenticated"
            return client

    def health(self) -> dict[str, Any]:
        return {
            "product": APP_NAME,
            "version": APP_VERSION,
            "root": str(self.root),
            "codexReady": self.codex_ready,
            "codexError": self.codex_error,
            "pid": os.getpid(),
        }

    @staticmethod
    def _next_action(
        stages: list[dict[str, Any]],
        active: list[str],
    ) -> dict[str, Any]:
        """Return one canonical roadmap action for every UI surface.

        Critical core/readiness work intentionally outranks the parallel
        processor lane.  This keeps a pending technical recheck or Git
        checkpoint on the Evidence Map path from being hidden behind an
        otherwise startable processor package.
        """

        by_id = {str(stage["id"]): stage for stage in stages}

        def action(
            stage: Mapping[str, Any],
            *,
            kind: str,
            work_kind: str,
            reason: str,
            action_label: str,
            can_execute: bool,
        ) -> dict[str, Any]:
            run = stage.get("run")
            run_mapping = run if isinstance(run, Mapping) else {}
            thread_id = run_mapping.get("threadId")
            return {
                "kind": kind,
                "workKind": work_kind,
                "stageId": stage["id"],
                "title": stage["title"],
                "lane": (
                    "processor"
                    if stage.get("group") == "processor"
                    else "critical"
                ),
                "reason": reason,
                "actionLabel": action_label,
                "threadId": thread_id,
                "canExecute": can_execute,
            }

        if active:
            active_key = active[0]
            stage_id, separator, suffix = active_key.partition(":")
            stage = by_id.get(stage_id)
            if stage is not None:
                work_kind = suffix if separator and suffix in {"git", "review"} else "stage"
                return action(
                    stage,
                    kind="active",
                    work_kind=work_kind,
                    reason=(
                        "GitHub checkpoint виконується у постійному task цього package."
                        if work_kind == "git"
                        else (
                            "Ранній огляд контракту виконується."
                            if work_kind == "review"
                            else "Технічний turn package виконується."
                        )
                    ),
                    action_label="Виконується",
                    can_execute=False,
                )

        critical = [stage for stage in stages if stage.get("group") != "processor"]
        processors = [stage for stage in stages if stage.get("group") == "processor"]
        for lane in (critical, processors):
            contract_review = next(
                (stage for stage in lane if stage.get("canContractReview")),
                None,
            )
            if contract_review is not None:
                return action(
                    contract_review,
                    kind="contract_review",
                    work_kind="review",
                    reason=str(contract_review.get("contractReviewReason", "")),
                    action_label="Огляд контракту",
                    can_execute=True,
                )

            technical_recheck = next(
                (
                    stage
                    for stage in lane
                    if stage.get("needsTechnicalRecheck") and stage.get("canStart")
                ),
                None,
            )
            if technical_recheck is not None:
                return action(
                    technical_recheck,
                    kind="technical_recheck",
                    work_kind="stage",
                    reason=str(technical_recheck.get("startReason", "")),
                    action_label="Оновити TECH PASS",
                    can_execute=True,
                )

            git_checkpoint = next(
                (stage for stage in lane if stage.get("canGitCheckpoint")),
                None,
            )
            if git_checkpoint is not None:
                return action(
                    git_checkpoint,
                    kind="git_checkpoint",
                    work_kind="git",
                    reason=str(git_checkpoint.get("gitReason", "")),
                    action_label="Запустити GitHub checkpoint",
                    can_execute=True,
                )

            stage_start = next(
                (stage for stage in lane if stage.get("canStart")),
                None,
            )
            if stage_start is not None:
                return action(
                    stage_start,
                    kind="stage_start",
                    work_kind="stage",
                    reason=str(stage_start.get("startReason", "")),
                    action_label=f"Почати {stage_start['id']}",
                    can_execute=True,
                )

        return {
            "kind": "none",
            "workKind": None,
            "stageId": None,
            "title": None,
            "lane": None,
            "reason": (
                "Доступної ручної дії немає; очікується завершення або "
                "перевірка попереднього gate."
            ),
            "actionLabel": None,
            "threadId": None,
            "canExecute": False,
        }

    def snapshot(self) -> dict[str, Any]:
        state = self.store.snapshot()
        quality_rechecks = {
            stage_id
            for stage_id, run in state["stages"].items()
            if requires_quality_recheck(run)
        }
        completed = {
            stage_id
            for stage_id, run in state["stages"].items()
            if run.get("runStatus") == "completed"
            and isinstance(run.get("result"), dict)
            and run["result"].get("outcome") == "passed"
            and stage_id not in quality_rechecks
        }
        synced = {
            stage_id
            for stage_id, run in state["stages"].items()
            if isinstance(run.get("git"), dict)
            and run["git"].get("status") == "synced"
            and isinstance(run["git"].get("result"), dict)
            and run["git"]["result"].get("outcome") == "synced"
            and stage_id not in quality_rechecks
        }
        active: list[str] = []
        for stage_id, run in state["stages"].items():
            if run.get("runStatus") in ACTIVE_STATUSES:
                active.append(stage_id)
            git_checkpoint = run.get("git")
            if (
                isinstance(git_checkpoint, dict)
                and git_checkpoint.get("status") in ACTIVE_STATUSES
            ):
                active.append(f"{stage_id}:git")
            review = run.get("contractReview")
            if isinstance(review, dict) and review.get("status") in ACTIVE_STATUSES:
                active.append(f"{stage_id}:review")
        core_start_candidate_id: str | None = None
        readiness_start_candidate_id: str | None = None
        processor_start_candidate_ids: set[str] = set()
        git_candidate_id: str | None = None
        technical_recheck_candidate_id: str | None = None
        if self.codex_ready and not active:
            technical_recheck_candidate_id = next(
                (
                    stage["id"]
                    for stage in self.catalog
                    if stage["id"] in quality_rechecks
                    and not any(
                        dependency not in synced
                        for dependency in stage["dependencies"]
                    )
                ),
                None,
            )
            for catalog_stage in self.catalog:
                candidate_id = catalog_stage["id"]
                candidate_run = state["stages"][candidate_id]
                candidate_missing = [
                    dependency
                    for dependency in catalog_stage["dependencies"]
                    if dependency not in synced
                ]
                if (
                    candidate_run.get("runStatus") != "completed"
                    and not candidate_missing
                ):
                    if catalog_stage["group"] == "processor":
                        processor_start_candidate_ids.add(candidate_id)
                    elif catalog_stage["group"] == "readiness":
                        if readiness_start_candidate_id is None:
                            readiness_start_candidate_id = candidate_id
                    elif core_start_candidate_id is None:
                        core_start_candidate_id = candidate_id
                candidate_git = candidate_run.get("git")
                if (
                    git_candidate_id is None
                    and candidate_run.get("runStatus") == "completed"
                    and isinstance(candidate_git, dict)
                    and candidate_git.get("status") != "synced"
                    and candidate_git.get("status") not in ACTIVE_STATUSES
                ):
                    git_candidate_id = candidate_id
            if technical_recheck_candidate_id is None and git_candidate_id is not None:
                candidate_git = state["stages"][git_candidate_id].get("git")
                if (
                    isinstance(candidate_git, dict)
                    and candidate_git.get("status")
                    in TECHNICAL_RECHECK_GIT_STATUSES
                ):
                    technical_recheck_candidate_id = git_candidate_id
        stages: list[dict[str, Any]] = []
        for stage in self.catalog:
            stage_id = stage["id"]
            run = copy.deepcopy(state["stages"][stage_id])
            thread_id = run.get("threadId")
            if isinstance(thread_id, str) and thread_id in self._live_messages:
                run["lastMessage"] = self._live_messages[thread_id][-4000:]
            git_checkpoint = run["git"]
            git_thread_id = git_checkpoint.get("threadId")
            if (
                isinstance(git_thread_id, str)
                and git_thread_id in self._live_messages
            ):
                git_checkpoint["lastMessage"] = self._live_messages[git_thread_id][-4000:]
            missing = [item for item in stage["dependencies"] if item not in synced]
            current_status = run.get("runStatus")
            review = run.get("contractReview", {})
            review_status = review.get("status") if isinstance(review, dict) else "not_started"
            needs_quality_recheck = stage_id in quality_rechecks
            needs_technical_recheck = stage_id == technical_recheck_candidate_id
            is_start_candidate = (
                stage_id == core_start_candidate_id
                or stage_id == readiness_start_candidate_id
                or stage_id in processor_start_candidate_ids
                or needs_technical_recheck
            )
            can_start = (
                self.codex_ready
                and not missing
                and not active
                and (current_status != "completed" or needs_technical_recheck)
                and is_start_candidate
                and review_status == "passed"
            )
            can_review = (
                self.codex_ready
                and not missing
                and not active
                and review_status != "passed"
                and (current_status != "completed" or needs_quality_recheck)
            )

            if current_status in ACTIVE_STATUSES:
                reason = "Task уже виконується."
            elif review_status != "passed" and (current_status != "completed" or needs_quality_recheck):
                reason = "Спочатку запустіть ранній огляд контракту окремою кнопкою."
            elif current_status == "completed" and needs_technical_recheck:
                reason = (
                    "Останній TECH PASS виконано профілем Luna · low, який більше "
                    "не приймається як професійний gate. Перевірте package новим "
                    "turn на Sol/Astra з високою глибиною."
                    if needs_quality_recheck
                    else "Git checkpoint не підтвердив актуальний technical scope; "
                    "оновіть TECH PASS новим turn у цьому самому чаті."
                )
            elif current_status == "completed":
                if git_checkpoint.get("status") == "synced":
                    reason = "Stage PASS і GitHub checkpoint пройдено."
                else:
                    reason = "Stage PASS; перед наступним етапом потрібен GitHub checkpoint."
            elif active:
                reason = f"Спочатку завершіть активний task {active[0]}."
            elif missing:
                reason = "Не завершені prerequisites: " + ", ".join(missing)
            elif not self.codex_ready:
                reason = self.codex_error or "Codex App Server недоступний."
            elif (
                stage["group"] == "core"
                and core_start_candidate_id
                and stage_id != core_start_candidate_id
            ):
                reason = (
                    "За порядком core roadmap спочатку запустіть "
                    f"{core_start_candidate_id}."
                )
            elif (
                stage["group"] == "readiness"
                and readiness_start_candidate_id
                and stage_id != readiness_start_candidate_id
            ):
                reason = (
                    "За порядком readiness-гілки спочатку запустіть "
                    f"{readiness_start_candidate_id}."
                )
            else:
                reason = "Готово до запуску."

            git_status = git_checkpoint.get("status", "not_ready")
            can_git_checkpoint = (
                self.codex_ready
                and current_status == "completed"
                and git_status != "synced"
                and git_status not in ACTIVE_STATUSES
                and not active
                and stage_id == git_candidate_id
                and not needs_technical_recheck
            )
            if current_status != "completed":
                git_reason = "GitHub checkpoint доступний тільки після технічного PASS."
            elif needs_technical_recheck:
                git_reason = (
                    "Спочатку оновіть TECH PASS у цьому самому чаті: попередній "
                    "Git checkpoint не підтвердив актуальний ownership scope."
                )
            elif git_status in ACTIVE_STATUSES:
                git_reason = "GitHub checkpoint уже виконується."
            elif git_status == "synced":
                git_reason = "Commit підтверджено на origin і Draft PR зафіксовано."
            elif active:
                git_reason = f"Спочатку завершіть активну роботу {active[0]}."
            elif not self.codex_ready:
                git_reason = self.codex_error or "Codex App Server недоступний."
            elif git_checkpoint.get("retryNotice"):
                git_reason = str(git_checkpoint["retryNotice"])
            elif git_candidate_id and stage_id != git_candidate_id:
                git_reason = (
                    "За порядком roadmap спочатку виконайте GitHub checkpoint "
                    f"для {git_candidate_id}."
                )
            else:
                git_reason = (
                    "Готово: ізольований механічний Git task перевірить diff, "
                    "stage exact paths, commit, push у codex/* і Draft PR."
                )
            canonical_thread_id = run.get("threadId")
            can_rerun = (
                self.codex_ready
                and current_status == "completed"
                and not active
                and not missing
                and isinstance(canonical_thread_id, str)
                and bool(canonical_thread_id)
                and (
                    review_status == "passed"
                    or (review_status == "legacy_passed" and not needs_quality_recheck)
                )
            )
            if current_status != "completed":
                rerun_reason = "Перепрогін доступний після технічного PASS."
            elif active:
                rerun_reason = f"Спочатку завершіть активну роботу {active[0]}."
            elif missing:
                rerun_reason = "Не підтверджені prerequisites: " + ", ".join(missing)
            elif review_status != "passed" and not (
                review_status == "legacy_passed" and not needs_quality_recheck
            ):
                rerun_reason = "Спочатку виконайте ранній огляд контракту."
            elif not isinstance(canonical_thread_id, str) or not canonical_thread_id:
                rerun_reason = (
                    "Немає канонічного Task ID; новий дубль автоматично не створюється."
                )
            elif not self.codex_ready:
                rerun_reason = self.codex_error or "Codex App Server недоступний."
            else:
                rerun_reason = (
                    "Новий technical turn у тому самому чаті; попередній Git "
                    "checkpoint буде скинуто до повторної перевірки."
                )
            stages.append(
                {
                    **copy.deepcopy(stage),
                    "run": run,
                    "execution": execution_view(run),
                    "canStart": can_start,
                    "canContractReview": can_review,
                    "contractReviewReason": (
                        "Готово до раннього огляду контракту."
                        if can_review
                        else (
                            "Огляд контракту пройдено."
                            if review_status == "passed"
                            else reason
                        )
                    ),
                    "canGitCheckpoint": can_git_checkpoint,
                    "canRerun": can_rerun,
                    "needsTechnicalRecheck": needs_technical_recheck,
                    "needsQualityRecheck": needs_quality_recheck,
                    "qualityProfileAccepted": not needs_quality_recheck,
                    "blockedBy": missing,
                    "startReason": reason,
                    "gitReason": git_reason,
                    "rerunReason": rerun_reason,
                }
            )
        counts: dict[str, int] = {}
        git_counts: dict[str, int] = {}
        for run in state["stages"].values():
            status = str(run.get("runStatus", "not_started"))
            counts[status] = counts.get(status, 0) + 1
            git_status = str(run.get("git", {}).get("status", "not_ready"))
            git_counts[git_status] = git_counts.get(git_status, 0) + 1
        next_action = self._next_action(stages, active)
        return {
            "schemaVersion": 2,
            "updatedAt": state["updatedAt"],
            "controller": self.health(),
            "executionOptions": {
                "defaultModel": DEFAULT_EXECUTION_MODEL,
                "latestModel": LATEST_EXECUTION_MODEL,
                "defaultReasoningEffort": DEFAULT_REASONING_EFFORT,
                "models": [
                    {
                        "id": option["id"],
                        "label": option["label"],
                        "efforts": list(option["efforts"]),
                    }
                    for option in EXECUTION_MODEL_OPTIONS
                ],
            },
            "nextAction": next_action,
            "summary": {
                "counts": counts,
                "gitCounts": git_counts,
                "active": active,
                "completed": len(completed),
                "gitSynced": len(synced),
                "qualityRecheckRequired": len(quality_rechecks),
                "qualityRecheckStages": [
                    stage["id"] for stage in self.catalog if stage["id"] in quality_rechecks
                ],
            },
            "stages": stages,
        }

    def _bind_thread(self, thread_id: str, stage_id: str, work_kind: str) -> None:
        with self._lock:
            self._thread_to_stage[thread_id] = stage_id
            self._thread_kind[thread_id] = work_kind
            self._live_messages[thread_id] = ""
            self._progress_signatures.pop((thread_id, work_kind), None)

    def _ensure_canonical_thread(
        self,
        client: AppServerClient,
        stage: Mapping[str, Any],
        work_kind: str,
        model: str,
    ) -> tuple[str, bool]:
        """Return the one persistent Codex thread owned by a roadmap package."""

        stage_id = str(stage["id"])
        run = self.store.stage(stage_id)
        existing = run.get("threadId")
        created = False
        if isinstance(existing, str) and existing:
            thread_id = existing
            with self._lock:
                loaded = thread_id in self._loaded_threads
            if not loaded:
                resumed = client.request(
                    "thread/resume",
                    {
                        "threadId": thread_id,
                        "cwd": str(self.root),
                        "approvalPolicy": "never",
                        "sandbox": "workspace-write",
                    },
                    timeout=40,
                )
                resumed_thread = resumed.get("thread")
                resumed_id = (
                    resumed_thread.get("id") if isinstance(resumed_thread, dict) else None
                )
                if resumed_id != thread_id:
                    raise AppServerError(
                        "thread/resume did not restore the canonical package thread"
                    )
        else:
            started = client.request(
                "thread/start",
                {
                    "cwd": str(self.root),
                    "model": model,
                    "approvalPolicy": "never",
                    "sandbox": "workspace-write",
                    "serviceName": "varta_roadmap_controller",
                    "threadSource": "vartaRoadmap",
                },
                timeout=40,
            )
            thread = started.get("thread")
            if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
                raise AppServerError("thread/start did not return a thread id")
            thread_id = thread["id"]
            created = True

            def remember_thread(item: dict[str, Any]) -> None:
                item["threadId"] = thread_id
                git_checkpoint = item.get("git")
                if isinstance(git_checkpoint, dict):
                    git_checkpoint["threadId"] = thread_id

            self.store.update_stage(stage_id, remember_thread)
            client.request(
                "thread/name/set",
                {"threadId": thread_id, "name": stage["topic"]},
                timeout=20,
            )

        with self._lock:
            self._loaded_threads.add(thread_id)
        self._bind_thread(thread_id, stage_id, work_kind)
        return thread_id, created

    def _start_isolated_git_thread(
        self,
        client: AppServerClient,
        stage: Mapping[str, Any],
        model: str,
    ) -> str:
        """Start a context-free mechanical worker for one Git checkpoint attempt."""

        started = client.request(
            "thread/start",
            {
                "cwd": str(self.root),
                "model": model,
                "approvalPolicy": "never",
                "sandbox": "workspace-write",
                "serviceName": "varta_roadmap_controller",
                "threadSource": "vartaRoadmapGitWorker",
            },
            timeout=40,
        )
        thread = started.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise AppServerError("thread/start did not return a Git worker thread id")
        thread_id = thread["id"]
        client.request(
            "thread/name/set",
            {"threadId": thread_id, "name": f"VARTA {stage['id']} — GitHub sync"},
            timeout=20,
        )
        with self._lock:
            self._loaded_threads.add(thread_id)
        self._bind_thread(thread_id, str(stage["id"]), "git")
        return thread_id

    def _register_turn(self, thread_id: str, turn_id: str) -> None:
        with self._lock:
            self._thread_to_turn[thread_id] = turn_id

    def _update_work_progress(
        self,
        stage_id: str,
        work_kind: str,
        *,
        percent: int,
        phase: str,
        detail: str,
        source: str,
        allow_regression: bool = False,
    ) -> None:
        def update_progress(item: dict[str, Any]) -> None:
            progress = _normalise_progress(item.get("progress"))
            _set_progress(
                progress,
                percent=percent,
                phase=phase,
                detail=detail,
                source=source,
                allow_regression=allow_regression,
            )
            item["progress"] = progress

        if work_kind == "git":
            self._update_git_checkpoint(stage_id, update_progress)
        else:
            self.store.update_stage(stage_id, update_progress)

    def _apply_reported_progress(
        self,
        thread_id: str,
        stage_id: str,
        work_kind: str,
        text: str,
    ) -> None:
        update = parse_progress_update(text, stage_id, work_kind)
        if update is None:
            return
        signature = (
            update["percent"],
            update["phase"],
            update["detail"],
        )
        signature_key = (thread_id, work_kind)
        with self._lock:
            if self._progress_signatures.get(signature_key) == signature:
                return
            self._progress_signatures[signature_key] = signature
        current = self.store.stage(stage_id)
        container = current.get("git") if work_kind == "git" else current
        progress = container.get("progress") if isinstance(container, dict) else None
        current_percent = progress.get("percent", 0) if isinstance(progress, dict) else 0
        if isinstance(current_percent, int) and update["percent"] < current_percent:
            return
        self._update_work_progress(
            stage_id,
            work_kind,
            percent=update["percent"],
            phase=update["phase"],
            detail=update["detail"],
            source="reported",
        )

    def start_contract_review(self, stage_id: str) -> dict[str, Any]:
        stage = self.catalog_by_id.get(stage_id)
        if stage is None:
            raise KeyError(stage_id)
        self._ensure_client()
        with self._lock:
            current = next(item for item in self.snapshot()["stages"] if item["id"] == stage_id)
            if not current["canContractReview"]:
                raise RoadmapConflict(current["contractReviewReason"])

            def mark(run: dict[str, Any]) -> None:
                now = utc_now()
                review = run.setdefault("contractReview", StateStore._blank_contract_review())
                review.update(
                    {
                        "status": "starting",
                        "attempt": int(review.get("attempt", 0)) + 1,
                        "turnId": None,
                        "startedAt": now,
                        "updatedAt": now,
                        "completedAt": None,
                        "result": None,
                        "error": None,
                        "lastMessage": "Готується ранній огляд контракту…",
                    }
                )

            run = self.store.update_stage(stage_id, mark)
        threading.Thread(
            target=self._execute_contract_review,
            args=(copy.deepcopy(stage),),
            name=f"varta-roadmap-review-{stage_id}",
            daemon=True,
        ).start()
        return copy.deepcopy(run["contractReview"])

    def _execute_contract_review(self, stage: Mapping[str, Any]) -> None:
        stage_id = str(stage["id"])
        try:
            client = self._ensure_client()
            thread_id, _created = self._ensure_canonical_thread(
                client, stage, "review", DEFAULT_EXECUTION_MODEL
            )
            response = client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "model": DEFAULT_EXECUTION_MODEL,
                    "effort": DEFAULT_REASONING_EFFORT,
                    "input": [{"type": "text", "text": build_contract_review_prompt(stage)}],
                },
                timeout=40,
            )
            turn = response.get("turn")
            if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
                raise AppServerError("turn/start did not return a review turn id")
            self._register_turn(thread_id, turn["id"])

            def running(run: dict[str, Any]) -> None:
                run["contractReview"].update(
                    {
                        "status": "running",
                        "turnId": turn["id"],
                        "updatedAt": utc_now(),
                        "lastMessage": "Codex перевіряє контракт до великих тестів…",
                    }
                )

            self.store.update_stage(stage_id, running)
        except Exception as exc:
            message = _limited_string(str(exc), limit=2000) or type(exc).__name__

            def failed(run: dict[str, Any]) -> None:
                run["contractReview"].update(
                    {
                        "status": "failed",
                        "updatedAt": utc_now(),
                        "completedAt": utc_now(),
                        "error": message,
                        "lastMessage": "Огляд контракту не запустився.",
                    }
                )

            self.store.update_stage(stage_id, failed)

    def stop_contract_review(self, stage_id: str) -> dict[str, Any]:
        run = self.store.stage(stage_id)
        review = run.get("contractReview")
        if not isinstance(review, dict) or review.get("status") not in ACTIVE_STATUSES:
            raise RoadmapConflict("Огляд контракту зараз не виконується.")
        thread_id, turn_id = run.get("threadId"), review.get("turnId")
        if not isinstance(thread_id, str) or not isinstance(turn_id, str):
            raise RoadmapConflict("Review turn ще не створено; повторіть за кілька секунд.")
        self._ensure_client().request(
            "turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=20
        )
        return copy.deepcopy(review)

    def start_stage(self, stage_id: str) -> dict[str, Any]:
        return self._start_stage(stage_id, manual_rerun=False)

    def rerun_stage(
        self,
        stage_id: str,
        *,
        model: str,
        reasoning_effort: str,
    ) -> dict[str, Any]:
        selected_model, selected_effort = validate_execution_settings(
            model,
            reasoning_effort,
        )
        return self._start_stage(
            stage_id,
            manual_rerun=True,
            requested_model=selected_model,
            requested_effort=selected_effort,
        )

    def _start_stage(
        self,
        stage_id: str,
        *,
        manual_rerun: bool,
        requested_model: str | None = None,
        requested_effort: str | None = None,
    ) -> dict[str, Any]:
        stage = self.catalog_by_id.get(stage_id)
        if stage is None:
            raise KeyError(stage_id)
        self._ensure_client()
        with self._lock:
            snapshot = self.snapshot()
            current = next(item for item in snapshot["stages"] if item["id"] == stage_id)
            if manual_rerun and not current["canRerun"]:
                raise RoadmapConflict(current["rerunReason"])
            if not manual_rerun and not current["canStart"]:
                raise RoadmapConflict(current["startReason"])
            current_run = current["run"]
            current_status = current_run.get("runStatus")
            technical_recheck = bool(current.get("needsTechnicalRecheck"))
            quality_recheck = bool(current.get("needsQualityRecheck"))
            resume_from_checkpoint = current_status in {
                "blocked",
                "failed",
                "interrupted",
                "needs_review",
            }
            if manual_rerun:
                if not current_run.get("threadId"):
                    raise RoadmapConflict(
                        "Немає канонічного Task ID; новий дубль не створюється."
                    )
                selected_model, selected_effort = validate_execution_settings(
                    requested_model,
                    requested_effort,
                )
            elif quality_recheck:
                selected_model = DEFAULT_EXECUTION_MODEL
                selected_effort = DEFAULT_REASONING_EFFORT
            else:
                try:
                    selected_model, selected_effort = validate_execution_settings(
                        current_run.get("model"),
                        current_run.get("reasoningEffort"),
                    )
                except RoadmapValidationError:
                    selected_model = DEFAULT_EXECUTION_MODEL
                    selected_effort = DEFAULT_REASONING_EFFORT
            stored_baseline = current["run"].get("gitBaseline")
            git_baseline = (
                copy.deepcopy(stored_baseline)
                if (
                    technical_recheck
                    and not manual_rerun
                    and isinstance(stored_baseline, dict)
                )
                else capture_git_baseline(self.root)
            )

            def mark_starting(run: dict[str, Any]) -> None:
                if run["runStatus"] in TERMINAL_STATUSES and run["attempt"]:
                    history_entry = {
                        key: copy.deepcopy(run.get(key))
                        for key in (
                            "attempt",
                            "runStatus",
                            "threadId",
                            "turnId",
                            "model",
                            "reasoningEffort",
                            "executionSource",
                            "startedAt",
                            "completedAt",
                            "result",
                            "error",
                            "progress",
                        )
                    }
                    run["history"].append(history_entry)
                    run["history"] = run["history"][-20:]
                canonical_thread_id = run.get("threadId")
                progress = _blank_progress()
                started_at = utc_now()
                _set_progress(
                    progress,
                    percent=5,
                    phase="Підготовка запуску",
                    detail="Controller фіксує Git baseline і готує turn пакета.",
                    source="lifecycle",
                    timestamp=started_at,
                )
                previous_git = copy.deepcopy(run.get("git"))
                git_checkpoint = StateStore._blank_git_checkpoint()
                if (
                    (technical_recheck or manual_rerun)
                    and isinstance(previous_git, dict)
                    and (
                        previous_git.get("attempt")
                        or previous_git.get("status") != "not_ready"
                        or previous_git.get("turnId")
                        or previous_git.get("result")
                    )
                ):
                    previous_history = previous_git.get("history")
                    git_history = (
                        copy.deepcopy(previous_history)
                        if isinstance(previous_history, list)
                        else []
                    )
                    git_history.append(
                        {
                            key: copy.deepcopy(previous_git.get(key))
                            for key in (
                                "attempt",
                                "status",
                                "threadId",
                                "turnId",
                                "model",
                                "reasoningEffort",
                                "executionSource",
                                "startedAt",
                                "completedAt",
                                "result",
                                "error",
                                "progress",
                            )
                        }
                    )
                    git_checkpoint["history"] = git_history[-20:]
                if isinstance(canonical_thread_id, str) and canonical_thread_id:
                    git_checkpoint["threadId"] = canonical_thread_id
                run.update(
                    {
                        "seriesId": run.get("seriesId") or f"{stage_id}-{started_at}",
                        "seriesStartedAt": run.get("seriesStartedAt") or started_at,
                        "runStatus": "starting",
                        "attempt": int(run.get("attempt", 0)) + 1,
                        "threadId": canonical_thread_id,
                        "turnId": None,
                        "model": selected_model,
                        "reasoningEffort": selected_effort,
                        "executionSource": "planned",
                        "startedAt": started_at,
                        "updatedAt": started_at,
                        "completedAt": None,
                        "lastMessage": (
                            "Готується новий turn у постійному чаті package…"
                            if canonical_thread_id
                            else "Створюється постійний чат package у Codex…"
                        ),
                        "result": None,
                        "error": None,
                        "gitBaseline": git_baseline,
                        "progress": progress,
                        "git": git_checkpoint,
                    }
                )

            run = self.store.update_stage(stage_id, mark_starting)
        worker = threading.Thread(
            target=self._execute_stage,
            args=(
                copy.deepcopy(stage),
                technical_recheck,
                manual_rerun,
                quality_recheck,
                resume_from_checkpoint,
                selected_model,
                selected_effort,
            ),
            name=f"varta-roadmap-{stage_id}",
            daemon=True,
        )
        worker.start()
        return run

    def _execute_stage(
        self,
        stage: Mapping[str, Any],
        technical_recheck: bool = False,
        manual_rerun: bool = False,
        quality_recheck: bool = False,
        resume_from_checkpoint: bool = False,
        model: str = DEFAULT_EXECUTION_MODEL,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    ) -> None:
        stage_id = str(stage["id"])
        try:
            client = self._ensure_client()
            thread_id, created = self._ensure_canonical_thread(
                client,
                stage,
                "stage",
                model,
            )

            self.store.update_stage(
                stage_id,
                lambda run: run.update(
                    {
                        "threadId": thread_id,
                        "updatedAt": utc_now(),
                        "lastMessage": (
                            "Постійний чат створено; запускається перший turn…"
                            if created
                            else "Використовується постійний чат; запускається новий turn…"
                        ),
                    }
                ),
            )
            self._update_work_progress(
                stage_id,
                "stage",
                percent=8,
                phase="Чат готовий",
                detail=(
                    "Створено один постійний Codex-чат для package."
                    if created
                    else "Повторна спроба продовжується в тому самому Codex-чаті."
                ),
                source="lifecycle",
            )
            turn_result = client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "model": model,
                    "effort": reasoning_effort,
                    "input": [
                        {
                            "type": "text",
                            "text": build_task_prompt(
                                stage,
                                self.store.stage(stage_id).get("gitBaseline"),
                                technical_recheck=technical_recheck,
                                manual_rerun=manual_rerun,
                                quality_recheck=quality_recheck,
                                resume_from_checkpoint=resume_from_checkpoint,
                            ),
                        }
                    ],
                },
                timeout=40,
            )
            turn = turn_result.get("turn")
            if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
                raise AppServerError("turn/start did not return a turn id")
            self._register_turn(thread_id, turn["id"])
            self.store.update_stage(
                stage_id,
                lambda run: run.update(
                    {
                        "turnId": turn["id"],
                        "model": model,
                        "reasoningEffort": reasoning_effort,
                        "executionSource": "actual",
                        "runStatus": "running",
                        "updatedAt": utc_now(),
                        "lastMessage": "Codex виконує package…",
                    }
                ),
            )
            self._update_work_progress(
                stage_id,
                "stage",
                percent=10,
                phase="Package виконується",
                detail="Turn запущено; очікується перший доказовий progress checkpoint.",
                source="lifecycle",
            )
        except Exception as exc:
            message = _limited_string(str(exc), limit=2000) or type(exc).__name__
            self.store.update_stage(
                stage_id,
                lambda run: run.update(
                    {
                        "runStatus": "failed",
                        "updatedAt": utc_now(),
                        "completedAt": utc_now(),
                        "error": message,
                        "lastMessage": "Не вдалося запустити task.",
                    }
                ),
            )
            current = self.store.stage(stage_id).get("progress", {})
            percent = current.get("percent", 5) if isinstance(current, dict) else 5
            self._update_work_progress(
                stage_id,
                "stage",
                percent=int(percent) if isinstance(percent, int) else 5,
                phase="Запуск не вдався",
                detail=message,
                source="controller",
            )

    def _update_git_checkpoint(
        self,
        stage_id: str,
        updater: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        def update_stage(run: dict[str, Any]) -> None:
            git_checkpoint = run.get("git")
            if not isinstance(git_checkpoint, dict):
                git_checkpoint = StateStore._blank_git_checkpoint()
                run["git"] = git_checkpoint
            updater(git_checkpoint)

        stage = self.store.update_stage(stage_id, update_stage)
        return copy.deepcopy(stage["git"])

    def start_git_checkpoint(self, stage_id: str) -> dict[str, Any]:
        stage = self.catalog_by_id.get(stage_id)
        if stage is None:
            raise KeyError(stage_id)
        self._ensure_client()
        with self._lock:
            snapshot = self.snapshot()
            current = next(item for item in snapshot["stages"] if item["id"] == stage_id)
            if not current["canGitCheckpoint"]:
                raise RoadmapConflict(current["gitReason"])
            model = GIT_EXECUTION_MODEL
            reasoning_effort = GIT_REASONING_EFFORT

            def mark_starting(git_checkpoint: dict[str, Any]) -> None:
                if (
                    git_checkpoint.get("status") in TERMINAL_STATUSES | {"synced"}
                    and git_checkpoint.get("attempt")
                ):
                    history_entry = {
                        key: copy.deepcopy(git_checkpoint.get(key))
                        for key in (
                            "attempt",
                            "status",
                            "threadId",
                            "turnId",
                            "model",
                            "reasoningEffort",
                            "executionSource",
                            "startedAt",
                            "completedAt",
                            "result",
                            "error",
                            "progress",
                        )
                    }
                    git_checkpoint["history"].append(history_entry)
                    git_checkpoint["history"] = git_checkpoint["history"][-20:]
                started_at = utc_now()
                progress = _blank_progress()
                _set_progress(
                    progress,
                    percent=5,
                    phase="Підготовка Git checkpoint",
                    detail="Controller готує ізольований механічний Git worker.",
                    source="lifecycle",
                    timestamp=started_at,
                )
                git_checkpoint.update(
                    {
                        "status": "starting",
                        "attempt": int(git_checkpoint.get("attempt", 0)) + 1,
                        "threadId": None,
                        "turnId": None,
                        "model": model,
                        "reasoningEffort": reasoning_effort,
                        "executionSource": "planned",
                        "startedAt": started_at,
                        "updatedAt": started_at,
                        "completedAt": None,
                        "lastMessage": "Готується ізольований GitHub sync task…",
                        "result": None,
                        "error": None,
                        "retryNotice": None,
                        "progress": progress,
                    }
                )

            git_checkpoint = self._update_git_checkpoint(stage_id, mark_starting)
        worker = threading.Thread(
            target=self._execute_git_checkpoint,
            args=(copy.deepcopy(stage),),
            name=f"varta-roadmap-git-{stage_id}",
            daemon=True,
        )
        worker.start()
        return git_checkpoint

    def _execute_git_checkpoint(self, stage: Mapping[str, Any]) -> None:
        stage_id = str(stage["id"])
        try:
            stored = self.store.stage(stage_id)
            git_checkpoint = stored.get("git")
            if not isinstance(git_checkpoint, dict):
                raise AppServerError("Git checkpoint state is missing")
            model, reasoning_effort = validate_execution_settings(
                git_checkpoint.get("model"),
                git_checkpoint.get("reasoningEffort"),
            )
            client = self._ensure_client()
            thread_id = self._start_isolated_git_thread(client, stage, model)

            self._update_git_checkpoint(
                stage_id,
                lambda item: item.update(
                    {
                        "threadId": thread_id,
                        "updatedAt": utc_now(),
                        "lastMessage": "Створено ізольований механічний GitHub sync task.",
                    }
                ),
            )
            self._update_work_progress(
                stage_id,
                "git",
                percent=8,
                phase="Git worker готовий",
                detail="Git checkpoint запускається в окремому task без технічної історії stage.",
                source="lifecycle",
            )
            run = self.store.stage(stage_id)
            turn_result = client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "model": model,
                    "effort": reasoning_effort,
                    # The native elevated Windows sandbox runs commands as a
                    # dedicated low-privilege user. That user cannot use the
                    # interactive user's Windows Credential Manager entry
                    # created by `gh auth login`, so an explicitly confirmed
                    # Git checkpoint needs a turn-scoped full-access override.
                    # Ordinary roadmap stages keep the workspace-write policy.
                    "sandboxPolicy": {"type": "dangerFullAccess"},
                    "input": [
                        {
                            "type": "text",
                            "text": build_git_checkpoint_prompt(stage, run),
                        }
                    ],
                },
                timeout=40,
            )
            turn = turn_result.get("turn")
            if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
                raise AppServerError("turn/start did not return a turn id")
            self._register_turn(thread_id, turn["id"])
            self._update_git_checkpoint(
                stage_id,
                lambda item: item.update(
                    {
                        "turnId": turn["id"],
                        "model": model,
                        "reasoningEffort": reasoning_effort,
                        "executionSource": "actual",
                        "status": "running",
                        "updatedAt": utc_now(),
                        "lastMessage": "Codex перевіряє й публікує Git checkpoint…",
                    }
                ),
            )
            self._update_work_progress(
                stage_id,
                "git",
                percent=10,
                phase="Git checkpoint виконується",
                detail="Turn запущено; очікується перший доказовий Git progress checkpoint.",
                source="lifecycle",
            )
        except Exception as exc:
            message = _limited_string(str(exc), limit=2000) or type(exc).__name__
            if is_active_writer_conflict(message):
                self.store.recover_retryable_writer_conflicts(
                    stage_id,
                    error_message=message,
                )
                return
            self._update_git_checkpoint(
                stage_id,
                lambda item: item.update(
                    {
                        "status": "failed",
                        "updatedAt": utc_now(),
                        "completedAt": utc_now(),
                        "error": message,
                        "lastMessage": "Не вдалося запустити GitHub checkpoint task.",
                    }
                ),
            )
            current = self.store.stage(stage_id).get("git", {}).get("progress", {})
            percent = current.get("percent", 5) if isinstance(current, dict) else 5
            self._update_work_progress(
                stage_id,
                "git",
                percent=int(percent) if isinstance(percent, int) else 5,
                phase="Git checkpoint не запустився",
                detail=message,
                source="controller",
            )

    def stop_git_checkpoint(self, stage_id: str) -> dict[str, Any]:
        if stage_id not in self.catalog_by_id:
            raise KeyError(stage_id)
        run = self.store.stage(stage_id)
        git_checkpoint = run.get("git")
        if (
            not isinstance(git_checkpoint, dict)
            or git_checkpoint.get("status") not in ACTIVE_STATUSES
        ):
            raise RoadmapConflict("GitHub checkpoint зараз не виконується.")
        thread_id = git_checkpoint.get("threadId")
        turn_id = git_checkpoint.get("turnId")
        if not isinstance(thread_id, str) or not isinstance(turn_id, str):
            raise RoadmapConflict("Turn ще не створено; повторіть зупинку за кілька секунд.")
        client = self._ensure_client()
        client.request(
            "turn/interrupt",
            {"threadId": thread_id, "turnId": turn_id},
            timeout=20,
        )
        self._update_git_checkpoint(
            stage_id,
            lambda item: item.update(
                {"lastMessage": "Запит на зупинку прийнято…", "updatedAt": utc_now()}
            ),
        )
        progress = self.store.stage(stage_id).get("git", {}).get("progress", {})
        percent = progress.get("percent", 10) if isinstance(progress, dict) else 10
        self._update_work_progress(
            stage_id,
            "git",
            percent=int(percent) if isinstance(percent, int) else 10,
            phase="Зупинка Git checkpoint",
            detail="Controller надіслав запит на зупинку активного Git turn.",
            source="controller",
        )
        return copy.deepcopy(self.store.stage(stage_id)["git"])

    def stop_stage(self, stage_id: str) -> dict[str, Any]:
        if stage_id not in self.catalog_by_id:
            raise KeyError(stage_id)
        run = self.store.stage(stage_id)
        if run.get("runStatus") not in ACTIVE_STATUSES:
            raise RoadmapConflict("Цей task зараз не виконується.")
        thread_id = run.get("threadId")
        turn_id = run.get("turnId")
        if not isinstance(thread_id, str) or not isinstance(turn_id, str):
            raise RoadmapConflict("Turn ще не створено; повторіть зупинку за кілька секунд.")
        client = self._ensure_client()
        client.request(
            "turn/interrupt",
            {"threadId": thread_id, "turnId": turn_id},
            timeout=20,
        )
        self.store.update_stage(
            stage_id,
            lambda item: item.update(
                {"lastMessage": "Запит на зупинку прийнято…", "updatedAt": utc_now()}
            ),
        )
        progress = self.store.stage(stage_id).get("progress", {})
        percent = progress.get("percent", 10) if isinstance(progress, dict) else 10
        self._update_work_progress(
            stage_id,
            "stage",
            percent=int(percent) if isinstance(percent, int) else 10,
            phase="Зупинка package",
            detail="Controller надіслав запит на зупинку активного turn.",
            source="controller",
        )
        return self.store.stage(stage_id)

    def _write_checkpoint_report(self, stage_id: str) -> None:
        run = self.store.stage(stage_id)
        report_dir = self.runtime_root / "checkpoints"
        report_dir.mkdir(parents=True, exist_ok=True)
        target = report_dir / f"{stage_id}.md"
        lines = [
            f"# {stage_id} execution checkpoints",
            "",
            f"- Series: `{run.get('seriesId') or 'legacy'}`",
            f"- Series started: `{run.get('seriesStartedAt') or 'unknown'}`",
            f"- Updated: `{run.get('updatedAt') or utc_now()}`",
            "",
        ]
        checkpoints = run.get("checkpoints", [])
        if not checkpoints:
            lines.append("No structured checkpoints have been recorded.")
        for item in checkpoints:
            lines.extend(
                [
                    f"## {item.get('kind', 'stage')} / {item.get('stepId', 'unknown')}",
                    "",
                    f"- Status: **{item.get('status', 'unknown')}**",
                    f"- Updated: `{item.get('updatedAt', 'unknown')}`",
                    f"- Summary: {item.get('summary', '')}",
                    f"- Command: `{item.get('command') or 'not recorded'}`",
                    f"- Inputs: {', '.join(item.get('inputs', [])) or 'none'}",
                    f"- Next: {item.get('nextStep') or 'none'}",
                    "",
                ]
            )
        temporary = target.with_suffix(".md.tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temporary.replace(target)

    def _record_checkpoints(self, stage_id: str, work_kind: str, text: str) -> None:
        updates = parse_checkpoint_updates(text, stage_id, work_kind)
        if not updates:
            return

        def apply(run: dict[str, Any]) -> None:
            existing = run.setdefault("checkpoints", [])
            if not isinstance(existing, list):
                existing = []
                run["checkpoints"] = existing
            for update in updates:
                fingerprints = fingerprint_inputs(self.root, update["inputs"])
                if update["status"] == "passed" and fingerprints is None:
                    update["status"] = "invalidated"
                    update["summary"] += " Вхідний fingerprint не вдалося підтвердити."
                update["inputFingerprints"] = fingerprints or {}
                update["updatedAt"] = utc_now()
                key = (update["kind"], update["stepId"])
                previous = next(
                    (
                        item
                        for item in existing
                        if (item.get("kind"), item.get("stepId")) == key
                    ),
                    None,
                )
                if previous is None:
                    existing.append(copy.deepcopy(update))
                else:
                    previous.update(copy.deepcopy(update))
            run["updatedAt"] = utc_now()

        self.store.update_stage(stage_id, apply)
        self._write_checkpoint_report(stage_id)

    def _refresh_checkpoint_validity(self, stage_id: str) -> list[str]:
        invalidated: list[str] = []

        def refresh(run: dict[str, Any]) -> None:
            checkpoints = run.get("checkpoints", [])
            if not isinstance(checkpoints, list):
                return
            for item in checkpoints:
                if item.get("status") != "passed":
                    continue
                inputs = item.get("inputs")
                recorded = item.get("inputFingerprints")
                current = fingerprint_inputs(self.root, inputs) if isinstance(inputs, list) else None
                if current is None or current != recorded:
                    item["status"] = "invalidated"
                    item["updatedAt"] = utc_now()
                    invalidated.append(str(item.get("stepId", "unknown")))

        self.store.update_stage(stage_id, refresh)
        if invalidated:
            self._write_checkpoint_report(stage_id)
        return invalidated

    def _checkpoint_gate(self, stage_id: str) -> tuple[bool, str]:
        invalidated = self._refresh_checkpoint_validity(stage_id)
        run = self.store.stage(stage_id)
        checkpoints = [
            item
            for item in run.get("checkpoints", [])
            if isinstance(item, dict) and item.get("kind") == "stage"
        ]
        if invalidated:
            return False, "Змінилися inputs checkpoints: " + ", ".join(invalidated)
        if not checkpoints or not any(item.get("status") == "passed" for item in checkpoints):
            return False, "Turn не надав жодного успішного structured checkpoint."
        unresolved = [
            str(item.get("stepId", "unknown"))
            for item in checkpoints
            if item.get("status") in {"failed", "interrupted", "invalidated", "running"}
        ]
        if unresolved:
            return False, "Незакриті checkpoints: " + ", ".join(unresolved)
        return True, "Structured checkpoints та їхні input fingerprints чинні."

    def handle_app_server_message(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        thread_id = params.get("threadId")
        if not isinstance(thread_id, str):
            return
        with self._lock:
            stage_id = self._thread_to_stage.get(thread_id)
            work_kind = self._thread_kind.get(thread_id, "stage")
            active_turn_id = self._thread_to_turn.get(thread_id)
        if stage_id is None:
            return
        event_turn_id = params.get("turnId")
        if method == "turn/completed" and not isinstance(event_turn_id, str):
            event_turn = params.get("turn")
            if isinstance(event_turn, dict):
                event_turn_id = event_turn.get("id")
        if (
            isinstance(event_turn_id, str)
            and isinstance(active_turn_id, str)
            and event_turn_id != active_turn_id
        ):
            return

        def update_context(fields: Mapping[str, Any]) -> None:
            values = dict(fields)
            if work_kind == "git":
                self._update_git_checkpoint(
                    stage_id, lambda item: item.update(copy.deepcopy(values))
                )
            elif work_kind == "review":
                def update_review(run: dict[str, Any]) -> None:
                    run["contractReview"].update(copy.deepcopy(values))
                self.store.update_stage(stage_id, update_review)
            else:
                self.store.update_stage(
                    stage_id, lambda item: item.update(copy.deepcopy(values))
                )

        if method == "item/tool/requestUserInput":
            update_context(
                {
                    "updatedAt": utc_now(),
                    "lastMessage": (
                        "Interactive input request відхилено controller; "
                        "task має завершитися зі structured BLOCKED result."
                    ),
                }
            )
            return

        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if isinstance(delta, str):
                with self._lock:
                    combined = self._live_messages.get(thread_id, "") + delta
                    self._live_messages[thread_id] = combined[-200_000:]
                self._apply_reported_progress(
                    thread_id, stage_id, work_kind, combined
                )
            return

        if method == "item/completed":
            item = params.get("item")
            if isinstance(item, dict) and item.get("type") == "agentMessage":
                text = item.get("text")
                if isinstance(text, str):
                    with self._lock:
                        self._live_messages[thread_id] = text[-200_000:]
                    self._apply_reported_progress(
                        thread_id, stage_id, work_kind, text
                    )
                    self._record_checkpoints(stage_id, work_kind, text)
                    update_context(
                        {"lastMessage": text[-4000:], "updatedAt": utc_now()}
                    )
            return

        if method == "thread/status/changed":
            status = params.get("status")
            if isinstance(status, dict) and status.get("type") == "active":
                flags = status.get("activeFlags", [])
                if isinstance(flags, list) and "waitingOnApproval" in flags:
                    status_key = "status" if work_kind in {"git", "review"} else "runStatus"
                    update_context(
                        {
                            status_key: "waiting",
                            "updatedAt": utc_now(),
                            "lastMessage": "Task очікує дії або дозволу в Codex.",
                        }
                    )
                    current = self.store.stage(stage_id)
                    container = (
                        current.get("git")
                        if work_kind == "git"
                        else current.get("contractReview")
                        if work_kind == "review"
                        else current
                    )
                    progress = (
                        container.get("progress", {})
                        if isinstance(container, dict)
                        else {}
                    )
                    percent = progress.get("percent", 10)
                    self._update_work_progress(
                        stage_id,
                        work_kind,
                        percent=int(percent) if isinstance(percent, int) else 10,
                        phase="Очікується дія",
                        detail="Codex повідомив про очікування дозволу або зовнішньої дії.",
                        source="controller",
                    )
            return

        if method != "turn/completed":
            return
        turn = params.get("turn")
        if not isinstance(turn, dict):
            return
        turn_status = turn.get("status")
        with self._lock:
            final_message = self._live_messages.get(thread_id, "")
        if work_kind == "review":
            result = parse_review_result(final_message, stage_id)
            if turn_status == "interrupted":
                status, error = "interrupted", "Contract review turn зупинено."
            elif turn_status == "failed":
                turn_error = turn.get("error")
                status, error = "failed", _limited_string(
                    turn_error.get("message") if isinstance(turn_error, dict) else "Turn failed",
                    limit=2000,
                )
            elif result is None:
                status, error = "needs_review", "Немає валідного VARTA_REVIEW_RESULT."
            else:
                status = "passed" if result["outcome"] == "passed" else result["outcome"]
                error = None

            def finish_review(run: dict[str, Any]) -> None:
                now = utc_now()
                review = run["contractReview"]
                review.update(
                    {
                        "status": status,
                        "updatedAt": now,
                        "completedAt": now,
                        "lastMessage": final_message[-4000:],
                        "result": result,
                        "error": error,
                    }
                )

            self.store.update_stage(stage_id, finish_review)
            return
        if work_kind == "git":
            result = parse_git_checkpoint_result(final_message, stage_id)
            if turn_status == "interrupted":
                git_status = "interrupted"
                error = "GitHub checkpoint turn зупинено."
            elif turn_status == "failed":
                git_status = "failed"
                turn_error = turn.get("error")
                error = _limited_string(
                    turn_error.get("message")
                    if isinstance(turn_error, dict)
                    else "Turn failed",
                    limit=2000,
                )
            elif result is None:
                git_status = "needs_review"
                error = (
                    "Turn завершився без валідного VARTA_GIT_RESULT; "
                    "roadmap не позначає GitHub checkpoint як synced."
                )
            elif result["outcome"] == "synced":
                run = self.store.stage(stage_id)
                scope_ok, scope_evidence = self.scope_verifier(
                    stage_id,
                    result,
                    run.get("result") if isinstance(run, dict) else None,
                )
                if scope_ok:
                    verified, verification_evidence, canonical_commit = self.git_verifier(
                        result
                    )
                    result["controller_verification"] = (
                        scope_evidence + " " + verification_evidence
                    )
                    if verified and canonical_commit is not None:
                        result["commit"] = canonical_commit
                        git_status = "synced"
                        error = None
                    else:
                        git_status = "needs_review"
                        error = verification_evidence
                else:
                    git_status = "needs_review"
                    error = scope_evidence
                    result["controller_verification"] = scope_evidence
            elif result["outcome"] == "blocked":
                git_status = "blocked"
                error = None
            else:
                git_status = "failed"
                error = None
            self._update_git_checkpoint(
                stage_id,
                lambda item: item.update(
                    {
                        "status": git_status,
                        "updatedAt": utc_now(),
                        "completedAt": utc_now(),
                        "lastMessage": final_message[-4000:],
                        "result": result,
                        "error": error,
                    }
                ),
            )
            current_progress = self.store.stage(stage_id).get("git", {}).get(
                "progress", {}
            )
            current_percent = (
                current_progress.get("percent", 10)
                if isinstance(current_progress, dict)
                else 10
            )
            progress_phase = {
                "synced": "GITHUB SYNCED",
                "blocked": "Git checkpoint заблоковано",
                "failed": "Git checkpoint завершився помилкою",
                "interrupted": "Git checkpoint зупинено",
                "needs_review": "Git checkpoint потребує перевірки",
            }.get(git_status, "Git checkpoint завершено")
            self._update_work_progress(
                stage_id,
                "git",
                percent=100 if git_status == "synced" else int(current_percent),
                phase=progress_phase,
                detail=(
                    result["summary"]
                    if isinstance(result, dict)
                    else (error or progress_phase)
                ),
                source="controller",
            )
            return

        result = parse_stage_result(final_message, stage_id)
        if turn_status == "interrupted":
            run_status = "interrupted"
            error = "Turn зупинено."
        elif turn_status == "failed":
            run_status = "failed"
            turn_error = turn.get("error")
            error = _limited_string(
                turn_error.get("message") if isinstance(turn_error, dict) else "Turn failed",
                limit=2000,
            )
        elif result is None:
            run_status = "needs_review"
            error = (
                "Turn завершився без валідного VARTA_STAGE_RESULT; "
                "roadmap не позначає gate як PASS автоматично."
            )
        elif result["outcome"] == "passed":
            checkpoint_passed, checkpoint_evidence = self._checkpoint_gate(stage_id)
            result["controller_checkpoint_gate"] = checkpoint_evidence
            if checkpoint_passed:
                run_status = "completed"
                error = None
            else:
                run_status = "needs_review"
                error = checkpoint_evidence
        elif result["outcome"] == "blocked":
            run_status = "blocked"
            error = None
        else:
            run_status = "failed"
            error = None

        def finalize_stage(run: dict[str, Any]) -> None:
            completed_at = utc_now()
            run.update(
                {
                    "runStatus": run_status,
                    "updatedAt": completed_at,
                    "completedAt": completed_at,
                    "lastMessage": final_message[-4000:],
                    "result": result,
                    "error": error,
                }
            )
            progress = _normalise_progress(run.get("progress"))
            progress_phase = {
                "completed": "TECH PASS",
                "blocked": "Package заблоковано",
                "failed": "Package завершився помилкою",
                "interrupted": "Package зупинено",
                "needs_review": "Package потребує перевірки",
            }.get(run_status, "Package завершено")
            _set_progress(
                progress,
                percent=(
                    100
                    if run_status == "completed"
                    else int(progress.get("percent", 10))
                ),
                phase=progress_phase,
                detail=(
                    result["summary"]
                    if isinstance(result, dict)
                    else (error or progress_phase)
                ),
                source="controller",
                timestamp=completed_at,
            )
            run["progress"] = progress
            if run_status == "completed":
                git_checkpoint = run.get("git")
                if not isinstance(git_checkpoint, dict):
                    git_checkpoint = StateStore._blank_git_checkpoint()
                    run["git"] = git_checkpoint
                git_checkpoint.update(
                    {
                        "status": "awaiting_approval",
                        "threadId": run.get("threadId"),
                        "updatedAt": completed_at,
                        "lastMessage": (
                            "Технічний PASS підтверджено. GitHub змін не отримав; "
                            "потрібне окреме підтвердження checkpoint."
                        ),
                        "result": None,
                        "error": None,
                        "progress": _blank_progress(),
                    }
                )

        self.store.update_stage(stage_id, finalize_stage)

    def close(self) -> None:
        with self._lock:
            client = self.client
            self.client = None
            self.codex_ready = False
            self._loaded_threads.clear()
        if client is not None:
            client.close()


class RoadmapHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        controller: RoadmapController,
        html_path: Path,
        session_token: str,
    ) -> None:
        self.controller = controller
        self.html_path = html_path
        self.session_token = session_token
        super().__init__(address, RoadmapRequestHandler)


class RoadmapRequestHandler(BaseHTTPRequestHandler):
    server: RoadmapHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *args: Any) -> None:
        return

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "")
        expected_port = self.server.server_port
        return host.casefold() in {
            f"127.0.0.1:{expected_port}".casefold(),
            f"localhost:{expected_port}".casefold(),
        }

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        if not origin:
            return False
        parsed = urlparse(origin)
        return (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
            and parsed.port == self.server.server_port
        )

    def _token_allowed(self) -> bool:
        provided = self.headers.get("X-Varta-Roadmap-Token", "")
        return bool(provided) and hmac.compare_digest(provided, self.server.session_token)

    def _send_headers(self, status: HTTPStatus, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Connection", "close")
        self.end_headers()

    def _json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"error": message})

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._error(HTTPStatus.BAD_REQUEST, "Invalid Host header")
            return
        path = urlparse(self.path).path
        if path == "/api/v1/health":
            self._json(HTTPStatus.OK, self.server.controller.health())
            return
        if path == "/api/v1/roadmap":
            if not self._token_allowed():
                self._error(HTTPStatus.FORBIDDEN, "Invalid session token")
                return
            self._json(HTTPStatus.OK, self.server.controller.snapshot())
            return
        if path == "/favicon.ico":
            self._send_headers(HTTPStatus.NO_CONTENT, "image/x-icon", 0)
            return
        if path not in {"/", "/index.html"}:
            self._error(HTTPStatus.NOT_FOUND, "Not found")
            return
        source = self.server.html_path.read_text(encoding="utf-8")
        source = source.replace("__VARTA_SESSION_TOKEN__", self.server.session_token)
        body = source.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'",
        )
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._host_allowed():
            self._error(HTTPStatus.BAD_REQUEST, "Invalid Host header")
            return
        if not self._origin_allowed() or not self._token_allowed():
            self._error(HTTPStatus.FORBIDDEN, "Origin or session token rejected")
            return
        length_header = self.headers.get("Content-Length", "0")
        try:
            content_length = int(length_header)
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            return
        if content_length < 0 or content_length > 1024:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body is too large")
            return
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON.")
            return
        if not isinstance(payload, dict):
            self._error(HTTPStatus.BAD_REQUEST, "Request body must be a JSON object.")
            return
        path = urlparse(self.path).path
        if path == "/api/v1/controller/stop":
            self._json(HTTPStatus.ACCEPTED, {"stopping": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        stage_match = re.fullmatch(
            r"/api/v1/stages/([CPR]\d{2})/(start|stop|rerun)",
            path,
        )
        git_match = re.fullmatch(
            r"/api/v1/stages/([CPR]\d{2})/git/(start|stop)", path
        )
        review_match = re.fullmatch(
            r"/api/v1/stages/([CPR]\d{2})/review/(start|stop)", path
        )
        match = git_match or review_match or stage_match
        if match is None:
            self._error(HTTPStatus.NOT_FOUND, "Not found")
            return
        stage_id, action = match.groups()
        try:
            if review_match is not None and action == "start":
                review = self.server.controller.start_contract_review(stage_id)
                self._json(HTTPStatus.ACCEPTED, {"stageId": stage_id, "review": review})
            elif review_match is not None:
                review = self.server.controller.stop_contract_review(stage_id)
                self._json(HTTPStatus.ACCEPTED, {"stageId": stage_id, "review": review})
            elif git_match is not None and action == "start":
                checkpoint = self.server.controller.start_git_checkpoint(stage_id)
                self._json(
                    HTTPStatus.ACCEPTED,
                    {"stageId": stage_id, "git": checkpoint},
                )
            elif git_match is not None:
                checkpoint = self.server.controller.stop_git_checkpoint(stage_id)
                self._json(
                    HTTPStatus.ACCEPTED,
                    {"stageId": stage_id, "git": checkpoint},
                )
            elif action == "rerun":
                expected_keys = {"model", "reasoningEffort"}
                if set(payload) != expected_keys:
                    raise RoadmapValidationError(
                        "Rerun потребує тільки поля model і reasoningEffort."
                    )
                model = payload["model"]
                reasoning_effort = payload["reasoningEffort"]
                if not isinstance(model, str) or not isinstance(reasoning_effort, str):
                    raise RoadmapValidationError(
                        "Поля model і reasoningEffort мають бути рядками."
                    )
                run = self.server.controller.rerun_stage(
                    stage_id,
                    model=model,
                    reasoning_effort=reasoning_effort,
                )
                self._json(HTTPStatus.ACCEPTED, {"stageId": stage_id, "run": run})
            elif action == "start":
                run = self.server.controller.start_stage(stage_id)
                self._json(HTTPStatus.ACCEPTED, {"stageId": stage_id, "run": run})
            else:
                run = self.server.controller.stop_stage(stage_id)
                self._json(HTTPStatus.ACCEPTED, {"stageId": stage_id, "run": run})
        except KeyError:
            self._error(HTTPStatus.NOT_FOUND, "Unknown stage")
        except RoadmapConflict as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
        except RoadmapValidationError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except AppServerError as exc:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))


def create_http_server(
    controller: RoadmapController,
    html_path: Path,
    *,
    port: int,
    session_token: str | None = None,
) -> RoadmapHTTPServer:
    return RoadmapHTTPServer(
        ("127.0.0.1", port),
        controller,
        html_path,
        session_token or secrets.token_urlsafe(32),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--root", type=Path, default=repository_root())
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    html_path = root / "docs" / "interactive" / "varta-chat-roadmap.html"
    if not (root / "AGENTS.md").is_file() or not html_path.is_file():
        parser.error(f"Not a VARTA repository: {root}")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")

    controller = RoadmapController(root)
    controller.bootstrap()
    if args.diagnose:
        print(json.dumps(controller.health(), ensure_ascii=False))
        controller.close()
        return 0 if controller.codex_error is None else 1

    session_token = secrets.token_urlsafe(32)
    server = create_http_server(
        controller,
        html_path,
        port=args.port,
        session_token=session_token,
    )
    runtime_dir = root / ".varta" / "roadmap-controller"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "server.pid").write_text(f"{os.getpid()}\n", encoding="ascii")
    (runtime_dir / "session.token").write_text(session_token + "\n", encoding="ascii")
    (runtime_dir / "server.json").write_text(
        json.dumps(
            {
                "product": APP_NAME,
                "root": str(root),
                "host": "127.0.0.1",
                "port": server.server_port,
                "pid": os.getpid(),
                "startedAt": utc_now(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        controller.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
