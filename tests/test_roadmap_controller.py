from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from tools.roadmap_controller import server as roadmap


ROOT = Path(__file__).resolve().parents[1]


class FakeAppServer:
    authenticated = True

    def __init__(self, callback: Any) -> None:
        self.callback = callback
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        self.thread_count = 0
        self.turn_count = 0
        self.resume_error: str | None = None

    def start(self) -> None:
        return

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        del timeout
        payload = dict(params or {})
        self.requests.append((method, payload))
        if method == "thread/start":
            self.thread_count += 1
            suffix = "c01" if self.thread_count == 1 else f"extra-{self.thread_count}"
            return {"thread": {"id": f"thread-{suffix}", "ephemeral": False}}
        if method == "thread/name/set":
            return {}
        if method == "thread/resume":
            if self.resume_error is not None:
                raise roadmap.AppServerError(self.resume_error)
            return {"thread": {"id": payload["threadId"], "ephemeral": False}}
        if method == "turn/start":
            self.turn_count += 1
            suffix = "c01" if self.turn_count == 1 else f"c01-{self.turn_count}"
            return {"turn": {"id": f"turn-{suffix}", "status": "inProgress"}}
        if method == "turn/interrupt":
            return {}
        raise AssertionError(f"Unexpected fake request: {method}")

    def close(self) -> None:
        self.closed = True


