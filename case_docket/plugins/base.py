"""
case_docket.plugins.base
===========================
Абстрактні інтерфейси для зовнішніх рушіїв (ADR-001, Рек.10).

СТАТУС: лише контракт. Механізм реєстрації/discovery плагінів свідомо
НЕ реалізовано зараз — у проєкті ще 0 реальних реалізацій (OCR/STT/КЕП),
будувати систему плагінів під відсутні реалізації означало б передчасну
складність (YAGNI). Коли зʼявиться хоча б 2 реальні реалізації одного
типу (напр. два OCR-рушії) — тоді є сенс писати реєстр із динамічним
вибором. До того часу конкретний рушій обирається прямим імпортом.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol


class ProcessorPlugin(Protocol):
    name: str
    version: str

    def process(self, request: dict[str, Any]) -> dict[str, Any]: ...


def discover_plugins(candidates: dict[str, str]) -> dict[str, str]:
    """Explicit discovery: failures are capability states, never silent imports."""
    import importlib

    states: dict[str, str] = {}
    for name, module in candidates.items():
        try:
            importlib.import_module(module)
            states[name] = "available"
        except ModuleNotFoundError:
            states[name] = "unavailable_dependency"
        except Exception:
            states[name] = "failed"
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
