from __future__ import annotations

import json
import re
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
        client_factory=factory,
        git_verifier=git_verifier
        or (lambda _result: (True, "live remote verified", "a" * 40)),
    )
    controller.bootstrap()
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
    return (
        "Людиночитний звіт.\n<VARTA_STAGE_RESULT>"
        + json.dumps(payload, ensure_ascii=False)
        + "</VARTA_STAGE_RESULT>"
    )


def _valid_git_result(stage_id: str = "C01") -> str:
    payload = {
        "stage_id": stage_id,
        "outcome": "synced",
        "summary": "Stage-owned diff опубліковано у приватну feature branch.",
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
        "visibility": "PRIVATE",
        "pr_url": "https://github.com/mixa4y/varta/pull/7",
        "gate": "Remote commit і Draft PR підтверджені.",
    }
    return (
        "Git checkpoint звіт.\n<VARTA_GIT_RESULT>"
        + json.dumps(payload, ensure_ascii=False)
        + "</VARTA_GIT_RESULT>"
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


def test_catalog_contains_all_core_and_processor_stages() -> None:
    stages = roadmap.load_catalog(ROOT / "tools" / "roadmap_controller" / "stages.json")
    ids = [stage["id"] for stage in stages]

    assert ids[:16] == [f"C{number:02d}" for number in range(1, 17)]
    assert ids[16:] == ["P01", "P02", "P03", "P04"]
    assert next(stage for stage in stages if stage["id"] == "C16")["dependencies"] == [
        f"C{number:02d}" for number in range(1, 16)
    ]
    assert all(stage["prompt"].strip() for stage in stages)


def test_html_and_machine_catalog_have_the_same_stage_ids() -> None:
    html = (ROOT / "docs" / "interactive" / "varta-chat-roadmap.html").read_text(
        encoding="utf-8"
    )
    stages = roadmap.load_catalog(ROOT / "tools" / "roadmap_controller" / "stages.json")

    html_ids = set(re.findall(r'data-stage-id="([CP]\d{2})"', html))
    assert html_ids == {stage["id"] for stage in stages}
    assert len(re.findall(r'data-stage-id="([CP]\d{2})"', html)) == 20
    assert "__VARTA_SESSION_TOKEN__" in html
    assert "start-git" in html
    assert "/git/${action}" in html
    assert "GITHUB SYNCED" in html
    assert 'id="live-execution"' in html
    assert "VARTA_PROGRESS" in html
    assert "window.setInterval(refreshRoadmap, 1000)" in html
    assert "рівно один постійний чат" in html
    assert "position: sticky" not in html
    assert "position: fixed" not in html
    assert 'id="expand-all">+ Розгорнути всі C/P' in html
    assert 'id="collapse-all">− Згорнути всі C/P' in html
    assert 'article[data-stage-id] details[open] summary .id::before' in html
    assert len(re.findall(r'<article class="satellite" data-stage-id="P\d{2}"><details>', html)) == 4
    assert 'id="execution-stats"' in html
    assert "function packagePresentation(stage)" in html
    assert "function renderExecutionStats(snapshot)" in html
    assert "function renderRoadmapFooter(snapshot)" in html
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


def test_git_result_requires_private_pushed_branch_and_draft_pr() -> None:
    valid = roadmap.parse_git_checkpoint_result(_valid_git_result(), "C01")
    assert valid is not None
    assert valid["outcome"] == "synced"
    assert valid["visibility"] == "PRIVATE"

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
    raw["visibility"] = "PUBLIC"
    invalid_visibility = (
        "<VARTA_GIT_RESULT>"
        + json.dumps(raw, ensure_ascii=False)
        + "</VARTA_GIT_RESULT>"
    )
    assert roadmap.parse_git_checkpoint_result(invalid_visibility, "C01") is None


def test_state_store_persists_atomically_and_interrupts_stale_runs(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = roadmap.StateStore(path, ["C01", "C02"])
    store.update_stage("C01", lambda stage: stage.update({"runStatus": "running"}))

    reloaded = roadmap.StateStore(path, ["C01", "C02"])
    reloaded.interrupt_stale_active_runs()

    assert reloaded.stage("C01")["runStatus"] == "interrupted"
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 1
    assert not list(tmp_path.glob("*.tmp"))


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
        assert "sandboxPolicy" not in stage_turn_start
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
        assert git_running["threadId"] == "thread-c01"
        assert git_running["turnId"] == "turn-c01-2"
        assert fake.thread_count == 1
        git_turn_start = [
            params
            for method, params in fake.requests
            if method == "turn/start" and params["threadId"] == "thread-c01"
            and params.get("sandboxPolicy") == {"type": "dangerFullAccess"}
        ][0]
        assert git_turn_start["sandboxPolicy"] == {"type": "dangerFullAccess"}
        git_prompt = git_turn_start["input"][0]["text"]
        assert "git add ." in git_prompt
        assert "Ніколи не" in git_prompt
        assert "Draft PR" in git_prompt

        git_final = _valid_git_result()
        controller.handle_app_server_message(
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thread-c01",
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
                    "threadId": "thread-c01",
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


def test_snapshot_enables_only_the_first_ready_stage_in_roadmap_order(
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

        assert enabled == ["C09"]
        assert c10["blockedBy"] == []
        assert c11["blockedBy"] == []
        assert c10["startReason"] == "За порядком roadmap спочатку запустіть C09."
        assert c11["startReason"] == "За порядком roadmap спочатку запустіть C09."
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
            assert len(json.load(response)["stages"]) == 20

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
    assert '<VARTA_PROGRESS>{"stage_id":"C01","kind":"stage"' in prompt
    assert '<VARTA_STAGE_RESULT>{"stage_id":"C01"' in prompt


def test_git_checkpoint_prompt_is_exact_path_private_draft_pr_only() -> None:
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
    assert "приватний mixa4y/varta" in prompt
    assert "Draft PR" in prompt
    assert "Не merge" in prompt
    assert "того самого постійного Codex-чату" in prompt
    assert '<VARTA_PROGRESS>{"stage_id":"C01","kind":"git"' in prompt
    assert '<VARTA_GIT_RESULT>{"stage_id":"C01"' in prompt