def _wait_for_status(
    controller: roadmap.RoadmapController,
    stage_id: str,
    expected: str,
    timeout: float = 3.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        stage = controller.store.stage(stage_id)
        if stage["runStatus"] == expected:
            return stage
        time.sleep(0.02)
    raise AssertionError(
        f"{stage_id} did not reach {expected}: {controller.store.stage(stage_id)}"
    )


def _wait_for_git_status(
    controller: roadmap.RoadmapController,
    stage_id: str,
    expected: str,
    timeout: float = 3.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        checkpoint = controller.store.stage(stage_id)["git"]
        if checkpoint["status"] == expected:
            return checkpoint
        time.sleep(0.02)
    raise AssertionError(
        f"{stage_id} Git checkpoint did not reach {expected}: "
        f"{controller.store.stage(stage_id)['git']}"
    )


def _controller(
    tmp_path: Path,
    *,
    git_verifier: Any | None = None,
    sessions_root: Path | None = None,
) -> tuple[roadmap.RoadmapController, FakeAppServer]:
    fake_holder: dict[str, FakeAppServer] = {}

    def factory(callback: Any) -> FakeAppServer:
        fake = FakeAppServer(callback)
        fake_holder["client"] = fake
        return fake

    controller = roadmap.RoadmapController(
        ROOT,
        state_path=tmp_path / "state.json",
        runtime_root=tmp_path / "runtime",
        sessions_root=sessions_root or tmp_path / "sessions",
        client_factory=factory,
        git_verifier=git_verifier
        or (lambda _result: (True, "live remote verified", "a" * 40)),
        scope_verifier=lambda _stage_id, _result, _stage_result: (
            True,
            "scope verified",
        ),
    )
    controller.bootstrap()
    for stage in controller.catalog:
        controller.store.update_stage(
            stage["id"],
            lambda run: run["contractReview"].update(
                {"status": "passed", "completedAt": roadmap.utc_now()}
            ),
        )
    return controller, fake_holder["client"]


def _valid_result(stage_id: str = "C01") -> str:
    payload = {
        "stage_id": stage_id,
        "outcome": "passed",
        "summary": "Package виконано на synthetic fixtures.",
        "tests": [
            {
                "name": "pytest",
                "status": "passed",
                "evidence": "3 passed",
            }
        ],
        "changed_files": ["docs/example.md"],
        "gate": "Scope і tests підтверджені.",
        "next_stage": "C02",
    }
    checkpoint = {
        "stage_id": stage_id,
        "kind": "stage",
        "step_id": "G01-tests",
        "status": "passed",
        "summary": "Контрольний набір пройдено.",
        "command": "pytest",
        "inputs": ["tools/roadmap_controller/stages.json"],
        "next_step": "final gate",
    }
    return (
        "Людиночитний звіт.\n<VARTA_CHECKPOINT>"
        + json.dumps(checkpoint, ensure_ascii=False)
        + "</VARTA_CHECKPOINT>\n<VARTA_STAGE_RESULT>"
        + json.dumps(payload, ensure_ascii=False)
        + "</VARTA_STAGE_RESULT>"
    )


def _valid_git_result(stage_id: str = "C01") -> str:
    payload = {
        "stage_id": stage_id,
        "outcome": "synced",
        "summary": "Stage-owned diff опубліковано у public feature branch.",
        "checks": [
            {
                "name": "staged privacy scan",
                "status": "passed",
                "evidence": "no forbidden matches",
            },
            {
                "name": "remote verification",
                "status": "passed",
                "evidence": "origin contains commit",
            },
        ],
        "staged_files": ["docs/example.md"],
        "branch": "codex/stabilize-baseline",
        "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "commit_created": True,
        "remote": "origin",
        "pushed": True,
        "visibility": "PUBLIC",
        "pr_url": "https://github.com/mixa4y/varta/pull/7",
        "gate": "Remote commit і Draft PR підтверджені.",
    }
    return (
        "Git checkpoint звіт.\n<VARTA_GIT_RESULT>"
        + json.dumps(payload, ensure_ascii=False)
        + "</VARTA_GIT_RESULT>"
    )


def test_luna_low_result_requires_professional_recheck(tmp_path: Path) -> None:
    controller, _fake = _controller(tmp_path)

    def mark_low(run: dict[str, Any]) -> None:
        run.update(
            {
                "runStatus": "completed",
                "model": "gpt-5.6-luna",
                "reasoningEffort": "low",
                "executionSource": "actual",
                "result": {"outcome": "passed"},
                "threadId": "thread-c01",
            }
        )
        run["git"].update({"status": "synced", "result": {"outcome": "synced"}})

    controller.store.update_stage("C01", mark_low)
    snapshot = controller.snapshot()
    stage = next(item for item in snapshot["stages"] if item["id"] == "C01")
    assert stage["needsQualityRecheck"] is True
    assert stage["qualityProfileAccepted"] is False
    assert snapshot["summary"]["qualityRecheckStages"] == ["C01"]
    assert snapshot["summary"]["completed"] == 0
    assert snapshot["summary"]["gitSynced"] == 0

    prior = controller.store.stage("C01")

    def mark_interrupted(run: dict[str, Any]) -> None:
        run["history"].append(
            {
                "runStatus": "completed",
                "model": "gpt-5.6-luna",
                "reasoningEffort": "low",
                "executionSource": "actual",
            }
        )
        run.update(
            {
                "runStatus": "interrupted",
                "model": "gpt-5.6-sol",
                "reasoningEffort": "high",
                "executionSource": "actual",
            }
        )

    assert prior["runStatus"] == "completed"
    controller.store.update_stage("C01", mark_interrupted)
    interrupted = next(
        item for item in controller.snapshot()["stages"] if item["id"] == "C01"
    )
    assert interrupted["needsQualityRecheck"] is True


def test_scope_gate_accepts_verified_no_change_checkpoint() -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    passed, evidence = roadmap.verify_checkpoint_scope(
        ROOT,
        "C11",
        {"commit": commit, "commit_created": False, "staged_files": []},
        {"changed_files": []},
    )
    assert passed is True
    assert "ownership" in evidence


def test_scope_gate_accepts_stage_listed_on_shared_contract(tmp_path: Path) -> None:
    ownership_path = tmp_path / "config" / "file-ownership.json"
    ownership_path.parent.mkdir(parents=True)
    ownership_path.write_text(
        json.dumps(
            {
                "exactPaths": [
                    {
                        "path": "shared.py",
                        "owners": ["R02", "R04"],
                        "category": "shared-stage-contract",
                        "disposition": "hunk-review",
                    }
                ],
                "rules": [],
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "synthetic@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Synthetic Test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "add", "--", "config/file-ownership.json"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: add ownership contract"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "shared.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "shared.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "test: update shared contract"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    passed, evidence = roadmap.verify_checkpoint_scope(
        tmp_path,
        "R04",
        {"commit": commit, "commit_created": False, "staged_files": []},
        {"changed_files": ["shared.py"]},
    )

    assert passed is True
    assert "ownership" in evidence


def test_contract_review_runs_in_canonical_task(tmp_path: Path) -> None:
    controller, fake = _controller(tmp_path)
    controller.store.update_stage(
        "C01", lambda run: run["contractReview"].update({"status": "not_started"})
    )
    controller.start_contract_review("C01")
    deadline = time.monotonic() + 2
    while controller.store.stage("C01")["contractReview"]["status"] != "running":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    run = controller.store.stage("C01")
    thread_id = run["threadId"]
    turn_id = run["contractReview"]["turnId"]
    payload = {
        "stage_id": "C01",
        "outcome": "passed",
        "summary": "Contract is coherent.",
        "contract": "Preserve compatibility and privacy.",
        "required_gates": ["focused tests"],
        "inputs": ["tools/roadmap_controller/stages.json"],
    }
    fake.callback(
        {
            "method": "item/completed",
            "params": {
                "threadId": thread_id,
                "turnId": turn_id,
                "item": {
                    "type": "agentMessage",
                    "text": "<VARTA_REVIEW_RESULT>"
                    + json.dumps(payload)
                    + "</VARTA_REVIEW_RESULT>",
                },
            },
        }
    )
    fake.callback(
        {
            "method": "turn/completed",
            "params": {
                "threadId": thread_id,
                "turn": {"id": turn_id, "status": "completed"},
            },
        }
    )
    assert controller.store.stage("C01")["contractReview"]["status"] == "passed"


def test_restart_interrupts_stale_contract_review(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    store = roadmap.StateStore(state_path, ["C01"])
    store.update_stage(
        "C01",
        lambda run: run["contractReview"].update(
            {"status": "running", "turnId": "review-turn"}
        ),
    )
    reloaded = roadmap.StateStore(state_path, ["C01"])
    reloaded.interrupt_stale_active_runs()
    review = reloaded.stage("C01")["contractReview"]
    assert review["status"] == "interrupted"
    assert review["completedAt"]


def test_checkpoint_fingerprint_invalidates_only_changed_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _fake = _controller(tmp_path)
    fingerprint = {"value": "a" * 64}
    monkeypatch.setattr(
        roadmap,
        "_path_fingerprint",
        lambda _root, _path: fingerprint["value"],
    )
    checkpoint = {
        "stage_id": "C01",
        "kind": "stage",
        "step_id": "G01-contract",
        "status": "passed",
        "summary": "Contract checked.",
        "command": "read",
        "inputs": ["tools/roadmap_controller/stages.json"],
        "next_step": "tests",
    }
    controller._record_checkpoints(
        "C01",
        "stage",
        "<VARTA_CHECKPOINT>" + json.dumps(checkpoint) + "</VARTA_CHECKPOINT>",
    )
    assert controller._checkpoint_gate("C01")[0] is True
    fingerprint["value"] = "b" * 64
    passed, evidence = controller._checkpoint_gate("C01")
    assert passed is False
    assert "G01-contract" in evidence


def test_controller_runtime_output_cannot_be_checkpoint_input(tmp_path: Path) -> None:
    state_path = tmp_path / ".varta" / "roadmap-controller" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{}\n", encoding="utf-8")

    assert (
        roadmap.fingerprint_inputs(
            tmp_path, [".varta/roadmap-controller/state.json"]
        )
        is None
    )
    assert (
        roadmap.fingerprint_inputs(
            tmp_path, [r".varta\roadmap-controller\checkpoints\C12.md"]
        )
        is None
    )


def _progress_marker(
    stage_id: str = "C01",
    *,
    kind: str = "stage",
    percent: int = 35,
) -> str:
    payload = {
        "stage_id": stage_id,
        "kind": kind,
        "percent": percent,
        "phase": "Реалізація",
        "detail": "Завершено першу перевірену контрольну точку.",
    }
    return "<VARTA_PROGRESS>" + json.dumps(payload, ensure_ascii=False) + "</VARTA_PROGRESS>"


def test_catalog_contains_core_readiness_and_processor_stages() -> None:
    stages = roadmap.load_catalog(ROOT / "tools" / "roadmap_controller" / "stages.json")
    ids = [stage["id"] for stage in stages]

    assert ids[:10] == [f"C{number:02d}" for number in range(1, 11)]
    assert ids[10:15] == ["R01", "R02", "R03", "R04", "R05"]
    assert ids[15:21] == [f"C{number:02d}" for number in range(11, 17)]
    assert ids[21:] == ["P01", "P02", "P03", "P04"]
    assert next(stage for stage in stages if stage["id"] == "C11")["dependencies"] == [
        "R05"
    ]
    assert next(stage for stage in stages if stage["id"] == "R05")["dependencies"] == [
        "C09",
        "R04",
    ]
    assert next(stage for stage in stages if stage["id"] == "C16")["dependencies"] == [
        *[f"C{number:02d}" for number in range(1, 16)],
        "R05",
    ]
    assert all(stage["prompt"].strip() for stage in stages)


def test_html_and_machine_catalog_have_the_same_stage_ids() -> None:
    html = (ROOT / "docs" / "interactive" / "varta-chat-roadmap.html").read_text(
        encoding="utf-8"
    )
    stages = roadmap.load_catalog(ROOT / "tools" / "roadmap_controller" / "stages.json")

    html_ids = set(re.findall(r'data-stage-id="([CPR]\d{2})"', html))
    assert html_ids == {stage["id"] for stage in stages}
    assert len(re.findall(r'data-stage-id="([CPR]\d{2})"', html)) == 25
    assert "__VARTA_SESSION_TOKEN__" in html
    assert "start-git" in html
    assert "/git/${action}" in html
    assert "GITHUB SYNCED" in html
    assert "visibility <code>PUBLIC</code>" in html
    assert 'id="live-execution"' in html
    assert "VARTA_PROGRESS" in html
    assert "window.setInterval(refreshRoadmap, 1000)" in html
    assert "власний названий постійний task" in html
    assert "gpt-5.4-mini / high" in html
    assert "position: sticky" not in html
    assert "position: fixed" not in html
    assert 'id="expand-all">+ Розгорнути всі C/R/P' in html
    assert 'id="collapse-all">− Згорнути всі C/R/P' in html
    assert 'article[data-stage-id] details[open] summary .id::before' in html
    assert len(re.findall(r'<article class="satellite" data-stage-id="P\d{2}"><details>', html)) == 4
    assert 'id="execution-stats"' in html
    assert "function packagePresentation(stage)" in html
    assert "function renderExecutionStats(snapshot)" in html
    assert "function renderRoadmapFooter(snapshot)" in html
    assert "Оновити TECH PASS у цьому чаті" in html
    assert "snapshot.nextAction" in html
    assert "canonical controller nextAction" in html
    assert "FAILED · BLOCKED BY" in html
    assert 'if (gitStatus === "synced") return {tone: "done", label: "DONE"}' in html
    assert "summaryStatus.textContent = presentation.label" in html
    assert "Найближчий новий чат:" not in html
    assert 'href="http://127.0.0.1:8766/"' in html
    assert not re.search(r'<(?:script|link|img)[^>]+(?:src|href)="https?://', html)


def test_stage_result_requires_matching_id_and_real_passed_tests() -> None:
    valid = roadmap.parse_stage_result(_valid_result(), "C01")
    assert valid is not None
    assert valid["outcome"] == "passed"

    assert roadmap.parse_stage_result(_valid_result("C02"), "C01") is None
    no_tests = _valid_result().replace('"tests": [{', '"tests": [] , "unused": [{')
    assert roadmap.parse_stage_result(no_tests, "C01") is None

    failed_payload = json.loads(
        roadmap.RESULT_PATTERN.search(_valid_result()).group(1)  # type: ignore[union-attr]
    )
    failed_payload["tests"][0]["status"] = "failed"
    failed_text = (
        "<VARTA_STAGE_RESULT>"
        + json.dumps(failed_payload, ensure_ascii=False)
        + "</VARTA_STAGE_RESULT>"
    )
    assert roadmap.parse_stage_result(failed_text, "C01") is None


def test_progress_marker_is_stage_scoped_and_never_accepts_completion() -> None:
    valid = roadmap.parse_progress_update(_progress_marker(), "C01", "stage")
    assert valid == {
        "percent": 35,
        "phase": "Реалізація",
        "detail": "Завершено першу перевірену контрольну точку.",
        "source": "reported",
    }
    assert roadmap.parse_progress_update(_progress_marker("C02"), "C01", "stage") is None
    assert (
        roadmap.parse_progress_update(
            _progress_marker(kind="git"), "C01", "stage"
        )
        is None
    )
    assert roadmap.parse_progress_update(_progress_marker(percent=100), "C01", "stage") is None


def test_git_result_requires_public_pushed_branch_and_draft_pr() -> None:
    valid = roadmap.parse_git_checkpoint_result(_valid_git_result(), "C01")
    assert valid is not None
    assert valid["outcome"] == "synced"
    assert valid["visibility"] == "PUBLIC"

    assert roadmap.parse_git_checkpoint_result(_valid_git_result("C02"), "C01") is None
    raw = json.loads(
        roadmap.GIT_RESULT_PATTERN.search(_valid_git_result()).group(1)  # type: ignore[union-attr]
    )
    raw["branch"] = "main"
    invalid_branch = (
        "<VARTA_GIT_RESULT>"
        + json.dumps(raw, ensure_ascii=False)
        + "</VARTA_GIT_RESULT>"
    )
    assert roadmap.parse_git_checkpoint_result(invalid_branch, "C01") is None

    raw["branch"] = "codex/stabilize-baseline"
    raw["visibility"] = "PRIVATE"
    invalid_visibility = (
        "<VARTA_GIT_RESULT>"
        + json.dumps(raw, ensure_ascii=False)
        + "</VARTA_GIT_RESULT>"
    )
    assert roadmap.parse_git_checkpoint_result(invalid_visibility, "C01") is None


def test_machine_result_repairs_only_a_terminal_stray_quote() -> None:
    malformed = _valid_git_result().replace(
        "}</VARTA_GIT_RESULT>",
        ',"}</VARTA_GIT_RESULT>',
    )

    repaired = roadmap.parse_git_checkpoint_result(malformed, "C01")

    assert repaired is not None
    assert repaired["outcome"] == "synced"
    assert roadmap.parse_git_checkpoint_result(
        '<VARTA_GIT_RESULT>{"stage_id":"C01",broken}</VARTA_GIT_RESULT>',
        "C01",
    ) is None


def test_state_store_persists_atomically_and_interrupts_stale_runs(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = roadmap.StateStore(path, ["C01", "C02"])
    store.update_stage("C01", lambda stage: stage.update({"runStatus": "running"}))

    reloaded = roadmap.StateStore(path, ["C01", "C02"])
    reloaded.interrupt_stale_active_runs()

    assert reloaded.stage("C01")["runStatus"] == "interrupted"
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_session_execution_metadata_is_backfilled_without_overwriting_known_values(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    sessions_root = tmp_path / "sessions" / "2026" / "09" / "03"
    sessions_root.mkdir(parents=True)
    thread_id = "01a06486-0cc3-7880-a4d0-9e893e3b7566"
    session_path = sessions_root / f"rollout-test-{thread_id}.jsonl"
    records = [
        {"type": "turn_context", "payload": {
            "turn_id": "turn-tech", "model": "gpt-5.6-sol", "effort": "ultra",
        }},
        {"type": "turn_context", "payload": {
            "turn_id": "turn-git", "model": "gpt-5.6-terra", "effort": "high",
        }},
        {"type": "turn_context", "payload": {
            "turn_id": "turn-history", "model": "gpt-5.6-luna", "effort": "max",
        }},
    ]
    session_path.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n{malformed\n",
        encoding="utf-8",
    )
    store = roadmap.StateStore(state_path, ["C01"])

    def seed(run: dict[str, Any]) -> None:
        run.update(
            {
                "runStatus": "completed",
                "attempt": 2,
                "threadId": thread_id,
                "turnId": "turn-tech",
            }
        )
        run["history"] = [
            {
                "threadId": thread_id,
                "turnId": "turn-history",
                "model": "preserved-model",
                "reasoningEffort": "preserved-effort",
                "executionSource": "actual",
            },
            {"threadId": thread_id, "turnId": "turn-missing"},
        ]
        run["git"].update(
            {
                "threadId": thread_id,
                "turnId": "turn-git",
                "status": "synced",
            }
        )

    store.update_stage("C01", seed)
    controller, _fake = _controller(
        tmp_path,
        sessions_root=tmp_path / "sessions",
    )
    try:
        run = controller.store.stage("C01")
        assert run["model"] == "gpt-5.6-sol"
        assert run["reasoningEffort"] == "ultra"
        assert run["executionSource"] == "actual"
        assert run["git"]["model"] == "gpt-5.6-terra"
        assert run["git"]["reasoningEffort"] == "high"
        assert run["git"]["executionSource"] == "actual"
        assert run["history"][0]["model"] == "preserved-model"
        assert run["history"][0]["reasoningEffort"] == "preserved-effort"
        assert "model" not in run["history"][1]
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        assert persisted["stages"]["C01"]["model"] == "gpt-5.6-sol"
    finally:
        controller.close()


def test_snapshot_distinguishes_actual_planned_and_unknown_models(
    tmp_path: Path,
) -> None:
    controller, _fake = _controller(tmp_path)
    try:
        def mark_actual(run: dict[str, Any]) -> None:
            run.update(
                {
                    "runStatus": "completed",
                    "attempt": 1,
                    "threadId": "thread-c01",
                    "model": "gpt-5.6-sol",
                    "reasoningEffort": "ultra",
                    "executionSource": "actual",
                }
            )

        def mark_unknown(run: dict[str, Any]) -> None:
            run.update({"runStatus": "completed", "attempt": 1})

        controller.store.update_stage("C01", mark_actual)
        controller.store.update_stage("C02", mark_unknown)
        snapshot = controller.snapshot()
        by_id = {stage["id"]: stage for stage in snapshot["stages"]}

        assert by_id["C01"]["execution"] == {
            "model": "gpt-5.6-sol",
            "reasoningEffort": "ultra",
            "source": "actual",
        }
        assert by_id["C02"]["execution"] == {
            "model": None,
            "reasoningEffort": None,
            "source": "unknown",
        }
        assert by_id["C03"]["execution"] == {
            "model": "gpt-5.6-sol",
            "reasoningEffort": "high",
            "source": "planned",
        }
        assert snapshot["executionOptions"]["defaultModel"] == "gpt-5.6-sol"
        assert snapshot["executionOptions"]["latestModel"] == "gpt-6-astra"
        assert snapshot["executionOptions"]["defaultReasoningEffort"] == "high"
        assert any(
            option["id"] == "gpt-5.6-sol" and "ultra" in option["efforts"]
            for option in snapshot["executionOptions"]["models"]
        )
        astra = next(
            option
            for option in snapshot["executionOptions"]["models"]
            if option["id"] == "gpt-6-astra"
        )
        assert astra["efforts"] == [
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        ]
    finally:
        controller.close()


def test_controller_unlocks_next_stage_only_after_pass_and_git_sync(
    tmp_path: Path,
) -> None:
    controller, fake = _controller(tmp_path)
    try:
        first_snapshot = controller.snapshot()
        first = next(stage for stage in first_snapshot["stages"] if stage["id"] == "C01")
        second = next(stage for stage in first_snapshot["stages"] if stage["id"] == "C02")
        assert first["canStart"] is True
        assert second["canStart"] is False

        controller.start_stage("C01")
        running = _wait_for_status(controller, "C01", "running")
        assert running["threadId"] == "thread-c01"
        assert running["turnId"] == "turn-c01"
        assert [method for method, _ in fake.requests] == [
            "thread/start",
            "thread/name/set",
            "turn/start",
        ]
        stage_thread_start = next(
            params for method, params in fake.requests if method == "thread/start"
        )
        stage_turn_start = next(
            params for method, params in fake.requests if method == "turn/start"
        )
        assert stage_thread_start["sandbox"] == "workspace-write"
        assert stage_thread_start["model"] == "gpt-5.6-sol"
        assert "sandboxPolicy" not in stage_turn_start
        assert stage_turn_start["model"] == "gpt-5.6-sol"
        assert stage_turn_start["effort"] == "high"
        assert running["model"] == "gpt-5.6-sol"
        assert running["reasoningEffort"] == "high"
        assert running["executionSource"] == "actual"
        name_request = next(params for method, params in fake.requests if method == "thread/name/set")
        assert name_request["name"].startswith("VARTA C01")
        controller.handle_app_server_message(
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-c01",
                    "turnId": "turn-c01",
                    "delta": "Контрольна точка.\n" + _progress_marker(),
                },
            }
        )
        reported_progress = controller.store.stage("C01")["progress"]
        assert reported_progress["percent"] == 35
        assert reported_progress["source"] == "reported"
        assert reported_progress["events"][-1]["phase"] == "Реалізація"

        with pytest.raises(roadmap.RoadmapConflict):
            controller.start_stage("C02")

        final_message = _valid_result()
        controller.handle_app_server_message(
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thread-c01",
                    "turnId": "turn-c01",
                    "completedAtMs": 1,
                    "item": {"id": "item-1", "type": "agentMessage", "text": final_message},
                },
            }
        )
        controller.handle_app_server_message(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-c01",
                    "turn": {"id": "turn-c01", "status": "completed", "items": []},
                },
            }
        )

        completed = controller.store.stage("C01")
        assert completed["runStatus"] == "completed"
        assert completed["progress"]["percent"] == 100
        assert completed["git"]["status"] == "awaiting_approval"
        next_snapshot = controller.snapshot()
        first = next(stage for stage in next_snapshot["stages"] if stage["id"] == "C01")
        second = next(stage for stage in next_snapshot["stages"] if stage["id"] == "C02")
        assert first["canGitCheckpoint"] is True
        assert second["canStart"] is False
        assert second["blockedBy"] == ["C01"]

        controller.start_git_checkpoint("C01")
        git_running = _wait_for_git_status(controller, "C01", "running")
        assert git_running["threadId"] == "thread-extra-2"
        assert git_running["turnId"] == "turn-c01-2"
        assert fake.thread_count == 2
        git_turn_start = [
            params
            for method, params in fake.requests
            if method == "turn/start" and params["threadId"] == "thread-extra-2"
            and params.get("sandboxPolicy") == {"type": "dangerFullAccess"}
        ][0]
        assert git_turn_start["sandboxPolicy"] == {"type": "dangerFullAccess"}
        assert git_turn_start["model"] == "gpt-5.4-mini"
        assert git_turn_start["effort"] == "high"
        git_prompt = git_turn_start["input"][0]["text"]
        assert "git add ." in git_prompt
        assert "Ніколи не" in git_prompt
        assert "Draft PR" in git_prompt

        git_final = _valid_git_result()
        controller.handle_app_server_message(
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thread-extra-2",
                    "turnId": "turn-c01-2",
                    "completedAtMs": 2,
                    "item": {
                        "id": "item-git",
                        "type": "agentMessage",
                        "text": git_final,
                    },
                },
            }
        )
        controller.handle_app_server_message(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-extra-2",
                    "turn": {
                        "id": "turn-c01-2",
                        "status": "completed",
                        "items": [],
                    },
                },
            }
        )

        assert controller.store.stage("C01")["git"]["status"] == "synced"
        assert controller.store.stage("C01")["git"]["progress"]["percent"] == 100
        synced_snapshot = controller.snapshot()
        second = next(stage for stage in synced_snapshot["stages"] if stage["id"] == "C02")
        assert synced_snapshot["summary"]["gitSynced"] == 1
        assert second["canStart"] is True
    finally:
        controller.close()


