"""
case_docket.plugins.base
===========================
Абстрактні інтерфейси для зовнішніх рушіїв (ADR-001, Рек.10).

Stable C10 discovery contract.  Concrete OCR/STT/КЕП algorithms remain out
of scope; missing dependencies are represented explicitly and never silently
converted into an available capability.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


PROCESSOR_PLUGIN_CONTRACT_VERSION = 1


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE_DEPENDENCY = "unavailable_dependency"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PluginCapability:
    name: str
    status: CapabilityStatus
    contract_version: int
    plugin_version: str | None
    detail: str | None = None


class ProcessorPlugin(Protocol):
    name: str
    version: str
    contract_version: int

    def process(self, request: dict[str, Any]) -> dict[str, Any]: ...


def discover_plugins(candidates: dict[str, str]) -> dict[str, PluginCapability]:
    """Explicit discovery: failures are capability states, never silent imports."""
    import importlib

    states: dict[str, PluginCapability] = {}
    for name, module in candidates.items():
        try:
            loaded = importlib.import_module(module)
            version = getattr(loaded, "PLUGIN_VERSION", None)
            contract_version = getattr(loaded, "PLUGIN_CONTRACT_VERSION", None)
            if not isinstance(version, str) or not version:
                raise RuntimeError("plugin version is missing")
            if contract_version != PROCESSOR_PLUGIN_CONTRACT_VERSION:
                raise RuntimeError("unsupported plugin contract version")
            states[name] = PluginCapability(
                name=name,
                status=CapabilityStatus.AVAILABLE,
                contract_version=contract_version,
                plugin_version=version,
            )
        except ModuleNotFoundError as exc:
            states[name] = PluginCapability(
                name=name,
                status=CapabilityStatus.UNAVAILABLE_DEPENDENCY,
                contract_version=PROCESSOR_PLUGIN_CONTRACT_VERSION,
                plugin_version=None,
                detail=exc.name or "dependency not installed",
            )
        except Exception as exc:
            states[name] = PluginCapability(
                name=name,
                status=CapabilityStatus.FAILED,
                contract_version=PROCESSOR_PLUGIN_CONTRACT_VERSION,
                plugin_version=None,
                detail=type(exc).__name__,
            )
    return states


class OCRPlugin(ABC):
    @abstractmethod
    def recognize(self, file_path: str) -> tuple[str, float]:
        """Повертає (розпізнаний_текст, confidence 0..1). confidence —
        реальне значення від рушія, не вигадане (див. Рек.3 ADR-001)."""


class STTPlugin(ABC):
    @abstractmethod
    def transcribe(self, file_path: str, language: str = "uk") -> tuple[str, float]:
        """Повертає (транскрипт, confidence 0..1)."""


class SignaturePlugin(ABC):
    @abstractmethod
    def verify(self, file_path: str) -> dict[str, Any]:
        """
        Перевірка КЕП/ЄЦП. Повертає структурований результат:
        {signature_status, signer, verified_at, certificate_info, ...}.
        НІКОЛИ не приймає й не передає приватний ключ чи пароль до нього
        стороннім сервісам (п.6 CSMD).
        """
