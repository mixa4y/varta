import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caseflow.server import (
    VARTA_VERSION,
    CaseFlowState,
    anomaly_summary,
    build_preflight,
    parse_multipart_form,
    run_worker,
    safe_segment,
)


ROOT = Path(__file__).resolve().parents[1]


class SafeSegmentTests(unittest.TestCase):
    def test_server_version_comes_from_manifest(self) -> None:
        manifest = json.loads((ROOT / "caseflow" / "version.json").read_text(encoding="utf-8"))
        self.assertEqual(VARTA_VERSION, manifest["version"])

    def test_default_fallback_is_available(self) -> None:
        self.assertEqual(safe_segment(""), "БЕЗ_НАЗВИ")

    def test_invalid_path_characters_are_normalized(self) -> None:
        self.assertEqual(safe_segment('  архів: 01/02  '), "архів_ 01_02")


class ServerTypingRegressionTests(unittest.TestCase):
    def test_frozen_worker_uses_package_import(self) -> None:
        with patch.object(sys, "frozen", True, create=True):
            result = run_worker(Path("caseflow_process.py"), ["--help"], ROOT, 10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Універсальний локальний конвеєр VARTA", result.stdout)

    def test_preflight_rejects_wrong_index_shape_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (
                "00_INBOX",
                "01_ОПРАЦЬОВАНО",
                "02_РОЗПАКОВАНО",
                "03_РЕЄСТР",
                "99_ПОТРЕБУЄ_ПЕРЕВІРКИ",
                ".caseflow",
            ):
                (root / relative).mkdir(parents=True)
            (root / ".caseflow" / "index.json").write_text("[]", encoding="utf-8")

            result = build_preflight(CaseFlowState(root, "127.0.0.1", 8768))

            new_input = next(item for item in result["checks"] if item["code"] == "NEW_INPUT")
            self.assertEqual(new_input["status"], "blocker")
            self.assertIn("index.json", new_input["detail"])

    def test_unknown_severity_does_not_change_risk_score(self) -> None:
        summary = anomaly_summary(
            [
                {"status": "open", "severity": "high"},
                {"status": "open", "severity": None},
                {"status": "open", "severity": "unexpected"},
                {"status": "resolved", "severity": "critical"},
            ]
        )
        self.assertEqual(summary["open"], 3)
        self.assertEqual(summary["high"], 1)
        self.assertEqual(summary["risk_score"], 40)


class MultipartFormTests(unittest.TestCase):
    def test_fields_and_multiple_files_are_parsed_without_changing_bytes(self) -> None:
        boundary = "VartaBoundary0123456789"
        binary = b"first\x00line\r\n--VartaBoundary0123456789-not-a-boundary\r\nlast"
        parts = [
            ("proceeding", None, "1_111_222_33".encode()),
            ("flow", None, "02_МОЇ_ДОКУМЕНТИ".encode("utf-8")),
            ("options", None, b'{"runOcr":true}'),
            ("files", "вкладена/доказ.bin", binary),
            ("files", "порожній.txt", b""),
        ]
        body = bytearray()
        for field, filename, payload in parts:
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            disposition = f'Content-Disposition: form-data; name="{field}"'
            if filename is not None:
                disposition += f'; filename="{filename}"'
            body.extend((disposition + "\r\n\r\n").encode("utf-8"))
            body.extend(payload)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("ascii"))

        with tempfile.TemporaryDirectory() as temporary:
            fields, files = parse_multipart_form(
                io.BytesIO(body),
                f"multipart/form-data; boundary={boundary}",
                len(body),
                Path(temporary),
            )
            self.assertEqual(fields["proceeding"], "1_111_222_33")
            self.assertEqual(fields["flow"], "02_МОЇ_ДОКУМЕНТИ")
            self.assertEqual(json.loads(fields["options"]), {"runOcr": True})
            self.assertEqual([item["filename"] for item in files], ["вкладена/доказ.bin", "порожній.txt"])
            self.assertEqual(files[0]["path"].read_bytes(), binary)
            self.assertEqual(files[0]["bytes"], len(binary))
            self.assertEqual(files[1]["path"].read_bytes(), b"")

    def test_missing_boundary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "Content-Type"):
                parse_multipart_form(
                    io.BytesIO(b"invalid"),
                    "multipart/form-data",
                    7,
                    Path(temporary),
                )


if __name__ == "__main__":
    unittest.main()
