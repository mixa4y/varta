from __future__ import annotations

import http.client
import json
import os
import stat
import threading
from pathlib import Path

from caseflow.server import CaseFlowState, Handler, ThreadingHTTPServer


class RunningVarta:
    def __init__(self, root: Path):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self.server.server_address[1])
        self.state = CaseFlowState(root, "127.0.0.1", self.port)
        self.state.prepare_database()
        self.server.state = self.state  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            assert isinstance(payload, dict)
            return response.status, payload
        finally:
            connection.close()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.state.close()


def _multipart(filename: str, payload: bytes) -> tuple[bytes, str]:
    boundary = "----VartaC06SyntheticBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n"
        "\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f"multipart/form-data; boundary={boundary}"


def _restore_original_permissions(root: Path) -> None:
    for original in (root / ".varta" / "originals").rglob("original.bin"):
        try:
            os.chmod(original, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass


def test_versioned_local_web_upload_replays_and_inventory_survives_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-web-workspace"
    root.mkdir()
    body, content_type = _multipart("Синтетичний файл.txt", "веб-байти".encode())
    first = RunningVarta(root)
    try:
        status, capability = first.request("GET", "/api/v1/status")
        assert status == 200
        assert capability["capabilities"] == {
            "intake": ["file", "folder", "zip"],
            "inventoryAuthority": "sqlite",
        }
        headers = {
            "Content-Type": content_type,
            "Idempotency-Key": "web-synthetic-001",
            "X-Caseflow-Token": first.state.csrf_token,
        }
        status, created = first.request(
            "POST",
            "/api/v1/intake",
            body=body,
            headers=headers,
        )
        assert status == 201
        batch = created["batch"]
        assert isinstance(batch, dict)
        assert batch["status"] == "succeeded"
        assert batch["detectedKind"] == "file"
        assert batch["counts"] == {
            "discovered": 0,
            "accepted": 1,
            "duplicate": 0,
            "failed": 0,
            "skipped": 0,
        }
        batch_id = str(batch["batchId"])
        entry = batch["entries"][0]
        assert isinstance(entry, dict)
        assert entry["literalName"] == "Синтетичний файл.txt"
        assert str(entry["sourceUri"]).startswith("upload://request/")
        assert entry["sha256"]

        status, inventory = first.request("GET", "/api/v1/intake/inventory")
        assert status == 200
        inventory_payload = inventory["inventory"]
        assert isinstance(inventory_payload, dict)
        assert inventory_payload["authority"] == "sqlite"
        assert inventory_payload["count"] == 1

        status, replayed = first.request(
            "POST",
            "/api/v1/intake",
            body=body,
            headers=headers,
        )
        assert status == 200
        replayed_batch = replayed["batch"]
        assert isinstance(replayed_batch, dict)
        assert replayed_batch["batchId"] == batch_id
        assert replayed_batch["replayed"] is True

        unsafe_body, unsafe_type = _multipart("../escape.txt", b"unsafe")
        status, unsafe = first.request(
            "POST",
            "/api/v1/intake",
            body=unsafe_body,
            headers={
                "Content-Type": unsafe_type,
                "Idempotency-Key": "web-synthetic-unsafe",
                "X-Caseflow-Token": first.state.csrf_token,
            },
        )
        assert status == 422
        assert unsafe["error"]["code"] == "request_validation_error"  # type: ignore[index]
        assert not (root / "escape.txt").exists()
        assert first.state.database_path == root / ".varta" / "database" / "varta.sqlite3"
        assert not (root / "00_INBOX").exists()
    finally:
        first.close()

    second = RunningVarta(root)
    try:
        status, restarted = second.request("GET", f"/api/v1/intake/batches/{batch_id}")
        assert status == 200
        restarted_batch = restarted["batch"]
        assert isinstance(restarted_batch, dict)
        assert restarted_batch["batchId"] == batch_id
        assert restarted_batch["status"] == "succeeded"
        status, inventory = second.request("GET", "/api/v1/intake/inventory")
        assert status == 200
        assert inventory["inventory"]["count"] == 1  # type: ignore[index]
    finally:
        second.close()
        _restore_original_permissions(root)
