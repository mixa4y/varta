import json
import unittest
from pathlib import Path

from caseflow.server import VARTA_VERSION, safe_segment


ROOT = Path(__file__).resolve().parents[1]


class SafeSegmentTests(unittest.TestCase):
    def test_server_version_comes_from_manifest(self) -> None:
        manifest = json.loads((ROOT / "caseflow" / "version.json").read_text(encoding="utf-8"))
        self.assertEqual(VARTA_VERSION, manifest["version"])

    def test_default_fallback_is_available(self) -> None:
        self.assertEqual(safe_segment(""), "БЕЗ_НАЗВИ")

    def test_invalid_path_characters_are_normalized(self) -> None:
        self.assertEqual(safe_segment('  архів: 01/02  '), "архів_ 01_02")


if __name__ == "__main__":
    unittest.main()
