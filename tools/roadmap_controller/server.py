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
APP_VERSION = "0.3.0"
STATE_SCHEMA_VERSION = 1
ACTIVE_STATUSES = frozenset({"starting", "running", "waiting"})
TERMINAL_STATUSES = frozenset(
    {"completed", "blocked", "failed", "interrupted", "needs_review"}
)
RESULT_PATTERN = re.compile(
    r"<VARTA_STAGE_RESULT>\s*(\{.*?\})\s*</VARTA_STAGE_RESULT>",
    re.DOTALL,
)
GIT_RESULT_PATTERN = re.compile(
    r"<VARTA_GIT_RESULT>\s*(\{.*?\})\s*</VARTA_GIT_RESULT>",
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
        if not isinstance(stage_id, str) or not re.fullmatch(r"[CP]\d{2}", stage_id):
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


def parse_stage_result(text: str, expected_stage_id: str) -> dict[str, Any] | None:
    matches = list(RESULT_PATTERN.finditer(text or ""))
    if not matches:
        return None
    try:
        raw = json.loads(matches[-1].group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or raw.get("stage_id") != expected_stage_id:
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
    try:
        raw = json.loads(matches[-1].group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or raw.get("stage_id") != expected_stage_id:
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
        if remote != "origin" or not pushed or visibility != "PRIVATE":
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
            "startedAt": None,
            "updatedAt": None,
            "completedAt": None,
            "lastMessage": "",
            "result": None,
            "error": None,
            "history": [],
            "progress": _blank_progress(),
        }

    @staticmethod
    def _blank_stage() -> dict[str, Any]:
        return {
            "runStatus": "not_started",
            "attempt": 0,
            "threadId": None,
            "turnId": None,
            "startedAt": None,
            "updatedAt": None,
            "completedAt": None,
            "lastMessage": "",
            "result": None,
            "error": None,
            "history": [],
            "gitBaseline": None,
            "progress": _blank_progress(),
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
            or str(repo_payload.get("visibility", "")).upper() != "PRIVATE"
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
        "Controller повторно підтвердив local HEAD, origin branch, PRIVATE repo і Draft PR.",
        local_commit,
    )


def build_task_prompt(
    stage: Mapping[str, Any], git_baseline: Mapping[str, Any] | None = None
) -> str:
    dependencies = ", ".join(stage["dependencies"]) or "немає"
    baseline = json.dumps(git_baseline or {}, ensure_ascii=False, indent=2)
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

У фінальній відповіді спочатку дай нормальний людський звіт українською. В
самому кінці додай рівно один машинний блок без Markdown code fence:

<VARTA_STAGE_RESULT>{{"stage_id":"{stage['id']}","outcome":"passed|blocked|failed","summary":"короткий підсумок","tests":[{{"name":"назва перевірки","status":"passed|failed|not_run|not_applicable","evidence":"фактичний результат"}}],"changed_files":["відносний/шлях"],"gate":"чому transition gate пройдено або не пройдено","next_stage":"ID або порожній рядок"}}</VARTA_STAGE_RESULT>

Позначай outcome=passed лише коли scope завершений, усі обов'язкові перевірки
виконані й у масиві tests немає failed або not_run.
"""


def build_git_checkpoint_prompt(
    stage: Mapping[str, Any], run: Mapping[str, Any]
) -> str:
    stage_result = json.dumps(run.get("result") or {}, ensure_ascii=False, indent=2)
    baseline = json.dumps(run.get("gitBaseline") or {}, ensure_ascii=False, indent=2)
    return f"""Ти виконуєш GitHub checkpoint після технічного PASS етапу VARTA.

Stage ID: {stage['id']}
Тема етапу: {stage['topic']}

Це продовження того самого постійного Codex-чату package {stage['id']}, а не
окремий Git-чат. Не створюй і не проси створювати додатковий чат.

Натискання користувачем кнопки GitHub checkpoint є прямою командою виконати
вузько обмежені stage-owned staging, commit, push у приватну feature branch та
створити або оновити Draft PR. Це НЕ дозвіл на merge, tag, release, зміну
visibility, force-push або публікацію матеріалів справ.

Спочатку повністю прочитай D:\\VARTA\\AGENTS.md. Працюй тільки в D:\\VARTA.
Старі CaseFlow/CMSD каталоги та матеріали справ поза репозиторієм read-only.

Машинний результат завершеного stage:
{stage_result}

Git baseline перед початком stage:
{baseline}

Обов'язковий порядок:
1. Перевір live git status, HEAD, branch, origin і через gh visibility репозиторію.
2. Дозволена ціль — тільки приватний mixa4y/varta, origin і branch codex/*.
   Заборонені main/master, detached HEAD, інший remote, force-push та remote rewrite.
3. Зістав baseline, changed_files із stage result і поточний diff. Не приписуй
   stage жодної попередньої або сторонньої зміни. Якщо межа ownership не доведена,
   заверши BLOCKED без commit/push.
4. Заборони case materials, XLSX/PDF/DOCX/P7S/archives/databases, credentials,
   OAuth tokens, DPAPI blobs, private keys, реальні case/contact/bank identifiers,
   generated case maps і user-specific paths. Приватний repo не скасовує цю межу.
5. Stage тільки точні дозволені шляхи командою git add -- <paths>. Ніколи не
   використовуй git add ., git add -A або broad glob. Не змінюй чужий index.
6. Перед commit покажи exact staged manifest і виконай щонайменше:
   релевантні tests stage, git diff --cached --check, staged privacy/secret scan,
   forbidden extension/path scan та перевірку staged diff.
7. Створи один commit із повідомленням stage({stage['id']}): <коротка тема>.
   Якщо stage-owned змін немає, не створюй порожній commit: доведи, що поточний
   HEAD уже є на origin branch.
8. Push тільки поточну codex/* branch до origin без force. Створи Draft PR до
   main або знайди й онови вже відкритий Draft PR цієї branch. Не merge.
9. Після push повторно перевір remote branch commit, private visibility, Draft PR
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

У фінальній відповіді спочатку дай людський звіт українською. В самому кінці
додай рівно один машинний блок без Markdown code fence:

<VARTA_GIT_RESULT>{{"stage_id":"{stage['id']}","outcome":"synced|blocked|failed","summary":"короткий підсумок","checks":[{{"name":"назва gate","status":"passed|failed|not_run|not_applicable","evidence":"фактичний результат"}}],"staged_files":["відносний/шлях"],"branch":"codex/...","commit":"40-символьний SHA або короткий SHA","commit_created":true,"remote":"origin","pushed":true,"visibility":"PRIVATE","pr_url":"https://github.com/owner/repo/pull/123","gate":"чому GitHub checkpoint пройдено або ні"}}</VARTA_GIT_RESULT>

Позначай outcome=synced лише коли checks не містять failed/not_run, commit
підтверджено на origin, visibility=PRIVATE і Draft PR існує. Для blocked/failed
не вигадуй branch, commit, pushed або PR URL.
"""


class RoadmapConflict(RuntimeError):
    pass


class RoadmapController:
    def __init__(
        self,
        root: Path,
        *,
        catalog_path: Path | None = None,
        state_path: Path | None = None,
        runtime_root: Path | None = None,
        client_factory: Callable[[Callable[[dict[str, Any]], None]], AppServerClient]
        | None = None,
        git_verifier: Callable[
            [Mapping[str, Any]], tuple[bool, str, str | None]
        ]
        | None = None,
    ) -> None:
        self.root = root.resolve()
        self.catalog_path = catalog_path or Path(__file__).with_name("stages.json")
        self.catalog = load_catalog(self.catalog_path)
        self.catalog_by_id = {stage["id"]: stage for stage in self.catalog}
        runtime_base = runtime_root or self.root / ".varta" / "roadmap-controller"
        self.runtime_root = runtime_base
        self.store = StateStore(
            state_path or runtime_base / "state.json",
            [stage["id"] for stage in self.catalog],
        )
        self.store.interrupt_stale_active_runs()
        self.client_factory = client_factory
        self.git_verifier = git_verifier or (
            lambda result: verify_git_checkpoint_result(self.root, result)
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

    def snapshot(self) -> dict[str, Any]:
        state = self.store.snapshot()
        completed = {
            stage_id
            for stage_id, run in state["stages"].items()
            if run.get("runStatus") == "completed"
            and isinstance(run.get("result"), dict)
            and run["result"].get("outcome") == "passed"
        }
        synced = {
            stage_id
            for stage_id, run in state["stages"].items()
            if isinstance(run.get("git"), dict)
            and run["git"].get("status") == "synced"
            and isinstance(run["git"].get("result"), dict)
            and run["git"]["result"].get("outcome") == "synced"
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
        start_candidate_id: str | None = None
        git_candidate_id: str | None = None
        if self.codex_ready and not active:
            for catalog_stage in self.catalog:
                candidate_id = catalog_stage["id"]
                candidate_run = state["stages"][candidate_id]
                candidate_missing = [
                    dependency
                    for dependency in catalog_stage["dependencies"]
                    if dependency not in synced
                ]
                if (
                    start_candidate_id is None
                    and candidate_run.get("runStatus") != "completed"
                    and not candidate_missing
                ):
                    start_candidate_id = candidate_id
                candidate_git = candidate_run.get("git")
                if (
                    git_candidate_id is None
                    and candidate_run.get("runStatus") == "completed"
                    and isinstance(candidate_git, dict)
                    and candidate_git.get("status") != "synced"
                    and candidate_git.get("status") not in ACTIVE_STATUSES
                ):
                    git_candidate_id = candidate_id
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
            can_start = (
                self.codex_ready
                and not missing
                and not active
                and current_status != "completed"
                and stage_id == start_candidate_id
            )
            if current_status in ACTIVE_STATUSES:
                reason = "Task уже виконується."
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
            elif start_candidate_id and stage_id != start_candidate_id:
                reason = f"За порядком roadmap спочатку запустіть {start_candidate_id}."
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
            )
            if current_status != "completed":
                git_reason = "GitHub checkpoint доступний тільки після технічного PASS."
            elif git_status in ACTIVE_STATUSES:
                git_reason = "GitHub checkpoint уже виконується."
            elif git_status == "synced":
                git_reason = "Commit підтверджено на origin і Draft PR зафіксовано."
            elif active:
                git_reason = f"Спочатку завершіть активну роботу {active[0]}."
            elif not self.codex_ready:
                git_reason = self.codex_error or "Codex App Server недоступний."
            elif git_candidate_id and stage_id != git_candidate_id:
                git_reason = (
                    "За порядком roadmap спочатку виконайте GitHub checkpoint "
                    f"для {git_candidate_id}."
                )
            else:
                git_reason = (
                    "Готово: новий turn у чаті цього package перевірить diff, "
                    "stage exact paths, commit, push у codex/* і Draft PR."
                )
            stages.append(
                {
                    **copy.deepcopy(stage),
                    "run": run,
                    "canStart": can_start,
                    "canGitCheckpoint": can_git_checkpoint,
                    "blockedBy": missing,
                    "startReason": reason,
                    "gitReason": git_reason,
                }
            )
        counts: dict[str, int] = {}
        git_counts: dict[str, int] = {}
        for run in state["stages"].values():
            status = str(run.get("runStatus", "not_started"))
            counts[status] = counts.get(status, 0) + 1
            git_status = str(run.get("git", {}).get("status", "not_ready"))
            git_counts[git_status] = git_counts.get(git_status, 0) + 1
        return {
            "schemaVersion": 2,
            "updatedAt": state["updatedAt"],
            "controller": self.health(),
            "summary": {
                "counts": counts,
                "gitCounts": git_counts,
                "active": active,
                "completed": len(completed),
                "gitSynced": len(synced),
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

    def start_stage(self, stage_id: str) -> dict[str, Any]:
        stage = self.catalog_by_id.get(stage_id)
        if stage is None:
            raise KeyError(stage_id)
        self._ensure_client()
        with self._lock:
            snapshot = self.snapshot()
            current = next(item for item in snapshot["stages"] if item["id"] == stage_id)
            if not current["canStart"]:
                raise RoadmapConflict(current["startReason"])
            git_baseline = capture_git_baseline(self.root)

            def mark_starting(run: dict[str, Any]) -> None:
                if run["runStatus"] in TERMINAL_STATUSES and run["attempt"]:
                    history_entry = {
                        key: copy.deepcopy(run.get(key))
                        for key in (
                            "attempt",
                            "runStatus",
                            "threadId",
                            "turnId",
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
                git_checkpoint = StateStore._blank_git_checkpoint()
                if isinstance(canonical_thread_id, str) and canonical_thread_id:
                    git_checkpoint["threadId"] = canonical_thread_id
                run.update(
                    {
                        "runStatus": "starting",
                        "attempt": int(run.get("attempt", 0)) + 1,
                        "threadId": canonical_thread_id,
                        "turnId": None,
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
            args=(copy.deepcopy(stage),),
            name=f"varta-roadmap-{stage_id}",
            daemon=True,
        )
        worker.start()
        return run

    def _execute_stage(self, stage: Mapping[str, Any]) -> None:
        stage_id = str(stage["id"])
        try:
            client = self._ensure_client()
            thread_id, created = self._ensure_canonical_thread(client, stage, "stage")

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
                    "input": [
                        {
                            "type": "text",
                            "text": build_task_prompt(
                                stage, self.store.stage(stage_id).get("gitBaseline")
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
            canonical_thread_id = current["run"].get("threadId")

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
                    detail="Controller готує новий turn у чаті цього package.",
                    source="lifecycle",
                    timestamp=started_at,
                )
                git_checkpoint.update(
                    {
                        "status": "starting",
                        "attempt": int(git_checkpoint.get("attempt", 0)) + 1,
                        "threadId": canonical_thread_id,
                        "turnId": None,
                        "startedAt": started_at,
                        "updatedAt": started_at,
                        "completedAt": None,
                        "lastMessage": "Готується Git checkpoint у чаті цього package…",
                        "result": None,
                        "error": None,
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
            client = self._ensure_client()
            thread_id, created = self._ensure_canonical_thread(client, stage, "git")

            self._update_git_checkpoint(
                stage_id,
                lambda item: item.update(
                    {
                        "threadId": thread_id,
                        "updatedAt": utc_now(),
                        "lastMessage": (
                            "Відновлено legacy package без Task ID; створено його єдиний чат."
                            if created
                            else "Git checkpoint продовжується в чаті цього package…"
                        ),
                    }
                ),
            )
            self._update_work_progress(
                stage_id,
                "git",
                percent=8,
                phase="Чат package готовий",
                detail="Git checkpoint запускається як новий turn у тому самому Codex-чаті.",
                source="lifecycle",
            )
            run = self.store.stage(stage_id)
            turn_result = client.request(
                "turn/start",
                {
                    "threadId": thread_id,
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
                    update_context(
                        {"lastMessage": text[-4000:], "updatedAt": utc_now()}
                    )
            return

        if method == "thread/status/changed":
            status = params.get("status")
            if isinstance(status, dict) and status.get("type") == "active":
                flags = status.get("activeFlags", [])
                if isinstance(flags, list) and "waitingOnApproval" in flags:
                    status_key = "status" if work_kind == "git" else "runStatus"
                    update_context(
                        {
                            status_key: "waiting",
                            "updatedAt": utc_now(),
                            "lastMessage": "Task очікує дії або дозволу в Codex.",
                        }
                    )
                    current = self.store.stage(stage_id)
                    container = current.get("git") if work_kind == "git" else current
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
                verified, verification_evidence, canonical_commit = self.git_verifier(
                    result
                )
                result["controller_verification"] = verification_evidence
                if verified and canonical_commit is not None:
                    result["commit"] = canonical_commit
                    git_status = "synced"
                    error = None
                else:
                    git_status = "needs_review"
                    error = verification_evidence
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
            run_status = "completed"
            error = None
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
        if content_length:
            self.rfile.read(content_length)
        path = urlparse(self.path).path
        if path == "/api/v1/controller/stop":
            self._json(HTTPStatus.ACCEPTED, {"stopping": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        stage_match = re.fullmatch(r"/api/v1/stages/([CP]\d{2})/(start|stop)", path)
        git_match = re.fullmatch(
            r"/api/v1/stages/([CP]\d{2})/git/(start|stop)", path
        )
        match = git_match or stage_match
        if match is None:
            self._error(HTTPStatus.NOT_FOUND, "Not found")
            return
        stage_id, action = match.groups()
        try:
            if git_match is not None and action == "start":
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
