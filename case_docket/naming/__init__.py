"""Безпечне найменування людиночитних експортів.

Модуль не перейменовує оригінали й не визначає їхні фізичні ключі.
Оригінальна назва має зберігатися в БД, а кероване сховище — будуватися
зі стабільного ``file_id``. Функції нижче призначені лише для export/report.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import PurePath
from string import Formatter
from typing import Collection

DEFAULT_EXPORT_TEMPLATE = "{date}_{name}"
MAX_WINDOWS_FILENAME_LENGTH = 240

_ALLOWED_FIELDS = frozenset({"date", "proceeding", "category", "doc_type", "name", "seq"})
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
_SEPARATORS_RE = re.compile(r"[\s._-]+")
_INVALID_WINDOWS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_BASE_TRANSLITERATION = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d",
    "е": "e", "ж": "zh", "з": "z", "и": "y", "і": "i", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ь": "", "ʼ": "", "’": "",
    "'": "", "`": "",
}
_CONTEXTUAL_TRANSLITERATION = {
    "є": ("ye", "ie"),
    "ї": ("yi", "i"),
    "й": ("y", "i"),
    "ю": ("yu", "iu"),
    "я": ("ya", "ia"),
}


def _match_case(source: str, transliterated: str) -> str:
    if source.isupper() or source.istitle():
        return transliterated[:1].upper() + transliterated[1:]
    return transliterated


def transliterate_kmu55(value: str) -> str:
    """Транслітерує український текст за таблицею постанови КМУ №55.

    Контекстні літери ``Є/Ї/Й/Ю/Я`` обробляються на початку кожного слова,
    а сполука ``Зг`` передається як ``Zgh``.
    """
    result: list[str] = []
    index = 0
    word_start = True

    while index < len(value):
        char = value[index]
        lower = char.lower()
        next_lower = value[index + 1].lower() if index + 1 < len(value) else ""

        if lower == "з" and next_lower == "г":
            pair = value[index : index + 2]
            transliterated = "zgh"
            if pair.isupper():
                transliterated = "ZGH"
            elif pair[0].isupper():
                transliterated = "Zgh"
            result.append(transliterated)
            word_start = False
            index += 2
            continue

        if lower in _CONTEXTUAL_TRANSLITERATION:
            transliterated = _CONTEXTUAL_TRANSLITERATION[lower][0 if word_start else 1]
            result.append(_match_case(char, transliterated))
            word_start = False
        elif lower in _BASE_TRANSLITERATION:
            result.append(_match_case(char, _BASE_TRANSLITERATION[lower]))
            if lower not in {"ь", "ʼ", "’", "'", "`"}:
                word_start = False
        else:
            result.append(char)
            word_start = not char.isalnum()
        index += 1

    return "".join(result)


def sanitize_component(value: str, *, fallback: str = "untitled") -> str:
    """Повертає ASCII-компонент, безпечний для назви файла у Windows."""
    normalized = unicodedata.normalize("NFKC", value).strip()
    transliterated = transliterate_kmu55(normalized)
    ascii_value = unicodedata.normalize("NFKD", transliterated).encode("ascii", "ignore").decode()
    cleaned = _INVALID_WINDOWS_RE.sub("_", ascii_value)
    cleaned = _SEPARATORS_RE.sub("_", cleaned).strip(" ._").lower()
    cleaned = cleaned or fallback
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def _validate_template(template: str) -> None:
    fields = {field for _, field, _, _ in Formatter().parse(template) if field}
    unknown = fields - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Непідтримувані поля шаблону: {sorted(unknown)}")
    missing = {"date", "name"} - fields
    if missing:
        raise ValueError(f"У шаблоні відсутні обов'язкові поля: {sorted(missing)}")


def _normalize_extension(extension: str) -> str:
    cleaned = sanitize_component(extension.lstrip("."), fallback="")
    if not cleaned or "_" in cleaned:
        raise ValueError(f"Некоректне розширення файла: {extension!r}")
    return cleaned


def _fit_windows_limit(stem: str, extension: str, *, max_length: int) -> str:
    suffix = f".{extension}"
    if max_length <= len(suffix) + 10:
        raise ValueError("max_length замалий для безпечної назви файла")
    filename = f"{stem}{suffix}"
    if len(filename) <= max_length:
        return filename
    digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:8]
    available = max_length - len(suffix) - len(digest) - 2
    compact_stem = stem[:available].rstrip(" ._-")
    return f"{compact_stem}--{digest}{suffix}"


@dataclass(frozen=True, slots=True)
class ExportFilenameParts:
    document_date: date
    proceeding: str
    category: str
    doc_type: str
    name: str
    sequence: int
    extension: str

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("sequence має бути додатним цілим числом")


@dataclass(frozen=True, slots=True)
class ManagedFilenameParts:
    """Коротка людиночитна назва у контексті папки справи/провадження."""

    document_date: date
    name: str
    extension: str
    role: str | None = None
    sequence: int | None = None

    def __post_init__(self) -> None:
        if self.sequence is not None and self.sequence < 1:
            raise ValueError("sequence має бути додатним цілим числом або None")
        if self.sequence is not None and not self.role:
            raise ValueError("sequence потребує явно визначеної ролі файла")


def build_export_filename(
    parts: ExportFilenameParts,
    *,
    template: str = DEFAULT_EXPORT_TEMPLATE,
    max_length: int = MAX_WINDOWS_FILENAME_LENGTH,
) -> str:
    """Будує детерміновану людиночитну назву файла для експорту."""
    _validate_template(template)
    extension = _normalize_extension(parts.extension)
    values = {
        "date": parts.document_date.strftime("%Y%m%d"),
        "proceeding": sanitize_component(parts.proceeding),
        "category": sanitize_component(parts.category),
        "doc_type": sanitize_component(parts.doc_type),
        "name": sanitize_component(parts.name),
        "seq": f"{parts.sequence:03d}",
    }
    stem = _SEPARATORS_RE.sub("_", template.format(**values)).strip(" ._-")
    return _fit_windows_limit(stem, extension, max_length=max_length)


def build_managed_filename(
    parts: ManagedFilenameParts,
    *,
    max_length: int = MAX_WINDOWS_FILENAME_LENGTH,
) -> str:
    """Будує коротке ім'я без дублювання номера справи або провадження.

    Українські ``name`` і ``role`` транслітеруються за КМУ №55. Технічні
    ідентифікатори та SHA-256 навмисно не включаються до назви.
    """

    extension = _normalize_extension(parts.extension)
    components = [
        parts.document_date.strftime("%Y%m%d"),
        sanitize_component(parts.name),
    ]
    if parts.role:
        components.append(sanitize_component(parts.role))
    if parts.sequence is not None:
        components.append(f"{parts.sequence:03d}")
    return _fit_windows_limit("_".join(components), extension, max_length=max_length)


def resolve_collision(
    filename: str,
    existing_names: Collection[str],
    *,
    stable_id: str,
    max_length: int = MAX_WINDOWS_FILENAME_LENGTH,
) -> str:
    """Додає стабільний hash-суфікс, якщо ім'я вже існує (case-insensitive)."""
    existing = {name.casefold() for name in existing_names}
    if filename.casefold() not in existing:
        return filename
    if not stable_id.strip():
        raise ValueError("stable_id не може бути порожнім при колізії")

    path = PurePath(filename)
    extension = path.suffix
    stem = path.stem
    digest = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()
    for digest_length in range(8, len(digest) + 1, 4):
        suffix = f"--{digest[:digest_length]}"
        available = max_length - len(extension) - len(suffix)
        candidate = f"{stem[:available].rstrip(' ._-')}{suffix}{extension}"
        if candidate.casefold() not in existing:
            return candidate
    raise ValueError("Не вдалося детерміновано розв'язати колізію назви файла")


__all__ = [
    "DEFAULT_EXPORT_TEMPLATE",
    "ExportFilenameParts",
    "ManagedFilenameParts",
    "build_export_filename",
    "build_managed_filename",
    "resolve_collision",
    "sanitize_component",
    "transliterate_kmu55",
]