def test_snapshot_enables_only_the_first_ready_core_stage_in_roadmap_order(
    tmp_path: Path,
) -> None:
    controller, _fake = _controller(tmp_path)
    try:
        def mark_completed_and_synced(run: dict[str, object]) -> None:
            run["runStatus"] = "completed"
            run["result"] = {"outcome": "passed"}
            git_checkpoint = run["git"]
            assert isinstance(git_checkpoint, dict)
            git_checkpoint["status"] = "synced"
            git_checkpoint["result"] = {"outcome": "synced"}

        for number in range(1, 9):
            controller.store.update_stage(
                f"C{number:02d}",
                mark_completed_and_synced,
            )

        snapshot = controller.snapshot()
        enabled = [stage["id"] for stage in snapshot["stages"] if stage["canStart"]]
        c10 = next(stage for stage in snapshot["stages"] if stage["id"] == "C10")
        c11 = next(stage for stage in snapshot["stages"] if stage["id"] == "C11")

        assert enabled == ["C09", "R01"]
        assert c10["blockedBy"] == []
        assert c11["blockedBy"] == ["R05"]
        assert c10["startReason"] == (
            "За порядком core roadmap спочатку запустіть C09."
        )
        assert c11["startReason"] == "Не завершені prerequisites: R05"
    finally:
        controller.close()


