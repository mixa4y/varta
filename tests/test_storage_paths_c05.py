from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from case_docket.storage import (
    LAYOUT_CONTRACT,
    LAYOUT_VERSION,
    LAYOUT_ZONES,
    ReparsePointError,
    UnsafePathError,
    WorkspaceLayout,
    resolve_source_file,
    validate_archive_member_path,
    validate_relative_path,
)


def test_workspace_layout_v1_has_explicit_same_root_zones(c05_workspace: Path) -> None:
    layout = WorkspaceLayout(c05_workspace)
    layout.initialize()

    marker = json.loads(layout.marker.read_text(encoding="utf-8"))
    assert marker == {
        "contract": LAYOUT_CONTRACT,
        "version": LAYOUT_VERSION,
        "zones": list(LAYOUT_ZONES),
    }
    for zone in (
        "originals",
        "staging",
        "working",
        "derived",
        "reports",
        "logs",
        "backups",
    ):
        assert layout.zone(zone).is_dir()
    assert os.stat(layout.zone("staging")).st_dev == os.stat(layout.zone("originals")).st_dev


@pytest.mark.parametrize(
    "unsafe",
    [
        "../escape.txt",
        "folder/../escape.txt",
        "folder/./entry.txt",
        "folder//entry.txt",
        "/absolute.txt",
        r"C:\absolute.txt",
        r"\\server\share\entry.txt",
        "folder/CON.txt",
        "folder/nul",
        "folder/LPT9.log",
        "folder/name.",
        "folder/name ",
        "folder/name:stream",
        "folder/name?.txt",
        "folder/zero\x00name.txt",
    ],
)
def test_windows_and_archive_unsafe_paths_are_rejected(unsafe: str) -> None:
    with pytest.raises(UnsafePathError):
        validate_relative_path(unsafe)
    with pytest.raises(UnsafePathError):
        validate_archive_member_path(unsafe)


def test_literal_unicode_and_long_relative_path_are_preserved_without_max_path_limit() -> None:
    components = tuple(f"Дуже-довгий-компонент-{index}-" + "я" * 60 for index in range(5))
    literal = "/".join((*components, "Оригінал № 1.PDF"))

    parsed = validate_relative_path(literal)

    assert parsed[-1] == "Оригінал № 1.PDF"
    assert "/".join(parsed) == literal
    assert len(literal) > 260


def test_source_symlink_or_reparse_escape_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "source"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    target = outside / "synthetic.txt"
    target.write_text("synthetic", encoding="utf-8")
    link = root / "linked.txt"
    try:
        link.symlink_to(target)
    except OSError:
        import case_docket.storage.paths as storage_paths

        monkeypatch.setattr(storage_paths, "is_reparse_stat", lambda metadata: True)

    with pytest.raises(ReparsePointError):
        resolve_source_file(root, "linked.txt")
