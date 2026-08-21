from __future__ import annotations

import hashlib
import mimetypes
import os
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator
from urllib.parse import quote

from case_docket.application.ports import (
    IntakeSourceDiscovery,
    IntakeSourceEntry,
    MaterializedIntakeEntry,
)
from case_docket.storage import UnsafePathError, validate_archive_member_path
from case_docket.storage.paths import is_reparse_stat, native_path, validate_relative_path


_UNSUPPORTED_ARCHIVE_SUFFIXES = frozenset(
    {".7z", ".bz2", ".cab", ".gz", ".rar", ".tar", ".tgz", ".xz"}
)


@dataclass(frozen=True, slots=True)
class _MaterializationToken:
    kind: str
    source_root: Path | None = None
    source_relative_path: str | None = None
    provenance_relative_path: str | None = None
    archive_path: Path | None = None
    archive_index: int | None = None
    expected_size: int | None = None
    expected_modified_ns: int | None = None


@dataclass(frozen=True, slots=True)
class _VerificationToken:
    kind: str
    source: Path
    snapshot: tuple[int, int, str] | str


class IntakeSourceChangedError(RuntimeError):
    """The read-only source no longer matches metadata captured at discovery."""


class FilesystemIntakeSource:
    """Enumerate local file/folder/top-level ZIP inputs without mutating them."""

    def __init__(self, temporary_root: Path, *, chunk_size: int = 1024 * 1024):
        if chunk_size < 1:
            raise ValueError("chunk_size має бути додатним")
        self._temporary_root = temporary_root
        self._temporary_root.mkdir(parents=True, exist_ok=True)
        self._chunk_size = chunk_size

    def discover(self, source: Path, source_uri: str) -> IntakeSourceDiscovery:
        absolute = Path(os.path.abspath(os.fspath(source)))
        try:
            metadata = os.lstat(native_path(absolute))
        except OSError:
            return IntakeSourceDiscovery(
                detected_kind=None,
                entries=(),
                error_code="source_unavailable",
                error_message="Source input не читається або не існує",
            )
        if is_reparse_stat(metadata):
            return self._single_source_failure(
                absolute,
                source_uri,
                "source_reparse_point",
                "Source input є symlink/reparse point і не приймається",
            )
        if stat.S_ISDIR(metadata.st_mode):
            return self._discover_folder(absolute, source_uri)
        if not stat.S_ISREG(metadata.st_mode):
            return self._single_source_failure(
                absolute,
                source_uri,
                "source_not_regular",
                "Source input не є regular file або directory",
            )

        snapshot = self._file_snapshot(absolute)
        verification = (
            _VerificationToken("file", absolute, snapshot) if snapshot is not None else None
        )
        suffix = absolute.suffix.casefold()
        if suffix == ".zip":
            return self._discover_zip(absolute, source_uri, verification)
        if suffix in _UNSUPPORTED_ARCHIVE_SUFFIXES:
            entry = self._file_entry(
                absolute,
                source_uri,
                ordinal=0,
                entry_kind="archive",
                terminal_status="skipped",
                error_code="unsupported_archive_format",
                error_message="Цей archive format не має підтвердженої C06 capability",
            )
            return IntakeSourceDiscovery(
                detected_kind="file",
                entries=(entry,),
                verification_token=verification,
            )
        return IntakeSourceDiscovery(
            detected_kind="file",
            entries=(self._file_entry(absolute, source_uri, ordinal=0),),
            verification_token=verification,
        )

    @contextmanager
    def materialize(self, entry: IntakeSourceEntry) -> Iterator[MaterializedIntakeEntry]:
        token = entry.materialization_token
        if not isinstance(token, _MaterializationToken):
            raise ValueError("Intake entry не має materialization token")
        if token.kind == "file":
            if (
                token.source_root is None
                or token.source_relative_path is None
                or token.provenance_relative_path is None
            ):
                raise ValueError("File materialization token неповний")
            source_path = token.source_root.joinpath(
                *token.source_relative_path.replace("\\", "/").split("/")
            )
            metadata = os.stat(native_path(source_path), follow_symlinks=False)
            if (
                is_reparse_stat(metadata)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size != token.expected_size
                or metadata.st_mtime_ns != token.expected_modified_ns
            ):
                raise IntakeSourceChangedError(
                    "Source entry змінився між discovery та materialization"
                )
            yield MaterializedIntakeEntry(
                source_root=token.source_root,
                source_relative_path=token.source_relative_path,
                provenance_relative_path=token.provenance_relative_path,
            )
            return
        if token.kind != "zip" or token.archive_path is None or token.archive_index is None:
            raise ValueError("Непідтримуваний materialization token")
        if token.provenance_relative_path is None:
            raise ValueError("ZIP materialization token не має provenance path")

        with tempfile.TemporaryDirectory(prefix="entry_", dir=self._temporary_root) as folder:
            source_root = Path(folder)
            relative_path = "payload.bin"
            destination = source_root / relative_path
            with zipfile.ZipFile(native_path(token.archive_path), "r") as archive:
                infos = archive.infolist()
                if token.archive_index >= len(infos):
                    raise zipfile.BadZipFile("Archive member index changed")
                info = infos[token.archive_index]
                with archive.open(info, "r") as input_stream, destination.open("xb") as output_stream:
                    while True:
                        block = input_stream.read(self._chunk_size)
                        if not block:
                            break
                        output_stream.write(block)
                    output_stream.flush()
                    os.fsync(output_stream.fileno())
            yield MaterializedIntakeEntry(
                source_root=source_root,
                source_relative_path=relative_path,
                provenance_relative_path=token.provenance_relative_path,
            )

    def source_is_unchanged(self, discovery: IntakeSourceDiscovery) -> bool:
        token = discovery.verification_token
        if token is None:
            return True
        if not isinstance(token, _VerificationToken):
            return False
        if token.kind == "folder":
            return self._folder_snapshot(token.source) == token.snapshot
        return self._file_snapshot(token.source) == token.snapshot

    def _discover_folder(self, root: Path, source_uri: str) -> IntakeSourceDiscovery:
        entries: list[IntakeSourceEntry] = []
        ordinal = 0
        stack: list[tuple[str, Path]] = [("", root)]
        while stack:
            prefix, directory = stack.pop()
            try:
                children = sorted(
                    os.scandir(native_path(directory)),
                    key=lambda item: (item.name.casefold(), item.name),
                )
            except OSError:
                relative = prefix or root.name or "(root)"
                entries.append(
                    self._terminal_entry(
                        ordinal,
                        self._joined_uri(source_uri, relative),
                        relative,
                        self._literal_name(relative),
                        "directory",
                        "failed",
                        "source_directory_unreadable",
                        "Source directory не вдалося прочитати",
                    )
                )
                ordinal += 1
                continue
            for child in children:
                relative = f"{prefix}/{child.name}" if prefix else child.name
                child_path = directory / child.name
                try:
                    metadata = child.stat(follow_symlinks=False)
                except OSError:
                    entries.append(
                        self._terminal_entry(
                            ordinal,
                            self._joined_uri(source_uri, relative),
                            relative,
                            child.name,
                            "special",
                            "failed",
                            "source_entry_unreadable",
                            "Source entry metadata не вдалося прочитати",
                        )
                    )
                    ordinal += 1
                    continue
                if is_reparse_stat(metadata):
                    entries.append(
                        self._terminal_entry(
                            ordinal,
                            self._joined_uri(source_uri, relative),
                            relative,
                            child.name,
                            "special",
                            "skipped",
                            "source_reparse_point",
                            "Symlink/reparse source entry не приймається",
                        )
                    )
                    ordinal += 1
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    stack.append((relative, child_path))
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    entries.append(
                        self._terminal_entry(
                            ordinal,
                            self._joined_uri(source_uri, relative),
                            relative,
                            child.name,
                            "special",
                            "skipped",
                            "source_special_entry",
                            "Непідтримуваний special source entry пропущено",
                        )
                    )
                    ordinal += 1
                    continue
                entries.append(
                    self._folder_file_entry(
                        root,
                        relative,
                        source_uri,
                        ordinal,
                        metadata,
                    )
                )
                ordinal += 1
        entries.sort(key=lambda item: item.ordinal)
        snapshot = self._folder_snapshot(root)
        return IntakeSourceDiscovery(
            detected_kind="folder",
            entries=tuple(entries),
            error_code="empty_input" if not entries else None,
            error_message="Source folder не містить entries" if not entries else None,
            verification_token=_VerificationToken("folder", root, snapshot),
        )

    def _discover_zip(
        self,
        archive_path: Path,
        source_uri: str,
        verification: _VerificationToken | None,
    ) -> IntakeSourceDiscovery:
        try:
            with zipfile.ZipFile(native_path(archive_path), "r") as archive:
                infos = archive.infolist()
        except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
            failed = self._file_entry(
                archive_path,
                source_uri,
                ordinal=0,
                entry_kind="archive",
                terminal_status="failed",
                error_code="corrupt_zip",
                error_message="ZIP central directory не читається",
            )
            return IntakeSourceDiscovery(
                detected_kind="zip",
                entries=(failed,),
                error_code="corrupt_zip",
                error_message="ZIP archive пошкоджений або непідтримуваний",
                verification_token=verification,
            )

        entries: list[IntakeSourceEntry] = []
        seen: set[str] = set()
        for index, info in enumerate(infos):
            raw_name = info.filename
            directory_name = raw_name.rstrip("/\\")
            try:
                components = validate_archive_member_path(
                    directory_name if info.is_dir() else raw_name
                )
                relative = "/".join(components)
                literal_name = components[-1]
            except UnsafePathError:
                relative = raw_name or "(empty-member)"
                entries.append(
                    self._zip_terminal_entry(
                        index,
                        source_uri,
                        relative,
                        self._literal_name(relative),
                        "directory" if info.is_dir() else "zip_member",
                        info,
                        "failed",
                        "unsafe_archive_path",
                        "ZIP member path порушує Windows/traversal policy",
                    )
                )
                continue

            if info.is_dir():
                entries.append(
                    self._zip_terminal_entry(
                        index,
                        source_uri,
                        relative,
                        literal_name,
                        "directory",
                        info,
                        "skipped",
                        "archive_directory",
                        "Directory member не є immutable original",
                    )
                )
                continue
            collision_key = relative.casefold()
            if collision_key in seen:
                entries.append(
                    self._zip_terminal_entry(
                        index,
                        source_uri,
                        relative,
                        literal_name,
                        "zip_member",
                        info,
                        "skipped",
                        "duplicate_archive_member",
                        "Повторний ZIP member path не перезаписується",
                    )
                )
                continue
            seen.add(collision_key)
            if info.flag_bits & 0x1:
                entries.append(
                    self._zip_terminal_entry(
                        index,
                        source_uri,
                        relative,
                        literal_name,
                        "zip_member",
                        info,
                        "failed",
                        "encrypted_archive_member",
                        "Encrypted ZIP member не підтримується у C06 v1",
                    )
                )
                continue
            unix_mode = (info.external_attr >> 16) & 0o170000
            if unix_mode == stat.S_IFLNK:
                entries.append(
                    self._zip_terminal_entry(
                        index,
                        source_uri,
                        relative,
                        literal_name,
                        "special",
                        info,
                        "skipped",
                        "archive_special_entry",
                        "Archive symlink/special entry не матеріалізується",
                    )
                )
                continue
            extension, media_type, type_hint = self._type_hints(literal_name, nested=True)
            entries.append(
                IntakeSourceEntry(
                    ordinal=index,
                    source_uri=self._zip_uri(source_uri, relative),
                    source_relative_path=relative,
                    literal_name=literal_name,
                    entry_kind="zip_member",
                    size_bytes=info.file_size,
                    source_created_at=None,
                    source_modified_at=self._zip_timestamp(info),
                    extension=extension,
                    media_type=media_type,
                    type_hint=type_hint,
                    materialization_token=_MaterializationToken(
                        kind="zip",
                        archive_path=archive_path,
                        archive_index=index,
                        provenance_relative_path=relative,
                    ),
                )
            )
        return IntakeSourceDiscovery(
            detected_kind="zip",
            entries=tuple(entries),
            error_code="empty_input" if not entries else None,
            error_message="ZIP archive не містить entries" if not entries else None,
            verification_token=verification,
        )

    def _file_entry(
        self,
        source: Path,
        source_uri: str,
        *,
        ordinal: int,
        entry_kind: str = "file",
        terminal_status: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> IntakeSourceEntry:
        try:
            metadata = os.lstat(native_path(source))
        except OSError:
            metadata = None
        relative = source.name or "(source)"
        try:
            components = validate_relative_path(relative)
            provenance = "/".join(components)
            literal_name = components[-1]
        except UnsafePathError:
            provenance = relative
            literal_name = self._literal_name(relative)
            terminal_status = "failed"
            error_code = "unsafe_source_path"
            error_message = "Source filename порушує Windows path policy"
        extension, media_type, type_hint = self._type_hints(literal_name)
        return IntakeSourceEntry(
            ordinal=ordinal,
            source_uri=source_uri,
            source_relative_path=provenance,
            literal_name=literal_name,
            entry_kind=entry_kind,
            size_bytes=metadata.st_size if metadata is not None else None,
            source_created_at=self._created_at(metadata),
            source_modified_at=self._modified_at(metadata),
            extension=extension,
            media_type=media_type,
            type_hint=type_hint,
            terminal_status=terminal_status,
            error_code=error_code,
            error_message=error_message,
            materialization_token=(
                _MaterializationToken(
                    kind="file",
                    source_root=source.parent,
                    source_relative_path=source.name,
                    provenance_relative_path=provenance,
                    expected_size=metadata.st_size if metadata is not None else None,
                    expected_modified_ns=(
                        metadata.st_mtime_ns if metadata is not None else None
                    ),
                )
                if terminal_status is None
                else None
            ),
        )

    def _folder_file_entry(
        self,
        root: Path,
        relative: str,
        source_uri: str,
        ordinal: int,
        metadata: os.stat_result,
    ) -> IntakeSourceEntry:
        try:
            components = validate_relative_path(relative)
        except UnsafePathError:
            return self._terminal_entry(
                ordinal,
                self._joined_uri(source_uri, relative),
                relative,
                self._literal_name(relative),
                "file",
                "failed",
                "unsafe_source_path",
                "Source relative path порушує Windows path policy",
                metadata,
            )
        provenance = "/".join(components)
        literal_name = components[-1]
        extension, media_type, type_hint = self._type_hints(literal_name)
        return IntakeSourceEntry(
            ordinal=ordinal,
            source_uri=self._joined_uri(source_uri, provenance),
            source_relative_path=provenance,
            literal_name=literal_name,
            entry_kind="file",
            size_bytes=metadata.st_size,
            source_created_at=self._created_at(metadata),
            source_modified_at=self._modified_at(metadata),
            extension=extension,
            media_type=media_type,
            type_hint=type_hint,
            materialization_token=_MaterializationToken(
                kind="file",
                source_root=root,
                source_relative_path=provenance,
                provenance_relative_path=provenance,
                expected_size=metadata.st_size,
                expected_modified_ns=metadata.st_mtime_ns,
            ),
        )

    def _single_source_failure(
        self,
        source: Path,
        source_uri: str,
        error_code: str,
        error_message: str,
    ) -> IntakeSourceDiscovery:
        entry = self._terminal_entry(
            0,
            source_uri,
            source.name or "(source)",
            source.name or "(source)",
            "special",
            "failed",
            error_code,
            error_message,
        )
        return IntakeSourceDiscovery(
            detected_kind=None,
            entries=(entry,),
            error_code=error_code,
            error_message=error_message,
        )

    def _zip_terminal_entry(
        self,
        ordinal: int,
        source_uri: str,
        relative: str,
        literal_name: str,
        entry_kind: str,
        info: zipfile.ZipInfo,
        status: str,
        error_code: str,
        error_message: str,
    ) -> IntakeSourceEntry:
        extension, media_type, type_hint = self._type_hints(literal_name, nested=True)
        return IntakeSourceEntry(
            ordinal=ordinal,
            source_uri=self._zip_uri(source_uri, relative),
            source_relative_path=relative,
            literal_name=literal_name,
            entry_kind=entry_kind,
            size_bytes=info.file_size,
            source_created_at=None,
            source_modified_at=self._zip_timestamp(info),
            extension=extension,
            media_type=media_type,
            type_hint=type_hint,
            terminal_status=status,
            error_code=error_code,
            error_message=error_message,
        )

    def _terminal_entry(
        self,
        ordinal: int,
        source_uri: str,
        relative: str,
        literal_name: str,
        entry_kind: str,
        status: str,
        error_code: str,
        error_message: str,
        metadata: os.stat_result | None = None,
    ) -> IntakeSourceEntry:
        extension, media_type, type_hint = self._type_hints(literal_name)
        return IntakeSourceEntry(
            ordinal=ordinal,
            source_uri=source_uri,
            source_relative_path=relative,
            literal_name=literal_name,
            entry_kind=entry_kind,
            size_bytes=metadata.st_size if metadata is not None else None,
            source_created_at=self._created_at(metadata),
            source_modified_at=self._modified_at(metadata),
            extension=extension,
            media_type=media_type,
            type_hint=type_hint,
            terminal_status=status,
            error_code=error_code,
            error_message=error_message,
        )

    def _file_snapshot(self, path: Path) -> tuple[int, int, str] | None:
        try:
            before = os.stat(native_path(path), follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or is_reparse_stat(before):
                return None
            digest = hashlib.sha256()
            with open(native_path(path), "rb") as stream:
                for block in iter(lambda: stream.read(self._chunk_size), b""):
                    digest.update(block)
            after = os.stat(native_path(path), follow_symlinks=False)
        except OSError:
            return None
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return None
        return before.st_size, before.st_mtime_ns, digest.hexdigest()

    def _folder_snapshot(self, root: Path) -> str:
        digest = hashlib.sha256()
        stack: list[tuple[str, Path]] = [("", root)]
        while stack:
            prefix, directory = stack.pop()
            try:
                children = sorted(
                    os.scandir(native_path(directory)),
                    key=lambda item: (item.name.casefold(), item.name),
                    reverse=True,
                )
            except OSError as exc:
                digest.update(f"E:{prefix}:{type(exc).__name__}\n".encode("utf-8"))
                continue
            for child in children:
                relative = f"{prefix}/{child.name}" if prefix else child.name
                digest.update(relative.encode("utf-8", errors="surrogatepass"))
                digest.update(b"\0")
                try:
                    metadata = child.stat(follow_symlinks=False)
                except OSError as exc:
                    digest.update(f"E:{type(exc).__name__}\n".encode("ascii"))
                    continue
                digest.update(f"{metadata.st_mode}:{metadata.st_size}:{metadata.st_mtime_ns}\n".encode("ascii"))
                if is_reparse_stat(metadata):
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    stack.append((relative, directory / child.name))
                elif stat.S_ISREG(metadata.st_mode):
                    snapshot = self._file_snapshot(directory / child.name)
                    digest.update((snapshot[2] if snapshot is not None else "UNREADABLE").encode("ascii"))
        return digest.hexdigest()

    @staticmethod
    def _type_hints(literal_name: str, *, nested: bool = False) -> tuple[str | None, str | None, str]:
        extension = PurePosixPath(literal_name).suffix.casefold() or None
        media_type, _ = mimetypes.guess_type(literal_name, strict=False)
        if extension == ".zip":
            type_hint = "nested_zip_not_expanded" if nested else "zip_file_not_expanded"
        elif extension in _UNSUPPORTED_ARCHIVE_SUFFIXES:
            type_hint = "archive_without_adapter"
        else:
            type_hint = "file"
        return extension, media_type, type_hint

    @staticmethod
    def _created_at(metadata: os.stat_result | None) -> str | None:
        if metadata is None:
            return None
        created = getattr(metadata, "st_birthtime", None)
        return FilesystemIntakeSource._timestamp(created) if created is not None else None

    @staticmethod
    def _modified_at(metadata: os.stat_result | None) -> str | None:
        return FilesystemIntakeSource._timestamp(metadata.st_mtime) if metadata is not None else None

    @staticmethod
    def _timestamp(value: float) -> str:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    @staticmethod
    def _zip_timestamp(info: zipfile.ZipInfo) -> str | None:
        try:
            return datetime(*info.date_time).isoformat()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _literal_name(value: str) -> str:
        normalized = value.replace("\\", "/").rstrip("/")
        return normalized.rsplit("/", 1)[-1] or "(entry)"

    @staticmethod
    def _joined_uri(base: str, relative: str) -> str:
        return f"{base.rstrip('/')}/{quote(relative, safe='/')}"

    @staticmethod
    def _zip_uri(base: str, relative: str) -> str:
        return f"zip+{base}!/{quote(relative, safe='/')}"
