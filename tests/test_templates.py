from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]


def load_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8-sig"))


def test_case_profile_example_matches_schema():
    schema = load_json("config/schemas/case-profile.schema.json")
    example = load_json("templates/case/case-profile.example.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(example)


def test_map_data_example_matches_schema():
    schema = load_json("config/schemas/map-data.schema.json")
    example = load_json("templates/evidence-map/map-data.example.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=None).validate(example)


def test_embedded_map_template_data_matches_schema():
    html = (ROOT / "caseflow/static/legal-case-map.html").read_text(encoding="utf-8-sig")
    match = re.search(
        r'<script id="varta-map-data" type="application/json">\s*(.*?)\s*</script>',
        html,
        flags=re.DOTALL,
    )
    assert match is not None
    embedded = json.loads(match.group(1))
    schema = load_json("config/schemas/map-data.schema.json")
    Draft202012Validator(schema, format_checker=None).validate(embedded)


def test_case_profile_contract_rejects_unformalized_fields():
    schema = load_json("config/schemas/case-profile.schema.json")
    example = load_json("templates/case/case-profile.example.json")
    example["case"]["informalField"] = "must not silently pass"

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(example)


def test_case_profile_never_accepts_filename_as_sole_case_number_evidence():
    schema = load_json("config/schemas/case-profile.schema.json")
    example = load_json("templates/case/case-profile.example.json")
    example["bootstrap"]["allowFilenameAsSoleEvidence"] = True

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(example)


def test_map_contract_exposes_all_formalized_collections():
    example = load_json("templates/evidence-map/map-data.example.json")
    expected = {
        "proceedings",
        "actors",
        "files",
        "documents",
        "events",
        "claims",
        "relations",
        "sourceReferences",
        "reviewDecisions",
        "exclusions",
    }

    assert expected.issubset(example)


@pytest.mark.parametrize("entity_kind", ["claim", "relation"])
def test_confirmed_items_require_nonempty_evidence_basis(entity_kind: str):
    schema = load_json("config/schemas/map-data.schema.json")
    example = load_json("templates/evidence-map/map-data.example.json")
    subject = {"type": "document", "id": "document_example", "role": None}

    if entity_kind == "claim":
        example["claims"].append(
            {
                "id": "claim_example",
                "subject": subject,
                "text": "Вигадане тестове твердження",
                "classification": "confirmed_fact",
                "assertedByActorIds": [],
                "basisDocumentIds": [],
                "sourceReferenceIds": [],
                "legalCitationIds": [],
                "reviewStatus": "confirmed",
                "reviewDecisionIds": [],
                "uncertaintyNote": None,
                "processConsequence": None,
            }
        )
    else:
        example["relations"].append(
            {
                "id": "relation_example",
                "fromType": "document",
                "fromId": "document_example",
                "toType": "event",
                "toId": "event_example",
                "relationType": "evidences",
                "label": None,
                "basisDocumentIds": [],
                "sourceReferenceIds": [],
                "classification": "confirmed_fact",
                "reviewStatus": "confirmed",
                "reviewDecisionIds": [],
                "uncertaintyNote": None,
                "validFrom": None,
                "validTo": None,
            }
        )

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(deepcopy(example))
