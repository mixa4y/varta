from __future__ import annotations

import hashlib
import json

import pytest

from case_docket.application.profile import (
    CaseProfileService,
    GetCaseProfileQuery,
    InvalidProfileError,
    MissingProfileError,
    MissingProfileVersionError,
    UnknownCaseError,
)
from case_docket.repository import SQLiteUnitOfWorkFactory


def _profile(case_id: str, version: str) -> dict[str, object]:
    return {
        "schemaVersion": "1.1.0",
        "profileVersion": version,
        "case": {
            "id": case_id,
            "number": None,
            "numberStatus": "unknown",
            "folderKey": "synthetic",
            "title": "Synthetic case",
            "aliases": [],
        },
        "bootstrap": {
            "firstDocumentId": None,
            "temporaryIntakeCaseId": None,
            "numberDetectionSources": [],
            "requireManualReviewForMultipleCandidates": True,
            "allowFilenameAsSoleEvidence": False,
        },
        "proceedings": [],
        "evidenceMap": {
            "rootDocumentId": None,
            "rootSelector": None,
            "keyDocumentRules": [],
            "relationHypotheses": [],
        },
        "exportDefaults": {
            "profile": "metadata_only",
            "includeFullText": False,
            "includeOriginalFiles": False,
            "sealed": False,
        },
        "validationRules": {
            "requireSourceForConfirmedFacts": True,
            "requireAllRequiredProceedings": False,
            "requireReferentialIntegrity": True,
            "requireUniqueIds": True,
            "blockExternalNetworkInSealedExport": True,
        },
    }


def _seed(path, case_id="case-a", version="v1", payload=None) -> None:
    repo = SQLiteUnitOfWorkFactory(path)
    with repo(write=True) as uow:
        raw = json.dumps(payload or _profile(case_id, version), ensure_ascii=False)
        uow._repository.insert(
            "cases",
            {
                "id": case_id,
                "created_at": "2026-01-01T00:00:00+00:00",
                "legacy_payload": json.dumps({"name": "Synthetic"}),
            },
        )
        uow._repository.insert(
            "case_profiles",
            {
                "id": case_id + "-profile",
                "case_id": case_id,
                "schema_version": "1.1.0",
                "profile_version": version,
                "profile_json": raw,
                "profile_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "status": "active",
                "created_by": "test",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        )
        uow.commit()


def test_exact_profile_survives_sqlite_restart_and_is_case_isolated(tmp_path):
    db = tmp_path / "profiles.sqlite3"
    _seed(db)
    _seed(db, "case-b", "v1")
    service = CaseProfileService(SQLiteUnitOfWorkFactory(db))
    assert service.get(GetCaseProfileQuery("case-a", "v1")).case_id == "case-a"
    assert service.get(GetCaseProfileQuery("case-b", "v1")).case_id == "case-b"
    assert service.get(GetCaseProfileQuery("case-a", "v1")).profile["case"]["id"] == "case-a"


def test_missing_unknown_and_invalid_versions_are_explicit(tmp_path):
    db = tmp_path / "profiles.sqlite3"
    _seed(db)
    service = CaseProfileService(SQLiteUnitOfWorkFactory(db))
    with pytest.raises(UnknownCaseError):
        service.get(GetCaseProfileQuery("absent", "v1"))
    with pytest.raises(MissingProfileVersionError):
        service.get(GetCaseProfileQuery("case-a", "v9"))
    bad = _profile("case-a", "other")
    bad_db = tmp_path / "bad.sqlite3"
    _seed(bad_db, payload=bad)
    with pytest.raises(InvalidProfileError):
        CaseProfileService(SQLiteUnitOfWorkFactory(bad_db)).get(
            GetCaseProfileQuery("case-a", "v1")
        )


def test_case_without_any_profile_is_missing_profile(tmp_path):
    db = tmp_path / "profiles.sqlite3"
    repo = SQLiteUnitOfWorkFactory(db)
    with repo(write=True) as uow:
        uow._repository.insert(
            "cases",
            {
                "id": "case-empty",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        )
        uow.commit()
    with pytest.raises(MissingProfileError):
        CaseProfileService(repo).get(GetCaseProfileQuery("case-empty", "v1"))
