from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class R05PrivateSettings:
    corpus_root: Path
    workspace_root: Path


@dataclass(frozen=True, slots=True)
class R05PrivateSettingsStore:
    """Local path settings, stored outside Git; no credentials or DPAPI required."""

    path: Path

    def save(self, settings: R05PrivateSettings) -> None:
        payload = json.dumps(
            {
                "corpusRoot": str(settings.corpus_root.resolve()),
                "workspaceRoot": str(settings.workspace_root.resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".r05-settings-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def load(self) -> R05PrivateSettings:
        decoded = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("R05 private settings мають бути object")
        corpus = decoded.get("corpusRoot")
        workspace = decoded.get("workspaceRoot")
        if (
            not isinstance(corpus, str)
            or not corpus.strip()
            or not isinstance(workspace, str)
            or not workspace.strip()
        ):
            raise ValueError("R05 private settings неповні")
        return R05PrivateSettings(Path(corpus), Path(workspace))
