from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from case_docket.application.case_database_import_ports import CorpusImportResult
from case_docket.application.intake import IntakeCommand
from case_docket.runtime import build_intake_runtime


class CorpusImportError(RuntimeError):
    """Raised when managed corpus intake is not using the planned SQLite."""


@dataclass(frozen=True, slots=True)
class ManagedCorpusImporter:
    source_root: Path
    workspace_root: Path
    expected_database_path: Path

    def import_corpus(self, idempotency_key: str) -> CorpusImportResult:
        runtime = build_intake_runtime(self.workspace_root)
        if runtime.database_path.resolve() != self.expected_database_path.resolve():
            raise CorpusImportError("Managed corpus runtime не використовує planned SQLite")
        result = runtime.intake_service.intake(
            IntakeCommand(
                source=self.source_root,
                idempotency_key=idempotency_key,
                source_uri="private://r05/corpus",
            )
        )
        counts = result.counts
        return CorpusImportResult(
            accepted=int(counts.get("accepted", 0)),
            duplicate=int(counts.get("duplicate", 0)),
            failed=int(counts.get("failed", 0)),
            skipped=int(counts.get("skipped", 0)),
        )
