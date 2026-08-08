"""
case_docket.dictionaries
=========================
Единий, генералізований шар довідників (Патч 1) для будь-якої судової справи.

Жодних значень, специфічних для конкретної справи, тут немає — лише
контрольовані словники кодів, які використовуються по всьому конвеєру:
найменування файлів, модель документа, compliance-перевірка, звірка версій.

Використання
------------
    from case_docket import dictionaries as dct

    dct.is_valid("category", "atch")            # True
    dct.label("doc_type_main", "ruling")          # "Ухвала"
    dct.codes("workflow_status")                   # ['submitted', 'registered', ...]
    dct.default_severity("undeclared_attachment")   # "falsification_risk"
    dct.list_dictionaries()                          # усі доступні назви словників
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DICT_DIR = Path(__file__).parent / "dictionaries"

# Реєстр: логічна назва словника -> файл у /dictionaries
_REGISTRY: dict[str, str] = {
    "category": "category.json",
    "doc_type_main": "doc_type_main.json",
    "doc_type_attachment": "doc_type_attachment.json",
    "doc_type_tech": "doc_type_tech.json",
    "actor_role": "actor_role.json",
    "workflow_status": "workflow_status.json",
    "link_type": "link_type.json",
    "signature_status": "signature_status.json",
    "compliance_flag_type": "compliance_flag_type.json",
    "detection_source": "detection_source.json",
    "document_source": "document_source.json",
    "origin_format": "origin_format.json",
    "compliance_severity": "compliance_severity.json",
    "version_mismatch_type": "version_mismatch_type.json",
    "graph_node_type": "graph_node_type.json",   # ADR-001, Рек.5
    "graph_edge_type": "graph_edge_type.json",     # ADR-001, Рек.5
}


class UnknownDictionaryError(KeyError):
    """Запитано словник, якого немає в реєстрі."""


class UnknownCodeError(ValueError):
    """Запитано код, якого немає у вказаному словнику."""


@lru_cache(maxsize=None)
def _load(dict_name: str) -> tuple[dict[str, Any], ...]:
    if dict_name not in _REGISTRY:
        raise UnknownDictionaryError(
            f"Невідомий словник '{dict_name}'. Доступні: {sorted(_REGISTRY)}"
        )
    path = _DICT_DIR / _REGISTRY[dict_name]
    with path.open(encoding="utf-8") as f:
        items = json.load(f)

    codes_seen = set()
    for item in items:
        if "code" not in item or "name_uk" not in item:
            raise ValueError(f"{path.name}: кожен запис має містити 'code' і 'name_uk'")
        if item["code"] in codes_seen:
            raise ValueError(f"{path.name}: дублікат коду '{item['code']}'")
        codes_seen.add(item["code"])

    return tuple(items)


def list_dictionaries() -> list[str]:
    """Список усіх доступних назв словників."""
    return sorted(_REGISTRY)


def all_items(dict_name: str) -> list[dict[str, Any]]:
    """Повний вміст словника (список {code, name_uk, ...})."""
    return list(_load(dict_name))


def codes(dict_name: str) -> list[str]:
    """Усі допустимі коди словника."""
    return [item["code"] for item in _load(dict_name)]


def label(dict_name: str, code: str) -> str:
    """Українська назва для коду. Кидає UnknownCodeError, якщо коду немає."""
    for item in _load(dict_name):
        if item["code"] == code:
            return item["name_uk"]
    raise UnknownCodeError(f"Код '{code}' відсутній у словнику '{dict_name}'")


def is_valid(dict_name: str, code: str) -> bool:
    """Чи є код допустимим значенням словника (без винятку)."""
    return code in codes(dict_name)


def default_severity(flag_type_code: str) -> str:
    """
    Типова критичність для коду типу розбіжності (словник compliance_flag_type).
    Напр. default_severity("undeclared_attachment") -> "falsification_risk".
    """
    for item in _load("compliance_flag_type"):
        if item["code"] == flag_type_code:
            return item["default_severity"]
    raise UnknownCodeError(f"Код '{flag_type_code}' відсутній у словнику 'compliance_flag_type'")


def validate_all() -> None:
    """
    Проганяє всі словники через завантажувач (перевірка на дублікати кодів
    і обов'язкові поля). Викликати в CI/тестах при зміні JSON-файлів.
    """
    for name in list_dictionaries():
        _load(name)
