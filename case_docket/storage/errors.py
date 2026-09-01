from __future__ import annotations


class ManagedStorageError(RuntimeError):
    """Base error for safe managed-filesystem operations."""


class UnsafePathError(ManagedStorageError):
    """A source, archive, or managed path violates the Windows path contract."""


class ReparsePointError(UnsafePathError):
    """A path would traverse a symlink or Windows reparse point."""


class StorageCollisionError(ManagedStorageError):
    """A storage key or finalized target already contains different bytes."""


class StorageIntegrityError(ManagedStorageError):
    """Copied or finalized bytes do not match the expected size/hash."""


class StorageIOError(ManagedStorageError):
    """An explicit filesystem read/write/finalize failure."""


class WorkspaceLayoutError(ManagedStorageError):
    """The managed workspace layout is missing, unsafe, or incompatible."""


class ManifestError(ManagedStorageError):
    """A recovery manifest is malformed or inconsistent with its path."""