def test_snapshot_enables_dependency_ready_processors_alongside_next_core(
    tmp_path: Path,
) -> None:
    controller, _fake = _controller(tmp_path)
    try:
        def mark_completed_and_synced(run: dict[str, object]) -> None:
            run["runStatus"] = "completed"
            run["result"] = {"outcome": "passed"}
            git_checkpoint = run["git"]
            assert isinstance(git_checkpoint, dict)
            git_checkpoint["status"] = "synced"
            git_checkpoint["result"] = {"outcome": "synced"}

        for number in range(1, 11):
            controller.store.update_stage(
                f"C{number:02d}",
                mark_completed_and_synced,
            )

        snapshot = controller.snapshot()
        enabled = [stage["id"] for stage in snapshot["stages"] if stage["canStart"]]

        assert enabled == ["R01", "P01", "P02", "P03", "P04"]
        for stage_id in ("P01", "P02", "P03", "P04"):
            processor = next(
                stage for stage in snapshot["stages"] if stage["id"] == stage_id
            )
            assert processor["blockedBy"] == []
            assert processor["startReason"] == "Готово до запуску."

        controller.start_stage("P01")
        _wait_for_status(controller, "P01", "running")
        active_snapshot = controller.snapshot()
        assert not any(stage["canStart"] for stage in active_snapshot["stages"])
        assert active_snapshot["nextAction"] == {
            "kind": "active",
            "workKind": "stage",
            "stageId": "P01",
            "title": "Реалізувати OCR і text extraction adapter",
            "lane": "processor",
            "reason": "Технічний turn package виконується.",
            "actionLabel": "Виконується",
            "threadId": "thread-c01",
            "canExecute": False,
        }
        c11 = next(
            stage for stage in active_snapshot["stages"] if stage["id"] == "C11"
        )
        assert c11["startReason"] == "Спочатку завершіть активний task P01."
    finally:
        controller.close()


