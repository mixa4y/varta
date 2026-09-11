from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from case_docket.application.case_database_import_ports import (
    CorpusInventoryEntry,
    CorpusInventorySummary,
)
from case_docket.storage.paths import is_reparse_stat, native_path


class CorpusInventoryError(RuntimeError):
    """Raised when a read-only corpus cannot be inventoried safely."""


@dataclass(frozen=True, slots=True)
class FilesystemCorpusInventory:
    root: Path
    chunk_size: int = 1024 * 1024

    def __post_init__(self) -> None:
        if self.chunk_size < 1:
            raise ValueError("chunk_size має бути додатним")

    def inventory(self) -> CorpusInventorySummary:
        root = Path(os.path.abspath(os.fspath(self.root)))
        try:
            root_stat = os.lstat(native_path(root))
        except OSError as exc:
            raise CorpusInventoryError("Corpus root недоступний") from exc
        if not stat.S_ISDIR(root_stat.st_mode) or is_reparse_stat(root_stat):
            raise CorpusInventoryError("Corpus root має бути звичайним directory")

        manifest = hashlib.sha256()
        files = 0
        directories = 0
        unreadable = 0
        discovered = 0
        inventory_entries: list[CorpusInventoryEntry] = []
        stack: list[tuple[str, Path]] = [("", root)]
        while stack:
            prefix, directory = stack.pop()
            try:
                entries = sorted(
                    os.scandir(native_path(directory)),
                    key=lambda item: (item.name.casefold(), item.name),
                    reverse=True,
                )
            except OSError:
                unreadable += 1
                manifest.update(f"unreadable-directory:{prefix}\n".encode("utf-8"))
                continue
            for entry in entries:
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                discovered += 1
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    unreadable += 1
                    manifest.update(relative.encode("utf-8", errors="surrogatepass"))
                    manifest.update(b"\0unreadable-entry\n")
                    continue
                manifest.update(relative.encode("utf-8", errors="surrogatepass"))
                manifest.update(b"\0")
                if is_reparse_stat(metadata):
                    unreadable += 1
                    manifest.update(b"reparse-rejected\n")
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    directories += 1
                    manifest.update(b"directory\n")
                    stack.append((relative, directory / entry.name))
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    unreadable += 1
                    manifest.update(b"special-rejected\n")
                    continue
                files += 1
                digest = self._hash_stable_file(directory / entry.name, metadata)
                if digest is None:
                    unreadable += 1
                    manifest.update(b"unstable-or-unreadable\n")
                    continue
                manifest.update(f"file:{metadata.st_size}:{digest}\n".encode("ascii"))
                inventory_entries.append(
                    CorpusInventoryEntry(
                        relative_path=relative.replace("\\", "/"),
                        size_bytes=int(metadata.st_size),
                        sha256=digest,
                    )
                )
        return CorpusInventorySummary(
            manifest_sha256=manifest.hexdigest(),
            discovered=discovered,
            files=files,
            directories=directories,
            unreadable=unreadable,
            entries=tuple(sorted(inventory_entries, key=lambda item: item.relative_path)),
        )

    def _hash_stable_file(self, path: Path, before: os.stat_result) -> str | None:
        digest = hashlib.sha256()
        try:
            with open(native_path(path), "rb") as stream:
                for block in iter(lambda: stream.read(self.chunk_size), b""):
                    digest.update(block)
            after = os.stat(native_path(path), follow_symlinks=False)
        except OSError:
            return None
        if is_reparse_stat(after) or not stat.S_ISREG(after.st_mode):
            return None
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return None
        return digest.hexdigest()
