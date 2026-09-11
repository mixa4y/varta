"""C05 managed filesystem primitives for immutable original bytes."""

from .errors import (
    ManagedStorageError,
    ManifestError,
    ReparsePointError,
    StorageCollisionError,
    StorageIOError,
    StorageIntegrityError,
    UnsafePathError,
    WorkspaceLayoutError,
)
from .filesystem import MANIFEST_CONTRACT, MANIFEST_VERSION, ManagedFilesystem
from .paths import (
    LAYOUT_CONTRACT,
    LAYOUT_VERSION,
    LAYOUT_ZONES,
    WorkspaceLayout,
    resolve_source_file,
    validate_archive_member_path,
    validate_relative_path,
)

__all__ = [
    "LAYOUT_CONTRACT",
    "LAYOUT_VERSION",
    "LAYOUT_ZONES",
    "MANIFEST_CONTRACT",
    "MANIFEST_VERSION",
    "ManagedFilesystem",
    "ManagedStorageError",
    "ManifestError",
    "ReparsePointError",
    "StorageCollisionError",
    "StorageIOError",
    "StorageIntegrityError",
    "UnsafePathError",
    "WorkspaceLayout",
    "WorkspaceLayoutError",
    "resolve_source_file",
    "validate_archive_member_path",
    "validate_relative_path",
]