def test_next_action_prioritizes_critical_git_checkpoint_over_processors(
    tmp_path: Path,
) -> None:
    controller, _fake = _controller(tmp_path)
    try:
        def mark_completed_and_synced(run: dict[str, object]) -> None:
            run["runStatus"] = "completed"
            run["result"] = {"outcome": "passed"}
            git_checkpoint = run["git"]
            assert isinstance(git_checkpoint, dict)
            git_checkpoint["status"] = "synced"
            git_checkpoint["result"] = {"outcome": "synced"}

        def mark_technical_pass(run: dict[str, object]) -> None:
            run["runStatus"] = "completed"
            run["threadId"] = "thread-r03"
            run["result"] = {"outcome": "passed"}
            git_checkpoint = run["git"]
            assert isinstance(git_checkpoint, dict)
            git_checkpoint["status"] = "awaiting_approval"
            git_checkpoint["threadId"] = "thread-r03"

        for stage_id in [
            *(f"C{number:02d}" for number in range(1, 11)),
            "R01",
            "R02",
        ]:
            controller.store.update_stage(stage_id, mark_completed_and_synced)
        controller.store.update_stage("R03", mark_technical_pass)

        snapshot = controller.snapshot()
        enabled_starts = [
            stage["id"] for stage in snapshot["stages"] if stage["canStart"]
        ]
        r03 = next(stage for stage in snapshot["stages"] if stage["id"] == "R03")
        c11 = next(stage for stage in snapshot["stages"] if stage["id"] == "C11")

        assert enabled_starts == ["P01", "P02", "P03", "P04"]
        assert r03["canGitCheckpoint"] is True
        assert c11["blockedBy"] == ["R05"]
        assert snapshot["nextAction"] == {
            "kind": "git_checkpoint",
            "workKind": "git",
            "stageId": "R03",
            "title": "Реалізувати Evidence Map export audit persistence",
            "lane": "critical",
            "reason": r03["gitReason"],
            "actionLabel": "Запустити GitHub checkpoint",
            "threadId": "thread-r03",
            "canExecute": True,
        }

        controller.store.update_stage("R03", mark_completed_and_synced)
        after_sync = controller.snapshot()
        assert after_sync["nextAction"]["kind"] == "stage_start"
        assert after_sync["nextAction"]["stageId"] == "R04"
        assert after_sync["nextAction"]["lane"] == "critical"
    finally:
        controller.close()


def test_next_action_prioritizes_technical_recheck_over_processors(
    tmp_path: Path,
) -> None:
    controller, _fake = _controller(tmp_path)
    try:
        def mark_completed_and_synced(run: dict[str, object]) -> None:
            run["runStatus"] = "completed"
            run["result"] = {"outcome": "passed"}
            git_checkpoint = run["git"]
            assert isinstance(git_checkpoint, dict)
            git_checkpoint["status"] = "synced"
            git_checkpoint["result"] = {"outcome": "synced"}

        for stage_id in [
            *(f"C{number:02d}" for number in range(1, 11)),
            "R01",
            "R02",
        ]:
            controller.store.update_stage(stage_id, mark_completed_and_synced)

        def mark_needs_recheck(run: dict[str, object]) -> None:
            run["runStatus"] = "completed"
            run["threadId"] = "thread-r03"
            run["result"] = {"outcome": "passed"}
            git_checkpoint = run["git"]
            assert isinstance(git_checkpoint, dict)
            git_checkpoint["status"] = "needs_review"
            git_checkpoint["threadId"] = "thread-r03"

        controller.store.update_stage("R03", mark_needs_recheck)
        snapshot = controller.snapshot()

        assert snapshot["nextAction"]["kind"] == "technical_recheck"
        assert snapshot["nextAction"]["stageId"] == "R03"
        assert snapshot["nextAction"]["lane"] == "critical"
        assert snapshot["nextAction"]["threadId"] == "thread-r03"
        assert snapshot["nextAction"]["canExecute"] is True
    finally:
        controller.close()


def test_c11_unlocks_only_after_sequential_readiness_branch_is_synced(
    tmp_path: Path,
) -> None:
    controller, _fake = _controller(tmp_path)
    try:
        def mark_completed_and_synced(run: dict[str, object]) -> None:
            run["runStatus"] = "completed"
            run["result"] = {"outcome": "passed"}
            git_checkpoint = run["git"]
            assert isinstance(git_checkpoint, dict)
            git_checkpoint["status"] = "synced"
            git_checkpoint["result"] = {"outcome": "synced"}

        for number in range(1, 11):
            controller.store.update_stage(
                f"C{number:02d}",
                mark_completed_and_synced,
            )

        for readiness_number in range(1, 6):
            snapshot = controller.snapshot()
            enabled = [stage["id"] for stage in snapshot["stages"] if stage["canStart"]]
            expected = f"R{readiness_number:02d}"
            assert expected in enabled
            c11 = next(stage for stage in snapshot["stages"] if stage["id"] == "C11")
            assert c11["canStart"] is False
            assert c11["blockedBy"] == ["R05"]
            c12 = next(stage for stage in snapshot["stages"] if stage["id"] == "C12")
            assert c12["canStart"] is False
            assert "C11" in c12["blockedBy"]
            if expected == "R05":
                controller.store.update_stage(
                    "R05",
                    lambda run: run.update(
                        {"runStatus": "completed", "result": {"outcome": "passed"}}
                    ),
                )
                tech_only = next(
                    stage for stage in controller.snapshot()["stages"]
                    if stage["id"] == "C11"
                )
                assert tech_only["canStart"] is False
                assert tech_only["blockedBy"] == ["R05"]
            controller.store.update_stage(expected, mark_completed_and_synced)

        final_snapshot = controller.snapshot()
        final_enabled = [
            stage["id"] for stage in final_snapshot["stages"] if stage["canStart"]
        ]
        assert "C11" in final_enabled
        c11 = next(stage for stage in final_snapshot["stages"] if stage["id"] == "C11")
        assert c11["blockedBy"] == []
        c12 = next(stage for stage in final_snapshot["stages"] if stage["id"] == "C12")
        assert c12["canStart"] is False
        assert c12["blockedBy"] == ["C11"]
        controller.store.update_stage("C11", mark_completed_and_synced)
        c12 = next(stage for stage in controller.snapshot()["stages"] if stage["id"] == "C12")
        assert c12["canStart"] is True
        assert c12["blockedBy"] == []
    finally:
        controller.close()


