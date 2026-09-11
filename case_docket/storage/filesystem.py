from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from case_docket.application.ports import (
    StagedOriginal,
    StorageInspection,
    StorageScan,
    StorageScanIssue,
    StoredObject,
)

from .errors import (
    ManagedStorageError,
    ManifestError,
    StorageCollisionError,
    StorageIOError,
    StorageIntegrityError,
    UnsafePathError,
)
from .paths import (
    LAYOUT_VERSION,
    WorkspaceLayout,
    assert_not_reparse,
    is_reparse_stat,
    native_path,
    resolve_managed_reference,
    resolve_source_file,
    staging_reference_for,
    storage_reference_for,
    validate_file_id,
    validate_relative_path,
    validate_storage_reference,
)


MANIFEST_CONTRACT = "varta.managed-original"
MANIFEST_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
FaultHook = Callable[[str, Path], None]


class ManagedFilesystem:
    """Same-volume staging and no-overwrite finalization for immutable originals."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        chunk_size: int = 1024 * 1024,
        fault_hook: FaultHook | None = None,
    ):
        if chunk_size < 1:
            raise ValueError("chunk_size має бути додатним")
        self.layout = WorkspaceLayout(workspace_root)
        self.layout.initialize()
        self._chunk_size = chunk_size
        self._fault_hook = fault_hook

    def prepare(
        self,
        *,
        file_id: str,
        source_root: Path,
        source_relative_path: str,
        provenance_relative_path: str | None = None,
        managed_name: str | None,
        kind: str,
        created_at: datetime,
    ) -> StagedOriginal:
        validate_file_id(file_id)
        source, source_name = resolve_source_file(source_root, source_relative_path)
        if provenance_relative_path is None:
            recorded_source_path = source_relative_path
            original_name = source_name
        else:
            provenance_components = validate_relative_path(provenance_relative_path)
            recorded_source_path = "/".join(provenance_components)
            original_name = provenance_components[-1]
        storage_reference = storage_reference_for(file_id)
        staging_reference = staging_reference_for(file_id)
        staging = self.layout.managed_root.joinpath(*staging_reference.split("/"))
        manifest = self._manifest_path(file_id)
        finalized = self.layout.managed_root.joinpath(*storage_reference.split("/"))
        if staging.exists() or manifest.exists() or finalized.parent.exists():
            raise StorageCollisionError("file_id уже має staging/finalized storage state")

        before = self._source_stat(source)
        source_created_ns = getattr(before, "st_birthtime_ns", None)
        digest = hashlib.sha256()
        byte_count = 0
        try:
            self._fault("before_source_open", source)
            with open(native_path(source), "rb") as source_stream:
                self._fault("before_stage_open", staging)
                with open(native_path(staging), "xb") as staging_stream:
                    while True:
                        chunk = source_stream.read(self._chunk_size)
                        if not chunk:
                            break
                        self._fault("before_stage_write", staging)
                        staging_stream.write(chunk)
                        digest.update(chunk)
                        byte_count += len(chunk)
                        self._fault("after_stage_write", staging)
                    staging_stream.flush()
                    os.fsync(staging_stream.fileno())
            after = self._source_stat(source)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise StorageIntegrityError("Source змінився під час streaming copy")
            staged_bytes, staged_sha256 = self._hash_file(staging)
            self._fault("before_source_recheck", source)
            source_bytes, source_sha256 = self._hash_file(source)
            confirmed = self._source_stat(source)
            if (
                byte_count != before.st_size
                or staged_bytes != byte_count
                or source_bytes != byte_count
                or staged_sha256 != digest.hexdigest()
                or source_sha256 != digest.hexdigest()
                or (confirmed.st_size, confirmed.st_mtime_ns)
                != (before.st_size, before.st_mtime_ns)
            ):
                raise StorageIntegrityError("Source/staging size/hash не відповідає source stream")
            staged = StagedOriginal(
                file_id=file_id,
                layout_version=LAYOUT_VERSION,
                storage_key=file_id,
                storage_reference=storage_reference,
                staging_reference=staging_reference,
                original_name=original_name,
                managed_name=managed_name,
                source_relative_path=recorded_source_path,
                kind=kind,
                bytes=byte_count,
                sha256=digest.hexdigest(),
                source_created_ns=int(source_created_ns) if source_created_ns is not None else None,
                source_modified_ns=int(before.st_mtime_ns),
                created_at=created_at,
            )
            self._write_manifest(staged, state="prepared")
            self._fault("after_prepare", manifest)
            return staged
        except ManagedStorageError:
            self._safe_unlink(staging)
            raise
        except OSError as exc:
            self._safe_unlink(staging)
            raise StorageIOError(
                f"Streaming copy не завершено: {type(exc).__name__}"
            ) from exc

    def finalize(self, staged: StagedOriginal) -> StoredObject:
        validate_file_id(staged.file_id)
        expected_reference = storage_reference_for(staged.file_id)
        expected_staging = staging_reference_for(staged.file_id)
        if (
            staged.storage_reference != expected_reference
            or staged.staging_reference != expected_staging
            or staged.storage_key != staged.file_id
        ):
            raise ManifestError("Staged references не відповідають opaque file_id")
        manifest_record = self._load_manifest(self._manifest_path(staged.file_id))
        if manifest_record != staged:
            raise ManifestError("Recovery manifest не відповідає staged operation")

        staging = self.layout.managed_root.joinpath(*staged.staging_reference.split("/"))
        final = resolve_managed_reference(self.layout.managed_root, staged.storage_reference)
        final_parent = final.parent
        final_parent.parent.mkdir(parents=True, exist_ok=True)
        assert_not_reparse(final_parent.parent)

        if final_parent.exists():
            assert_not_reparse(final_parent)
            if final.exists():
                inspection = self.inspect(
                    staged.storage_reference,
                    expected_bytes=staged.bytes,
                    expected_sha256=staged.sha256,
                )
                if inspection.actual_bytes != staged.bytes or inspection.actual_sha256 != staged.sha256:
                    raise StorageCollisionError(
                        "Finalized storage key уже містить інші bytes"
                    )
                self._set_readonly(final)
                self._safe_unlink(staging)
                self._write_manifest(staged, state="finalized")
                return self._stored_object(staged, final)
            unexpected = [entry.name for entry in final_parent.iterdir()]
            if unexpected:
                raise StorageCollisionError("Finalized storage directory не порожній")
        else:
            try:
                final_parent.mkdir()
            except FileExistsError:
                assert_not_reparse(final_parent)

        if not staging.exists():
            raise StorageIntegrityError("Staged bytes відсутні до finalize")
        staging_metadata = assert_not_reparse(staging)
        if not stat.S_ISREG(staging_metadata.st_mode):
            raise UnsafePathError("Staging object має бути regular file")

        try:
            self._fault("before_atomic_move", staging)
            if final.exists():
                raise StorageCollisionError("Finalize не перезаписує existing original")
            # Windows os.rename is same-volume and refuses an existing destination.
            # The opaque file-id directory was claimed exclusively above, so this
            # is an atomic finalize without an overwrite-capable primitive.
            os.rename(native_path(staging), native_path(final))
            self._fault("after_atomic_move", final)
            self._set_readonly(final)
            inspection = self.inspect(
                staged.storage_reference,
                expected_bytes=staged.bytes,
                expected_sha256=staged.sha256,
            )
            if inspection.status != "verified":
                raise StorageIntegrityError("Finalized original не пройшов hash/readonly check")
            self._write_manifest(staged, state="finalized")
            return self._stored_object(staged, final)
        except ManagedStorageError:
            raise
        except OSError as exc:
            raise StorageIOError(f"Atomic finalize не завершено: {type(exc).__name__}") from exc

    def inspect(
        self,
        storage_reference: str,
        *,
        expected_bytes: int,
        expected_sha256: str,
    ) -> StorageInspection:
        if expected_bytes < 0 or _SHA256.fullmatch(expected_sha256) is None:
            raise ValueError("Expected size/SHA-256 мають бути валідними")
        try:
            target = resolve_managed_reference(self.layout.managed_root, storage_reference)
        except UnsafePathError:
            return StorageInspection("mismatch", None, None, None)
        if not target.exists():
            return StorageInspection("reference_unavailable", None, None, None)
        try:
            metadata = assert_not_reparse(target)
            if not stat.S_ISREG(metadata.st_mode):
                return StorageInspection("mismatch", None, None, None)
            self._fault("before_inspect_read", target)
            actual_bytes, actual_sha256 = self._hash_file(target)
            readonly = not bool(os.stat(native_path(target)).st_mode & stat.S_IWUSR)
        except (ManagedStorageError, OSError):
            return StorageInspection("error", None, None, None)
        status = (
            "verified"
            if actual_bytes == expected_bytes and actual_sha256 == expected_sha256 and readonly
            else "mismatch"
        )
        return StorageInspection(status, actual_bytes, actual_sha256, readonly)

    def scan(self) -> StorageScan:
        pending: list[StagedOriginal] = []
        issues: list[StorageScanIssue] = []
        staging_root = self.layout.zone("staging") / "v1"
        manifests: set[str] = set()
        for path in sorted(staging_root.glob("*.json"), key=lambda item: item.name):
            try:
                staged = self._load_manifest(path)
            except ManagedStorageError as exc:
                issues.append(
                    StorageScanIssue("invalid_manifest", self._relative(path), str(exc))
                )
                continue
            manifests.add(staged.file_id)
            pending.append(staged)

        for path in sorted(staging_root.glob("*.part"), key=lambda item: item.name):
            file_id = path.stem
            if file_id not in manifests:
                issues.append(
                    StorageScanIssue(
                        "orphan_staging_file",
                        self._relative(path),
                        "Staging bytes не мають recovery manifest",
                    )
                )

        finalized, final_issues = self._scan_finalized(recoverable_ids=manifests)
        issues.extend(final_issues)
        return StorageScan(
            pending=tuple(sorted(pending, key=lambda item: item.file_id)),
            finalized_file_ids=tuple(sorted(finalized)),
            issues=tuple(issues),
        )

    def complete(self, staged: StagedOriginal) -> bool:
        paths = (
            self.layout.managed_root.joinpath(*staged.staging_reference.split("/")),
            self._manifest_path(staged.file_id),
        )
        completed = True
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                completed = False
        return completed

    def _scan_finalized(
        self,
        *,
        recoverable_ids: set[str],
    ) -> tuple[set[str], list[StorageScanIssue]]:
        finalized: set[str] = set()
        issues: list[StorageScanIssue] = []
        root = self.layout.zone("originals") / "v1"
        for partition in sorted(root.iterdir(), key=lambda item: item.name):
            try:
                metadata = assert_not_reparse(partition)
            except ManagedStorageError as exc:
                issues.append(StorageScanIssue("unsafe_originals_entry", self._relative(partition), str(exc)))
                continue
            if not stat.S_ISDIR(metadata.st_mode) or not re.fullmatch(r"[0-9a-f]{2}", partition.name):
                issues.append(
                    StorageScanIssue(
                        "unexpected_originals_entry",
                        self._relative(partition),
                        "Originals partition має неочікуваний формат",
                    )
                )
                continue
            for object_dir in sorted(partition.iterdir(), key=lambda item: item.name):
                try:
                    validate_file_id(object_dir.name)
                    metadata = assert_not_reparse(object_dir)
                    if not stat.S_ISDIR(metadata.st_mode) or object_dir.name[:2] != partition.name:
                        raise UnsafePathError("Object directory не відповідає partition")
                    original = object_dir / "original.bin"
                    if object_dir.name in recoverable_ids and not original.exists():
                        if any(object_dir.iterdir()):
                            raise UnsafePathError(
                                "Recoverable object directory містить неочікувані entries"
                            )
                        continue
                    original_metadata = assert_not_reparse(original)
                    if not stat.S_ISREG(original_metadata.st_mode):
                        raise UnsafePathError("Finalized object не є regular file")
                    if {entry.name for entry in object_dir.iterdir()} != {"original.bin"}:
                        raise UnsafePathError("Finalized object directory містить зайві entries")
                except ManagedStorageError as exc:
                    issues.append(
                        StorageScanIssue("unsafe_finalized_object", self._relative(object_dir), str(exc))
                    )
                    continue
                finalized.add(object_dir.name)
        return finalized, issues

    def _write_manifest(self, staged: StagedOriginal, *, state: str) -> None:
        manifest = self._manifest_path(staged.file_id)
        payload = {
            "contract": MANIFEST_CONTRACT,
            "version": MANIFEST_VERSION,
            "state": state,
            "fileId": staged.file_id,
            "layoutVersion": staged.layout_version,
            "storageKey": staged.storage_key,
            "storageReference": staged.storage_reference,
            "stagingReference": staged.staging_reference,
            "originalName": staged.original_name,
            "managedName": staged.managed_name,
            "sourceRelativePath": staged.source_relative_path,
            "kind": staged.kind,
            "bytes": staged.bytes,
            "sha256": staged.sha256,
            "sourceCreatedNs": staged.source_created_ns,
            "sourceModifiedNs": staged.source_modified_ns,
            "createdAt": staged.created_at.isoformat(),
        }
        temporary = manifest.with_name(f"{manifest.name}.{uuid.uuid4()}.tmp")
        try:
            with open(native_path(temporary), "x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(native_path(temporary), native_path(manifest))
        except OSError as exc:
            self._safe_unlink(temporary)
            raise StorageIOError("Recovery manifest не вдалося записати атомарно") from exc

    def _load_manifest(self, path: Path) -> StagedOriginal:
        try:
            assert_not_reparse(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, UnsafePathError) as exc:
            raise ManifestError("Recovery manifest не читається або unsafe") from exc
        if not isinstance(payload, dict):
            raise ManifestError("Recovery manifest має бути JSON object")
        try:
            if payload["contract"] != MANIFEST_CONTRACT or payload["version"] != MANIFEST_VERSION:
                raise ManifestError("Recovery manifest має непідтримувану version")
            if payload["state"] not in {"prepared", "finalized"}:
                raise ManifestError("Recovery manifest має некоректний state")
            file_id = self._string(payload, "fileId")
            validate_file_id(file_id)
            if path != self._manifest_path(file_id):
                raise ManifestError("Manifest filename не відповідає file_id")
            source_relative_path = self._string(payload, "sourceRelativePath")
            components = validate_relative_path(source_relative_path)
            original_name = self._string(payload, "originalName")
            if original_name != components[-1]:
                raise ManifestError("Literal originalName не відповідає source path")
            storage_reference = self._string(payload, "storageReference")
            if validate_storage_reference(storage_reference) != file_id:
                raise ManifestError("storageReference не відповідає file_id")
            staging_reference = self._string(payload, "stagingReference")
            if staging_reference != staging_reference_for(file_id):
                raise ManifestError("stagingReference не відповідає file_id")
            sha256 = self._string(payload, "sha256")
            if _SHA256.fullmatch(sha256) is None:
                raise ManifestError("Manifest SHA-256 некоректний")
            bytes_value = self._integer(payload, "bytes", minimum=0)
            source_modified_ns = self._integer(payload, "sourceModifiedNs", minimum=0)
            raw_created = payload["sourceCreatedNs"]
            source_created_ns = (
                None
                if raw_created is None
                else self._checked_integer(raw_created, "sourceCreatedNs", minimum=0)
            )
            managed_name = payload["managedName"]
            if managed_name is not None and not isinstance(managed_name, str):
                raise ManifestError("managedName має бути string або null")
            created_at = datetime.fromisoformat(self._string(payload, "createdAt"))
            if created_at.tzinfo is None:
                raise ManifestError("createdAt має timezone")
            layout_version = self._integer(payload, "layoutVersion", minimum=1)
            if layout_version != LAYOUT_VERSION:
                raise ManifestError("layoutVersion не підтримується")
            storage_key = self._string(payload, "storageKey")
            if storage_key != file_id:
                raise ManifestError("storageKey не відповідає file_id")
            return StagedOriginal(
                file_id=file_id,
                layout_version=layout_version,
                storage_key=storage_key,
                storage_reference=storage_reference,
                staging_reference=staging_reference,
                original_name=original_name,
                managed_name=managed_name,
                source_relative_path=source_relative_path,
                kind=self._string(payload, "kind"),
                bytes=bytes_value,
                sha256=sha256,
                source_created_ns=source_created_ns,
                source_modified_ns=source_modified_ns,
                created_at=created_at,
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ManifestError):
                raise
            raise ManifestError("Recovery manifest має некоректні поля") from exc

    def _hash_file(self, path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        byte_count = 0
        with open(native_path(path), "rb") as stream:
            while True:
                chunk = stream.read(self._chunk_size)
                if not chunk:
                    break
                byte_count += len(chunk)
                digest.update(chunk)
        return byte_count, digest.hexdigest()

    @staticmethod
    def _source_stat(path: Path) -> os.stat_result:
        metadata = os.stat(native_path(path), follow_symlinks=False)
        if is_reparse_stat(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise UnsafePathError("Source змінився на symlink/reparse/non-file")
        return metadata

    @staticmethod
    def _set_readonly(path: Path) -> None:
        mode = os.stat(native_path(path), follow_symlinks=False).st_mode
        os.chmod(native_path(path), mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))

    @staticmethod
    def _stored_object(staged: StagedOriginal, path: Path) -> StoredObject:
        readonly = not bool(os.stat(native_path(path)).st_mode & stat.S_IWUSR)
        return StoredObject(
            file_id=staged.file_id,
            storage_key=staged.storage_key,
            storage_reference=staged.storage_reference,
            bytes=staged.bytes,
            sha256=staged.sha256,
            readonly=readonly,
        )

    def _manifest_path(self, file_id: str) -> Path:
        validate_file_id(file_id)
        return self.layout.zone("staging") / "v1" / f"{file_id}.json"

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.layout.managed_root).as_posix()

    def _fault(self, event: str, path: Path) -> None:
        if self._fault_hook is not None:
            self._fault_hook(event, path)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _string(payload: dict[str, Any], key: str) -> str:
        value = payload[key]
        if not isinstance(value, str) or not value:
            raise ManifestError(f"{key} має бути non-empty string")
        return value

    @classmethod
    def _integer(cls, payload: dict[str, Any], key: str, *, minimum: int) -> int:
        return cls._checked_integer(payload[key], key, minimum=minimum)

    @staticmethod
    def _checked_integer(value: object, key: str, *, minimum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ManifestError(f"{key} має бути integer >= {minimum}")
        return value
