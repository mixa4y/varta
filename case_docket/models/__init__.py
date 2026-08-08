"""
Моделі даних (dataclasses, Pydantic-сумісні за структурою — pydantic
недоступний офлайн у середовищі збірки; поля/типи підібрані так, щоб
перехід був рефактором, а не переписуванням).
"""

from .actor import Actor
from .dates import DocumentDates
from .document import Document
from .document_file import DocumentFile
from .event import Event

__all__ = ["Document", "DocumentFile", "Actor", "Event", "DocumentDates"]
