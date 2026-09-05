from __future__ import annotations

import json
from pathlib import Path

from case_docket.intake_cli import main


def test_cli_add_inventory_and_same_key_retry_share_sqlite_authority(
    c05_workspace: Path,
    capsys,
) -> None:
    source = c05_workspace.parent / "cli-synthetic.txt"
    source.write_text("synthetic CLI bytes", encoding="utf-8")
    common = ["--workspace", str(c05_workspace)]

    exit_code = main(
        [*common, "add", str(source), "--idempotency-key", "cli-synthetic-001"]
    )
    created = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert created["ok"] is True
    assert created["batch"]["status"] == "succeeded"
    batch_id = created["batch"]["batchId"]

    retry_code = main(
        [*common, "add", str(source), "--idempotency-key", "cli-synthetic-001"]
    )
    replayed = json.loads(capsys.readouterr().out)
    assert retry_code == 0
    assert replayed["batch"]["batchId"] == batch_id
    assert replayed["batch"]["replayed"] is True

    inventory_code = main([*common, "inventory", "--batch-id", batch_id])
    inventory = json.loads(capsys.readouterr().out)
    assert inventory_code == 0
    assert inventory["inventory"]["authority"] == "sqlite"
    assert inventory["inventory"]["count"] == 1
    assert inventory["inventory"]["batches"][0]["batchId"] == batch_id


def test_cli_returns_nonzero_with_persisted_corrupt_zip_failure(
    c05_workspace: Path,
    capsys,
) -> None:
    source = c05_workspace.parent / "cli-corrupt.zip"
    source.write_bytes(b"not a zip")

    exit_code = main(
        [
            "--workspace",
            str(c05_workspace),
            "add",
            str(source),
            "--idempotency-key",
            "cli-corrupt-001",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert result["ok"] is True
    assert result["batch"]["status"] == "failed"
    assert result["batch"]["entries"][0]["error"]["code"] == "corrupt_zip"
