"""Каркас інтерфейсів для зовнішніх рушіїв (ADR-001, Рек.10). Без реєстру/discovery — див. base.py."""

from .base import OCRPlugin, SignaturePlugin, STTPlugin

__all__ = ["OCRPlugin", "STTPlugin", "SignaturePlugin"]
