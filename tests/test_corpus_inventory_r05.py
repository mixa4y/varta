from __future__ import annotations

from pathlib import Path

import pytest

from case_docket.corpus_inventory import FilesystemCorpusInventory


def test_corpus_inventory_is_stable_and_reads_unicode_extensionless_and_archive(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "synthetic-corpus"
    corpus.mkdir()
    (corpus / "без-розширення").write_bytes(b"alpha")
    (corpus / "synthetic.zip").write_bytes(b"not-expanded-here")
    nested = corpus / "nested"
    nested.mkdir()
    (nested / "document.txt").write_bytes(b"beta")

    first = FilesystemCorpusInventory(corpus).inventory()
    second = FilesystemCorpusInventory(corpus).inventory()

    assert first == second
    assert first.files == 3
    assert first.directories == 1
    assert first.unreadable == 0
    assert len(first.manifest_sha256) == 64


def test_corpus_inventory_rejects_reparse_entry_without_following_it(tmp_path: Path) -> None:
    corpus = tmp_path / "synthetic-corpus"
    corpus.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("must-not-be-read", encoding="utf-8")
    link = corpus / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    result = FilesystemCorpusInventory(corpus).inventory()
    assert result.files == 0
    assert result.unreadable == 1
