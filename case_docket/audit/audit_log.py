"""
case_docket.audit.audit_log
==============================
Обгортка над Repository.record_audit_event (ADR-001, Рек.7; п.11 CSMD:
"Усі суттєві операції повинні бути відтворюваними та журналюватися").

Кожен модуль (intake, naming, compliance, version_check, signature, stt)
має логувати значущі дії через ці функції, а не звертатись до
repository.record_audit_event напряму — так усі дії журналюються за
єдиним, передбачуваним набором дій (AuditAction), а не довільними рядками.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from case_docket.repository.base import Repository


class AuditAction(str, Enum):
    """Контрольований словник дій, що журналюються. Розширювати тут,
    а не вигадувати нові рядки-дії на місці виклику."""

    ARCHIVE_IMPORTED = "archive_imported"
    HASH_COMPUTED = "hash_computed"
    DOCUMENT_RENAMED = "document_renamed"
    ATTACHMENT_LINKED = "attachment_linked"
    MANUAL_CONFIRMATION = "manual_confirmation"
    SIGNATURE_VERIFIED = "signature_verified"
    OCR_COMPLETED = "ocr_completed"
    OCR_RERUN = "ocr_rerun"
    TRANSCRIPT_COMPLETED = "transcript_completed"
    COMPLIANCE_FLAG_RAISED = "compliance_flag_raised"
    VERSION_MISMATCH_DETECTED = "version_mismatch_detected"
    METADATA_EDITED = "metadata_edited"


def log(
    repo: Repository,
    action: AuditAction,
    entity_table: str,
    entity_id: Optional[str],
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Єдина точка входу для журналювання дії. Append-only — жодних
    update/delete над audit_log ніде в системі не повинно бути."""
    repo.record_audit_event(action.value, entity_table, entity_id, details)
