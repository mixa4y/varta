from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def c05_workspace(tmp_path: Path) -> Iterator[Path]:
    """Synthetic-only workspace whose readonly test objects remain removable by pytest."""

    workspace = tmp_path / "synthetic-workspace"
    yield workspace
    originals = workspace / ".varta" / "originals"
    if originals.exists():
        for path in originals.rglob("original.bin"):
            try:
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
            except OSError:
                pass
