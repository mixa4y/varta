from __future__ import annotations

import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from .errors import ReparsePointError, UnsafePathError, WorkspaceLayoutError


LAYOUT_VERSION = 1
LAYOUT_CONTRACT = "varta.managed-workspace"
LAYOUT_ZONES = (
    "database",
    "originals",
    "staging",
    "working",
    "derived",
    "reports",
    "exports",
    "logs",
    "backups",
    "quarantine",
    "temp",
)

_INVALID_WINDOWS_CHARS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
_STORAGE_REFERENCE = re.compile(
    r"^originals/v1/(?P<partition>[0-9a-f]{2})/"
    r"(?P<file_id>[0-9a-f-]{36})/original\.bin$"
)


def native_path(path: Path) -> str:
    """Return a Windows extended path while keeping normal paths elsewhere."""

    absolute = os.path.abspath(os.fspath(path))
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def is_reparse_stat(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def assert_not_reparse(path: Path) -> os.stat_result:
    try:
        metadata = os.lstat(native_path(path))
    except OSError as exc:
        raise UnsafePathError("Path component недоступний для безпечної перевірки") from exc
    if is_reparse_stat(metadata):
        raise ReparsePointError("Symlink/reparse-point traversal заборонено")
    return metadata


def assert_path_chain_not_reparse(path: Path) -> os.stat_result:
    """Check every existing component, including parents of a selected root."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    metadata = assert_not_reparse(current)
    for component in absolute.parts[1:]:
        current /= component
        metadata = assert_not_reparse(current)
    return metadata


def validate_relative_path(value: str) -> tuple[str, ...]:
    """Validate a literal Windows-relative source/archive path without normalizing it."""

    if not isinstance(value, str) or not value:
        raise UnsafePathError("Relative path не може бути порожнім")
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        raise UnsafePathError("Absolute, drive-relative та UNC paths заборонено")
    if "\x00" in value:
        raise UnsafePathError("NUL у path заборонено")

    components = re.split(r"[/\\]", value)
    if any(component in {"", ".", ".."} for component in components):
        raise UnsafePathError("Empty/dot/traversal path component заборонено")
    for component in components:
        _validate_component(component)
    return tuple(components)


def validate_archive_member_path(value: str) -> tuple[str, ...]:
    """Archive names use the same Windows-safe, traversal-free literal contract."""

    return validate_relative_path(value)


def validate_file_id(file_id: str) -> uuid.UUID:
    try:
        parsed = uuid.UUID(file_id)
    except (AttributeError, ValueError) as exc:
        raise UnsafePathError("file_id має бути canonical lowercase UUIDv4") from exc
    if parsed.version != 4 or str(parsed) != file_id:
        raise UnsafePathError("file_id має бути canonical lowercase UUIDv4")
    return parsed


def storage_reference_for(file_id: str) -> str:
    validate_file_id(file_id)
    return f"originals/v1/{file_id[:2]}/{file_id}/original.bin"


def staging_reference_for(file_id: str) -> str:
    validate_file_id(file_id)
    return f"staging/v1/{file_id}.part"


def validate_storage_reference(reference: str) -> str:
    match = _STORAGE_REFERENCE.fullmatch(reference)
    if match is None:
        raise UnsafePathError("Managed storage reference має неочікуваний формат")
    file_id = match.group("file_id")
    validate_file_id(file_id)
    if match.group("partition") != file_id[:2]:
        raise UnsafePathError("Managed storage partition не відповідає file_id")
    return file_id


def resolve_source_file(source_root: Path, source_relative_path: str) -> tuple[Path, str]:
    components = validate_relative_path(source_relative_path)
    root = Path(os.path.abspath(os.fspath(source_root)))
    root_metadata = assert_path_chain_not_reparse(root)
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise UnsafePathError("Source root має бути каталогом")

    current = root
    metadata = root_metadata
    for component in components:
        current = current / component
        metadata = assert_not_reparse(current)
    if not stat.S_ISREG(metadata.st_mode):
        raise UnsafePathError("Source entry має бути regular file")
    return current, components[-1]


def resolve_managed_reference(managed_root: Path, reference: str) -> Path:
    validate_storage_reference(reference)
    current = managed_root
    for component in reference.split("/"):
        current = current / component
        if os.path.lexists(native_path(current)):
            assert_not_reparse(current)
    return current


def _validate_component(component: str) -> None:
    if component.endswith((" ", ".")):
        raise UnsafePathError("Windows path component не може завершуватися крапкою/пробілом")
    if any(ord(char) < 32 or char in _INVALID_WINDOWS_CHARS for char in component):
        raise UnsafePathError("Windows path component містить заборонені символи")
    if len(component.encode("utf-16-le")) // 2 > 255:
        raise UnsafePathError("Windows path component перевищує 255 UTF-16 code units")
    device_name = component.split(".", maxsplit=1)[0].upper()
    if device_name in _WINDOWS_RESERVED_NAMES:
        raise UnsafePathError("Windows reserved device name заборонено")


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    workspace_root: Path
    version: int = LAYOUT_VERSION

    @property
    def managed_root(self) -> Path:
        return self.workspace_root / ".varta"

    @property
    def marker(self) -> Path:
        return self.managed_root / "layout.json"

    def zone(self, name: str) -> Path:
        if name not in LAYOUT_ZONES:
            raise WorkspaceLayoutError(f"Невідома managed zone: {name}")
        return self.managed_root / name

    def initialize(self) -> None:
        if self.version != LAYOUT_VERSION:
            raise WorkspaceLayoutError(f"Непідтримувана layout version: {self.version}")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        assert_path_chain_not_reparse(self.workspace_root)
        self.managed_root.mkdir(exist_ok=True)
        assert_not_reparse(self.managed_root)
        for name in LAYOUT_ZONES:
            zone = self.zone(name)
            zone.mkdir(exist_ok=True)
            metadata = assert_not_reparse(zone)
            if not stat.S_ISDIR(metadata.st_mode):
                raise WorkspaceLayoutError(f"Managed zone не є каталогом: {name}")
        (self.zone("staging") / "v1").mkdir(exist_ok=True)
        (self.zone("originals") / "v1").mkdir(exist_ok=True)
        self._check_same_volume()
        self._ensure_marker()

    def _check_same_volume(self) -> None:
        staging = os.stat(native_path(self.zone("staging")))
        originals = os.stat(native_path(self.zone("originals")))
        if staging.st_dev != originals.st_dev:
            raise WorkspaceLayoutError("Staging і originals мають бути на одному volume")
        if os.name == "nt":
            staging_drive = os.path.splitdrive(native_path(self.zone("staging")))[0].casefold()
            originals_drive = os.path.splitdrive(native_path(self.zone("originals")))[0].casefold()
            if staging_drive != originals_drive:
                raise WorkspaceLayoutError("Staging і originals мають бути на одному drive")

    def _ensure_marker(self) -> None:
        expected = {
            "contract": LAYOUT_CONTRACT,
            "version": self.version,
            "zones": list(LAYOUT_ZONES),
        }
        if self.marker.exists():
            assert_not_reparse(self.marker)
            try:
                actual = json.loads(self.marker.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise WorkspaceLayoutError("layout.json не читається або пошкоджений") from exc
            if actual != expected:
                raise WorkspaceLayoutError("Managed workspace layout несумісний з v1")
            return
        temporary = self.managed_root / f"layout.{uuid.uuid4()}.tmp"
        try:
            temporary.write_text(
                json.dumps(expected, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(native_path(temporary), native_path(self.marker))
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise WorkspaceLayoutError("Не вдалося зафіксувати layout.json") from exc