def test_completed_turn_without_machine_result_needs_review(tmp_path: Path) -> None:
    controller, _fake = _controller(tmp_path)
    try:
        controller.start_stage("C01")
        _wait_for_status(controller, "C01", "running")
        controller.handle_app_server_message(
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thread-c01",
                    "turnId": "turn-c01",
                    "completedAtMs": 1,
                    "item": {"id": "item-1", "type": "agentMessage", "text": "Готово."},
                },
            }
        )
        controller.handle_app_server_message(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-c01",
                    "turn": {"id": "turn-c01", "status": "completed", "items": []},
                },
            }
        )

        assert controller.store.stage("C01")["runStatus"] == "needs_review"
        assert controller.snapshot()["summary"]["completed"] == 0
    finally:
        controller.close()


def test_retry_reuses_the_same_stage_thread_and_starts_only_a_new_turn(
    tmp_path: Path,
) -> None:
    controller, fake = _controller(tmp_path)
    try:
        controller.start_stage("C01")
        first = _wait_for_status(controller, "C01", "running")
        controller.handle_app_server_message(
            {
                "method": "item/completed",
                "params": {
                    "threadId": first["threadId"],
                    "turnId": first["turnId"],
                    "item": {"type": "agentMessage", "text": "Потрібна повторна спроба."},
                },
            }
        )
        controller.handle_app_server_message(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": first["threadId"],
                    "turn": {"id": first["turnId"], "status": "completed", "items": []},
                },
            }
        )
        assert controller.store.stage("C01")["runStatus"] == "needs_review"

        controller.start_stage("C01")
        second = _wait_for_status(controller, "C01", "running")

        assert first["threadId"] == second["threadId"] == "thread-c01"
        assert first["turnId"] == "turn-c01"
        assert second["turnId"] == "turn-c01-2"
        assert fake.thread_count == 1
        assert fake.turn_count == 2
        assert [method for method, _ in fake.requests].count("thread/start") == 1
        assert [method for method, _ in fake.requests].count("thread/name/set") == 1
    finally:
        controller.close()


def test_completed_stage_rerun_uses_selected_model_in_the_same_thread(
    tmp_path: Path,
) -> None:
    controller, fake = _controller(tmp_path)
    try:
        controller.start_stage("C01")
        first = _wait_for_status(controller, "C01", "running")
        first_result = _valid_result()
        controller.handle_app_server_message(
            {
                "method": "item/completed",
                "params": {
                    "threadId": first["threadId"],
                    "turnId": first["turnId"],
                    "item": {"type": "agentMessage", "text": first_result},
                },
            }
        )
        controller.handle_app_server_message(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": first["threadId"],
                    "turn": {"id": first["turnId"], "status": "completed", "items": []},
                },
            }
        )

        def mark_git_synced(run: dict[str, Any]) -> None:
            run["git"].update(
                {
                    "status": "synced",
                    "attempt": 1,
                    "threadId": run["threadId"],
                    "turnId": "turn-git-old",
                    "model": run["model"],
                    "reasoningEffort": run["reasoningEffort"],
                    "executionSource": "actual",
                    "result": {"outcome": "synced"},
                }
            )

        controller.store.update_stage("C01", mark_git_synced)
        before = controller.snapshot()
        c01_before = next(stage for stage in before["stages"] if stage["id"] == "C01")
        assert c01_before["canRerun"] is True

        controller.rerun_stage(
            "C01",
            model="gpt-5.6-terra",
            reasoning_effort="ultra",
        )
        second = _wait_for_status(controller, "C01", "running")

        assert second["threadId"] == first["threadId"] == "thread-c01"
        assert second["turnId"] == "turn-c01-2"
        assert second["attempt"] == 2
        assert second["model"] == "gpt-5.6-terra"
        assert second["reasoningEffort"] == "ultra"
        assert second["executionSource"] == "actual"
        assert second["history"][-1]["model"] == "gpt-5.6-sol"
        assert second["history"][-1]["reasoningEffort"] == "high"
        assert second["git"]["status"] == "not_ready"
        assert second["git"]["history"][-1]["status"] == "synced"
        assert second["git"]["history"][-1]["model"] == "gpt-5.6-sol"
        assert second["gitBaseline"]["head"]
        assert fake.thread_count == 1
        assert fake.turn_count == 2
        assert [method for method, _ in fake.requests].count("thread/start") == 1
        assert [method for method, _ in fake.requests].count("thread/name/set") == 1
        rerun_request = [
            payload for method, payload in fake.requests if method == "turn/start"
        ][-1]
        assert rerun_request["threadId"] == "thread-c01"
        assert rerun_request["model"] == "gpt-5.6-terra"
        assert rerun_request["effort"] == "ultra"
        assert "ручний повний перепрогін" in rerun_request["input"][0]["text"]

        second_result = _valid_result()
        controller.handle_app_server_message(
            {
                "method": "item/completed",
                "params": {
                    "threadId": second["threadId"],
                    "turnId": second["turnId"],
                    "item": {"type": "agentMessage", "text": second_result},
                },
            }
        )
        controller.handle_app_server_message(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": second["threadId"],
                    "turn": {"id": second["turnId"], "status": "completed", "items": []},
                },
            }
        )
        completed = controller.store.stage("C01")
        assert completed["runStatus"] == "completed"
        assert completed["git"]["status"] == "awaiting_approval"
        assert completed["git"]["history"][-1]["status"] == "synced"
    finally:
        controller.close()


@pytest.mark.parametrize(
    ("model", "effort"),
    [
        ("unknown-model", "ultra"),
        ("gpt-5.4-mini", "ultra"),
        ("gpt-5.6-sol", ""),
    ],
)
def test_rerun_rejects_invalid_execution_settings_without_state_change(
    tmp_path: Path,
    model: str,
    effort: str,
) -> None:
    controller, fake = _controller(tmp_path)
    try:
        before = controller.store.snapshot()
        with pytest.raises(roadmap.RoadmapValidationError):
            controller.rerun_stage("C01", model=model, reasoning_effort=effort)
        assert controller.store.snapshot() == before
        assert not fake.requests
    finally:
        controller.close()


def test_rerun_requires_completed_stage_and_canonical_thread(tmp_path: Path) -> None:
    controller, fake = _controller(tmp_path)
    try:
        with pytest.raises(roadmap.RoadmapConflict):
            controller.rerun_stage(
                "C01",
                model="gpt-5.6-sol",
                reasoning_effort="ultra",
            )

        controller.store.update_stage(
            "C01",
            lambda run: run.update(
                {"runStatus": "completed", "result": {"outcome": "passed"}}
            ),
        )
        with pytest.raises(roadmap.RoadmapConflict, match="Task ID"):
            controller.rerun_stage(
                "C01",
                model="gpt-5.6-sol",
                reasoning_effort="ultra",
            )
        assert not fake.requests
    finally:
        controller.close()


