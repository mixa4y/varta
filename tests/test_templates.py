from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator


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