def test_git_needs_review_enables_same_chat_technical_recheck(
    tmp_path: Path,
) -> None:
    controller, fake = _controller(tmp_path)
    original_baseline = {
        "capturedAt": "2026-08-31T20:46:43+03:00",
        "head": "1" * 40,
        "branch": "codex/stabilize-baseline",
        "status": ["?? case_docket/application/evidence_map_source.py"],
        "statusSha256": "2" * 64,
    }
    stage_result = roadmap.parse_stage_result(_valid_result(), "C01")
    assert stage_result is not None

    def mark_needs_recheck(run: dict[str, Any]) -> None:
        run.update(
            {
                "runStatus": "completed",
                "attempt": 3,
                "threadId": "thread-c01",
                "result": stage_result,
                "gitBaseline": original_baseline,
            }
        )
        checkpoint = roadmap.StateStore._blank_git_checkpoint()
        checkpoint.update(
            {
                "status": "needs_review",
                "attempt": 2,
                "threadId": "thread-c01",
                "turnId": "turn-c01-git-2",
                "startedAt": "2026-09-01T17:34:35+03:00",
                "completedAt": "2026-09-01T17:35:18+03:00",
                "error": "Machine result does not match the current ownership scope.",
            }
        )
        run["git"] = checkpoint

    try:
        controller.store.update_stage("C01", mark_needs_recheck)
        snapshot = controller.snapshot()
        stage = next(item for item in snapshot["stages"] if item["id"] == "C01")

        assert stage["needsTechnicalRecheck"] is True
        assert stage["canStart"] is True
        assert stage["canGitCheckpoint"] is False
        assert "оновіть TECH PASS" in stage["startReason"]

        controller.start_stage("C01")
        running = _wait_for_status(controller, "C01", "running")

        assert running["threadId"] == "thread-c01"
        assert running["gitBaseline"] == original_baseline
        assert running["git"]["status"] == "not_ready"
        assert running["git"]["history"][-1]["status"] == "needs_review"
        assert running["git"]["history"][-1]["attempt"] == 2
        assert fake.thread_count == 0
        assert fake.turn_count == 1
        turn_request = next(
            payload for method, payload in fake.requests if method == "turn/start"
        )
        prompt = turn_request["input"][0]["text"]
        assert "повторна технічна перевірка" in prompt
        assert original_baseline["head"] in prompt
    finally:
        controller.close()


def test_controller_restart_resumes_canonical_thread_instead_of_creating_duplicate(
    tmp_path: Path,
) -> None:
    first_controller, _first_fake = _controller(tmp_path)
    try:
        first_controller.start_stage("C01")
        first = _wait_for_status(first_controller, "C01", "running")
        first_controller.handle_app_server_message(
            {
                "method": "item/completed",
                "params": {
                    "threadId": first["threadId"],
                    "turnId": first["turnId"],
                    "item": {"type": "agentMessage", "text": "Потрібна повторна спроба."},
                },
            }
        )
        first_controller.handle_app_server_message(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": first["threadId"],
                    "turn": {"id": first["turnId"], "status": "completed", "items": []},
                },
            }
        )
        assert first_controller.store.stage("C01")["runStatus"] == "needs_review"
    finally:
        first_controller.close()

    resumed_controller, resumed_fake = _controller(tmp_path)
    try:
        resumed_controller.start_stage("C01")
        resumed = _wait_for_status(resumed_controller, "C01", "running")

        assert resumed["threadId"] == "thread-c01"
        assert resumed_fake.thread_count == 0
        resume_requests = [
            params for method, params in resumed_fake.requests if method == "thread/resume"
        ]
        assert resume_requests == [
            {
                "threadId": "thread-c01",
                "cwd": str(ROOT),
                "approvalPolicy": "never",
                "sandbox": "workspace-write",
            }
        ]
        assert [method for method, _ in resumed_fake.requests].count("thread/start") == 0
        assert [method for method, _ in resumed_fake.requests].count("thread/name/set") == 0
    finally:
        resumed_controller.close()


def test_controller_recovers_persisted_active_writer_git_failure(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    stage_ids = [
        stage["id"]
        for stage in roadmap.load_catalog(ROOT / "tools" / "roadmap_controller" / "stages.json")
    ]
    store = roadmap.StateStore(state_path, stage_ids)
    original_error = "thread/resume failed (-32600): thread thread-c01 already has an active writer"

    def seed_conflict(run: dict[str, Any]) -> None:
        run.update(
            {
                "runStatus": "completed",
                "attempt": 1,
                "threadId": "thread-c01",
                "turnId": "turn-tech",
                "model": "gpt-5.6-sol",
                "reasoningEffort": "ultra",
                "executionSource": "actual",
                "result": {"outcome": "passed"},
            }
        )
        run["git"].update(
            {
                "status": "failed",
                "attempt": 2,
                "threadId": "thread-c01",
                "turnId": None,
                "model": "gpt-5.6-sol",
                "reasoningEffort": "ultra",
                "executionSource": "planned",
                "error": original_error,
            }
        )

    store.update_stage("C01", seed_conflict)
    controller, fake = _controller(tmp_path)
    try:
        checkpoint = controller.store.stage("C01")["git"]
        assert checkpoint["status"] == "awaiting_approval"
        assert checkpoint["turnId"] is None
        assert checkpoint["error"] is None
        assert "Codex Desktop writer" in checkpoint["retryNotice"]
        assert checkpoint["progress"]["percent"] == 0
        assert checkpoint["history"][-1]["status"] == "failed"
        assert checkpoint["history"][-1]["error"] == original_error

        c01 = next(stage for stage in controller.snapshot()["stages"] if stage["id"] == "C01")
        assert c01["canGitCheckpoint"] is True
        assert "Другий writer не створено" in c01["gitReason"]
        assert fake.requests == []
    finally:
        controller.close()


def test_git_launch_uses_isolated_thread_even_when_technical_thread_has_writer(
    tmp_path: Path,
) -> None:
    controller, fake = _controller(tmp_path)
    try:

        def mark_passed(run: dict[str, Any]) -> None:
            run.update(
                {
                    "runStatus": "completed",
                    "attempt": 1,
                    "threadId": "thread-c01",
                    "turnId": "turn-tech",
                    "model": "gpt-5.6-sol",
                    "reasoningEffort": "ultra",
                    "executionSource": "actual",
                    "result": {"outcome": "passed"},
                }
            )
            run["git"].update(
                {
                    "status": "awaiting_approval",
                    "threadId": "thread-c01",
                }
            )

        controller.store.update_stage("C01", mark_passed)
        fake.resume_error = (
            "thread/resume failed (-32600): thread thread-c01 already has an active writer"
        )

        controller.start_git_checkpoint("C01")
        checkpoint = _wait_for_git_status(controller, "C01", "running")

        run = controller.store.stage("C01")
        checkpoint = run["git"]
        assert run["runStatus"] == "completed"
        assert checkpoint["status"] == "running"
        assert checkpoint["error"] is None
        assert checkpoint["threadId"] == "thread-c01"
        assert [method for method, _ in fake.requests].count("thread/resume") == 0
        assert [method for method, _ in fake.requests].count("thread/start") == 1
        assert [method for method, _ in fake.requests].count("turn/start") == 1

        c01 = next(stage for stage in controller.snapshot()["stages"] if stage["id"] == "C01")
        assert c01["canGitCheckpoint"] is False
    finally:
        controller.close()


def test_git_sync_is_rejected_when_controller_cannot_verify_remote(
    tmp_path: Path,
) -> None:
    controller, _fake = _controller(
        tmp_path,
        git_verifier=lambda _result: (
            False,
            "origin branch does not contain commit",
            None,
        ),
    )
    try:
        stage_result = roadmap.parse_stage_result(_valid_result(), "C01")
        assert stage_result is not None

        def mark_passed(run: dict[str, Any]) -> None:
            run["runStatus"] = "completed"
            run["result"] = stage_result
            run["git"]["status"] = "awaiting_approval"

        controller.store.update_stage("C01", mark_passed)
        controller.start_git_checkpoint("C01")
        checkpoint = _wait_for_git_status(controller, "C01", "running")
        thread_id = checkpoint["threadId"]
        turn_id = checkpoint["turnId"]
        assert isinstance(thread_id, str)
        assert isinstance(turn_id, str)
        final_message = _valid_git_result()
        controller.handle_app_server_message(
            {
                "method": "item/completed",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "completedAtMs": 1,
                    "item": {
                        "id": "item-git",
                        "type": "agentMessage",
                        "text": final_message,
                    },
                },
            }
        )
        controller.handle_app_server_message(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turn": {"id": turn_id, "status": "completed", "items": []},
                },
            }
        )

        rejected = controller.store.stage("C01")["git"]
        assert rejected["status"] == "needs_review"
        assert "origin branch" in rejected["error"]
        assert controller.snapshot()["summary"]["gitSynced"] == 0
    finally:
        controller.close()


def test_http_api_rejects_missing_token_and_cross_origin_writes(tmp_path: Path) -> None:
    controller, _fake = _controller(tmp_path)
    html_path = ROOT / "docs" / "interactive" / "varta-chat-roadmap.html"
    server = roadmap.create_http_server(
        controller,
        html_path,
        port=0,
        session_token="test-session-token",
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(f"{base}/api/v1/health", timeout=3) as response:
            assert json.load(response)["product"] == roadmap.APP_NAME

        with pytest.raises(HTTPError) as missing_token:
            urlopen(f"{base}/api/v1/roadmap", timeout=3)
        assert missing_token.value.code == 403

        roadmap_request = Request(
            f"{base}/api/v1/roadmap",
            headers={"X-Varta-Roadmap-Token": "test-session-token"},
        )
        with urlopen(roadmap_request, timeout=3) as response:
            assert len(json.load(response)["stages"]) == 25

        no_origin = Request(
            f"{base}/api/v1/stages/C01/start",
            data=b"{}",
            method="POST",
            headers={"X-Varta-Roadmap-Token": "test-session-token"},
        )
        with pytest.raises(HTTPError) as rejected_write:
            urlopen(no_origin, timeout=3)
        assert rejected_write.value.code == 403

        accepted = Request(
            f"{base}/api/v1/stages/C01/start",
            data=b"{}",
            method="POST",
            headers={
                "Origin": base,
                "X-Varta-Roadmap-Token": "test-session-token",
                "Content-Type": "application/json",
            },
        )
        with urlopen(accepted, timeout=3) as response:
            assert response.status == 202
            assert json.load(response)["stageId"] == "C01"
    finally:
        server.shutdown()
        server.server_close()
        controller.close()
        worker.join(timeout=3)


def test_http_rerun_validates_json_and_reuses_the_canonical_thread(
    tmp_path: Path,
) -> None:
    controller, fake = _controller(tmp_path)

    def mark_completed(run: dict[str, Any]) -> None:
        run.update(
            {
                "runStatus": "completed",
                "attempt": 1,
                "threadId": "thread-c01",
                "turnId": "turn-old",
                "model": "gpt-5.6-sol",
                "reasoningEffort": "ultra",
                "executionSource": "actual",
                "result": {"outcome": "passed"},
            }
        )

    controller.store.update_stage("C01", mark_completed)
    html_path = ROOT / "docs" / "interactive" / "varta-chat-roadmap.html"
    server = roadmap.create_http_server(
        controller,
        html_path,
        port=0,
        session_token="test-session-token",
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def rerun_request(data: bytes) -> Request:
        return Request(
            f"{base}/api/v1/stages/C01/rerun",
            data=data,
            method="POST",
            headers={
                "Origin": base,
                "X-Varta-Roadmap-Token": "test-session-token",
                "Content-Type": "application/json",
            },
        )

    invalid_bodies = [
        b"{",
        b"[]",
        json.dumps(
            {"model": "gpt-5.6-sol", "reasoningEffort": "ultra", "extra": True}
        ).encode(),
        json.dumps(
            {"model": "gpt-5.4-mini", "reasoningEffort": "ultra"}
        ).encode(),
    ]
    try:
        for body in invalid_bodies:
            with pytest.raises(HTTPError) as rejected:
                urlopen(rerun_request(body), timeout=3)
            assert rejected.value.code == 400

        accepted = rerun_request(
            json.dumps({"model": "gpt-6-astra", "reasoningEffort": "ultra"}).encode()
        )
        with urlopen(accepted, timeout=3) as response:
            assert response.status == 202
            assert json.load(response)["stageId"] == "C01"

        running = _wait_for_status(controller, "C01", "running")
        assert running["threadId"] == "thread-c01"
        assert fake.thread_count == 0
        assert [method for method, _ in fake.requests].count("thread/resume") == 1
        turn_request = next(
            payload for method, payload in fake.requests if method == "turn/start"
        )
        assert turn_request["model"] == "gpt-6-astra"
        assert turn_request["effort"] == "ultra"
    finally:
        server.shutdown()
        server.server_close()
        controller.close()
        worker.join(timeout=3)


def test_windows_runtime_staging_copies_only_allowlisted_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for index, name in enumerate(roadmap.WINDOWS_RUNTIME_FILES, start=1):
        (source / name).write_bytes(bytes([index]) * index)
    (source / "unrelated-secret.txt").write_text("do not copy", encoding="utf-8")
    monkeypatch.setattr(roadmap, "_executable_works", lambda _path: True)

    executable = roadmap.stage_windows_runtime(source / "codex.exe", tmp_path / "runtime")

    assert executable.name == "codex.exe"
    assert {path.name for path in executable.parent.iterdir()} == set(
        roadmap.WINDOWS_RUNTIME_FILES
    )
    assert not (executable.parent / "unrelated-secret.txt").exists()


def test_task_prompt_contains_scope_and_non_publication_guards() -> None:
    stage = roadmap.load_catalog(
        ROOT / "tools" / "roadmap_controller" / "stages.json"
    )[0]
    prompt = roadmap.build_task_prompt(stage)

    assert "D:\\VARTA\\AGENTS.md" in prompt
    assert "не виконуй commit, push" in prompt
    assert "не починай наступний package" in prompt
    assert "постійним і канонічним" in prompt
    assert "одну незалежно виконувану перевірку" in prompt
    assert "чинні `passed` із" in prompt
    assert "Не запускай і не виправляй тести чи файли пізнішого" in prompt
    assert "без доведеного causal link" in prompt
    assert "не включай `.varta/roadmap-controller/state.json`" in prompt
    assert '<VARTA_PROGRESS>{"stage_id":"C01","kind":"stage"' in prompt
    assert '<VARTA_STAGE_RESULT>{"stage_id":"C01"' in prompt

    resume_prompt = roadmap.build_task_prompt(stage, resume_from_checkpoint=True)
    assert "Не повторюй passed" in resume_prompt
    assert "Після failure/resume запускай лише" in resume_prompt


def test_git_checkpoint_prompt_is_exact_path_public_draft_pr_only() -> None:
    stage = roadmap.load_catalog(
        ROOT / "tools" / "roadmap_controller" / "stages.json"
    )[0]
    run = roadmap.StateStore._blank_stage()
    run["result"] = roadmap.parse_stage_result(_valid_result(), "C01")
    run["gitBaseline"] = {
        "head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "branch": "codex/stabilize-baseline",
        "status": [],
    }

    prompt = roadmap.build_git_checkpoint_prompt(stage, run)

    assert "прямою командою" in prompt
    assert "git add -- <paths>" in prompt
    assert "Ніколи не" in prompt
    assert "публічний mixa4y/varta" in prompt
    assert '"visibility":"PUBLIC"' in prompt
    assert "Draft PR" in prompt
    assert "Не merge" in prompt
    assert "ізольований механічний Git worker" in prompt
    assert "Не шукай, не читай" in prompt
    assert "`commit_created=false` і `staged_files=[]`" in prompt
    assert "manifest наявного commit наведи лише в checks/evidence" in prompt
    assert "`pushed` описує postcondition" in prompt
    assert "став `pushed=true`" in prompt
    assert '<VARTA_PROGRESS>{"stage_id":"C01","kind":"git"' in prompt
    assert '<VARTA_GIT_RESULT>{"stage_id":"C01"' in prompt
