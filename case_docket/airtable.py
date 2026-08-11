from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal


_SCHEMA_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "config" / "airtable_schema.json",
    Path(sys.prefix) / "config" / "airtable_schema.json",
    Path(sys.executable).resolve().parent / "config" / "airtable_schema.json",
    Path.cwd() / "config" / "airtable_schema.json",
)
AIRTABLE_SCHEMA_PATH = next(
    (candidate for candidate in _SCHEMA_CANDIDATES if candidate.exists()),
    _SCHEMA_CANDIDATES[0],
)
_LOCAL_ID_NAMESPACE = uuid.UUID("c098a362-4a6d-4cca-9474-7953f665c299")


class AirtableMappingError(ValueError):
    pass


@dataclass(frozen=True)
class JoinLink:
    table: str
    source_column: str
    target_column: str
    constants: tuple[tuple[str, str], ...] = ()

    @property
    def sql_target(self) -> str:
        suffix = ""
        if self.constants:
            suffix = ":" + ",".join(f"{key}={value}" for key, value in self.constants)
        return f"{self.table}.{self.source_column}->{self.target_column}{suffix}"


@dataclass(frozen=True)
class ReferenceLink:
    table: str
    column: str
    entity_side: Literal["source", "target"]

    @property
    def sql_target(self) -> str:
        return f"{self.table}.{self.column}:{self.entity_side}"


LinkSpec = JoinLink | ReferenceLink


@dataclass(frozen=True)
class AirtableImportSummary:
    records: int
    links: int
    unresolved_links: int


TABLE_SQL_NAMES = {
    "tbl2OUBStFDdfxNNS": "contacts",
    "tblw2m5qeasGSW3h8": "cases",
    "tbl0fQuxzzyGijsXK": "proceedings",
    "tbl2GzptAOVCEHQM7": "events",
    "tblhxvEsiaMwgl0BF": "documents",
    "tbll4F8mAUkQqUnQJ": "case_participants",
    "tblgiLYvazAF2YWOW": "document_links",
    "tblPvqu8ch6e29bq7": "compliance_flags",
    "tblACqocW5KmtYJp5": "document_version_match",
}


SCALAR_COLUMNS = {
    # Контакти
    "fldsUF5FAcJRAYzMG": ("contacts", "full_name"),
    "fldUkPtvUfcJGE252": ("contacts", "short_name"),
    "fldAbyAGj8TTMlgx6": ("contacts", "participant_type"),
    "fldq6Pe8Jiolfqz5B": ("contacts", "active"),
    "fldGn1lbv0naouTTw": ("contacts", "email"),
    "fldAv2Ga4NF7IRAuH": ("contacts", "phone"),
    "fldW9SHBjMSEwtypR": ("contacts", "additional_phone"),
    "fldALYDzCJcd0I2pR": ("contacts", "address"),
    "fldL60K18q0AHXfcT": ("contacts", "tax_id"),
    "fldnTPEQfWhTYBTPE": ("contacts", "edrpou"),
    "fldsRqcjUsc1kyN8a": ("contacts", "birth_or_registration_date"),
    "fldr5507Rsfe1XQen": ("contacts", "representative_or_contact_person"),
    "fldS3fiq6zA6dvVoU": ("contacts", "notes"),
    # Справи
    "fldBIYNLnq1NaQk3E": ("cases", "case_number"),
    "fld7xYu8Bu0BwP8Oq": ("cases", "name"),
    "fldPamBewNjAVNba0": ("cases", "dispute_summary"),
    "fldu5q9PSQdVZ7zYE": ("cases", "parties_text"),
    "fld5MKn1cYWwftFWx": ("cases", "court"),
    "fldXVPVLVN7Apk0Vt": ("cases", "category"),
    "fldyTlfLcU1p2lkvb": ("cases", "status"),
    "fldLE62seCBEDjVCc": ("cases", "current_stage"),
    "fld6wT602LQbMvtSo": ("cases", "opened_on"),
    "fldqg9yZi4ktjdFH3": ("cases", "closed_on"),
    "fldjE5BYiIqbuI2la": ("cases", "next_action"),
    "fldIGg1I98B0K1naW": ("cases", "short_description"),
    # Провадження
    "fld4gdU5CEgFNVn7I": ("proceedings", "name"),
    "fldKa4sGwfiW8JRA7": ("proceedings", "proceeding_number"),
    "fldAx9h8duUJyZlKW": ("proceedings", "proceeding_type"),
    "fldbzAXO471oogBMh": ("proceedings", "category"),
    "fldGX4OuNv1WD8ctW": ("proceedings", "authority"),
    "fldoiyeZwwaMWAl69": ("proceedings", "status"),
    "fldx4VDjy52qFQlpW": ("proceedings", "started_on"),
    "fldcpCZCsSfe2hcN4": ("proceedings", "ended_on"),
    "fldx1ulNiGTMAhT7g": ("proceedings", "outcome"),
    "fldTvX3eTyA48lZ8w": ("proceedings", "notes"),
    # Події
    "fld1y6fnMxVfRsnKw": ("events", "title"),
    "fldAm19XcFzk4P9oo": ("events", "interaction_type"),
    "fldtcR9bMUiIXfy3q": ("events", "event_at"),
    "fldW83ib6JYdmCHd6": ("events", "sent_at"),
    "fldxA9Ol7UIabWtdw": ("events", "delivered_at"),
    "fldw0Pqo2QuvIJXLl": ("events", "channel"),
    "fldAxGAnYBAxjIKbY": ("events", "channel_details"),
    "fldO8RpFa6tSMsSqN": ("events", "description"),
    "fldA6b3om7s6EMrME": ("events", "attachments_json"),
    "fldn3UiaKJgbHMIrA": ("events", "workflow_status"),
    # Документи
    "fldXuOovgXZaoZjV3": ("documents", "title"),
    "fldLO41zdBrI7vm8W": ("documents", "doc_type"),
    "fldQ2ePN1TdoqFBlm": ("documents", "sent_on"),
    "fldJ06MpzUxgONkgN": ("documents", "delivered_on"),
    "fldgVi1UBEU6Bvf95": ("documents", "channel"),
    "fldP5jGDLtjWc3l9A": ("documents", "channel_details"),
    "fldYaR97pw7qkWEH6": ("documents", "file_attachments_json"),
    "fldearxvbjyJuPOdr": ("documents", "category"),
    "fldB86r7KPYfepzJ7": ("documents", "registered_on"),
    "fldVJ0JmTzGeHfwOU": ("documents", "source"),
    "fldPDPrB6q5tlDuDr": ("documents", "source_archive"),
    "fldgK4uTdXamu4YIg": ("documents", "imported_on"),
    "fld4WYRDcNBcqBUu2": ("documents", "origin_format"),
    "fldWXdt6OkXib57wH": ("documents", "requires_manual_review"),
    "fldi6vOahIczfubSG": ("documents", "signature_status"),
    "fldOqnB9v9TiC1Fcl": ("documents", "transcript"),
    "fldAg7Huz1xGS85I1": ("documents", "file_hash"),
    # Учасники справи
    "fldZY8da3bfjfTiZy": ("case_participants", "role_external_id"),
    "fldnQfVMsMWOXwJRV": ("case_participants", "role"),
    # document_links
    "fldefA1UCXoAV22gr": ("document_links", "title"),
    "fldb9R4mTaWnuho1w": ("document_links", "link_type"),
    # compliance_flags
    "fldaA64IrdkwF8XVD": ("compliance_flags", "title"),
    "fldV6vFnYcCFbVbkO": ("compliance_flags", "flag_type"),
    "fldCgu9aYEApr2ioG": ("compliance_flags", "severity"),
    "fldX5iiacnhJzFa0z": ("compliance_flags", "detected_by"),
    "fld7YCh4JPsm3nYTT": ("compliance_flags", "note"),
    "fldTJLArM56urztXy": ("compliance_flags", "manually_confirmed"),
    # document_version_match
    "fld0M6V00eNStp0yi": ("document_version_match", "title"),
    "fld0gIaMY0z2yKq30": ("document_version_match", "hashes_equal"),
    "fldjehVBC2fOQS9GY": ("document_version_match", "text_similarity_score"),
    "fldzT9yfDloirAvKQ": ("document_version_match", "mismatch_type"),
    "fldlLs42CoJwlRq2z": ("document_version_match", "needs_review"),
}


COMPUTED_TARGETS = {
    "flduvJqA2CsVjO2Nk": ("lookup", "v_contact_proceeding_details.proceeding_name"),
    "fld8f9NZuCFHFJysm": ("lookup", "v_contact_proceeding_details.case_id"),
    "fldIiW8mH9VMxjNo6": ("lookup", "v_contact_proceeding_details.proceeding_number"),
    "fldnZIKHNcHGkyWD7": ("lookup", "v_contact_proceeding_details.proceeding_type"),
    "fldFECbIkr11qaOqp": ("lookup", "v_contact_proceeding_details.proceeding_category"),
    "fldEhChcZ5seuPpa9": ("lookup", "v_contact_proceeding_details.authority"),
    "fld1X2wvL8lFLanRy": ("lookup", "v_contact_proceeding_details.proceeding_status"),
    "fldf4q9R7wprP2cc2": ("lookup", "v_contact_proceeding_details.started_on"),
    "fldQxshxqILCBHsVH": ("lookup", "v_contact_proceeding_details.ended_on"),
    "fldP95Ruo8XoaHC0n": ("lookup", "v_contact_proceeding_details.outcome"),
    "fldCkpOOV8PcIP95f": ("formula", "v_cases.proceeding_count"),
    "fld9xPMhchWWBxj9U": ("formula", "v_events.activity_date"),
}


LINK_SPECS: dict[str, LinkSpec] = {
    # Контакти
    "fldBXm28KqnchRzWj": ReferenceLink("case_participants", "contact_id", "target"),
    "fldGfWlDfDcXuG420": JoinLink("contact_cases", "contact_id", "case_id"),
    "fldbv0WeRuN86jplD": JoinLink("contact_proceedings", "contact_id", "proceeding_id"),
    "fldMyuQxJCqhnTY7W": JoinLink(
        "event_contacts", "contact_id", "event_id", (("role", "sender"),)
    ),
    "fldZQZCxgWqWoyJjS": JoinLink(
        "event_contacts", "contact_id", "event_id", (("role", "recipient"),)
    ),
    # Справи
    "fldlv9rvYxpcMiLk0": JoinLink(
        "case_proceedings",
        "case_id",
        "proceeding_id",
        (("relationship_kind", "membership"),),
    ),
    "fld4GdY0KcbY9xBwp": JoinLink("case_events", "case_id", "event_id"),
    "fldbELvq8ZSxKJ9hN": JoinLink("case_documents", "case_id", "document_id"),
    "fldGL45mM96oJf8np": ReferenceLink("case_participants", "case_id", "target"),
    "fldHy2sJUeLfFe3CG": JoinLink(
        "case_proceedings",
        "case_id",
        "proceeding_id",
        (("relationship_kind", "main"),),
    ),
    "fldhVTA9nrcHKl7K0": JoinLink("contact_cases", "case_id", "contact_id"),
    # Провадження
    "fldnC3G8bYPZjQUdR": JoinLink(
        "case_proceedings",
        "proceeding_id",
        "case_id",
        (("relationship_kind", "membership"),),
    ),
    "fldOj5z7NVQZJQaUH": JoinLink("proceeding_events", "proceeding_id", "event_id"),
    "fldtD1ldsElO0XY6q": JoinLink(
        "proceeding_documents", "proceeding_id", "document_id"
    ),
    "fldmxZdw4KFkzfLbw": JoinLink(
        "case_proceedings",
        "proceeding_id",
        "case_id",
        (("relationship_kind", "main"),),
    ),
    "fldNiuRZV0h6liHsL": JoinLink(
        "proceeding_relations", "child_proceeding_id", "parent_proceeding_id"
    ),
    "fld12bJn1v7VGVXlk": JoinLink(
        "proceeding_relations", "parent_proceeding_id", "child_proceeding_id"
    ),
    "fld0iUoNDknwSQCvg": JoinLink(
        "contact_proceedings", "proceeding_id", "contact_id"
    ),
    # Події
    "fldnGMbGPaGVA64Q0": JoinLink("case_events", "event_id", "case_id"),
    "fldU85sGdvXfpyp8y": JoinLink("proceeding_events", "event_id", "proceeding_id"),
    "fldWQZaoDewhxKYY7": JoinLink("event_documents", "event_id", "document_id"),
    "fldpHAd9Jm5yPFktR": JoinLink(
        "event_contacts", "event_id", "contact_id", (("role", "sender"),)
    ),
    "fldyrkjlkPiJvCv6n": JoinLink(
        "event_contacts", "event_id", "contact_id", (("role", "recipient"),)
    ),
    # Документи
    "fldij2txUAF3rHkbA": JoinLink("case_documents", "document_id", "case_id"),
    "fldZhefYcXoIeO8Zq": JoinLink(
        "proceeding_documents", "document_id", "proceeding_id"
    ),
    "fldp637rPy50IaOcX": JoinLink("event_documents", "document_id", "event_id"),
    "fldhNMxvuNyp4d2hb": ReferenceLink(
        "document_links", "source_document_id", "target"
    ),
    "fldcXBwXGzWlJS0W6": ReferenceLink(
        "document_links", "target_document_id", "target"
    ),
    "fldv7rXxEClRRjSGF": ReferenceLink("compliance_flags", "document_id", "target"),
    "fldtxQxPT6Jun1FEu": ReferenceLink(
        "document_version_match", "user_document_id", "target"
    ),
    "fldW3zQIPszrLVm9y": ReferenceLink(
        "document_version_match", "court_document_id", "target"
    ),
    # Учасники справи
    "fldc7Bw4YJMYzQCwX": ReferenceLink("case_participants", "case_id", "source"),
    "flducJ9za4RACiSYP": ReferenceLink("case_participants", "contact_id", "source"),
    # document_links
    "fldw8cAqivZisjmGX": ReferenceLink(
        "document_links", "source_document_id", "source"
    ),
    "fldGPGtply6TOrrhj": ReferenceLink(
        "document_links", "target_document_id", "source"
    ),
    # compliance_flags
    "fldARhXpTAVPUjlpb": ReferenceLink("compliance_flags", "document_id", "source"),
    # document_version_match
    "fldqkXhCmRjCSBN7s": ReferenceLink(
        "document_version_match", "user_document_id", "source"
    ),
    "fldmWFUuKiDUQ0sdD": ReferenceLink(
        "document_version_match", "court_document_id", "source"
    ),
}


def load_airtable_schema(path: Path | None = None) -> dict[str, Any]:
    schema_path = path or AIRTABLE_SCHEMA_PATH
    try:
        data = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AirtableMappingError(f"Не вдалося прочитати Airtable schema: {schema_path}") from exc
    validate_airtable_mapping(data)
    return data


def validate_airtable_mapping(schema: dict[str, Any]) -> None:
    tables = schema.get("tables")
    if not isinstance(tables, list):
        raise AirtableMappingError("Airtable schema не містить масив tables")
    table_ids = {str(table.get("id")) for table in tables}
    if table_ids != set(TABLE_SQL_NAMES):
        raise AirtableMappingError("Набір Airtable tables не відповідає SQL mapping")
    field_ids = {
        str(field.get("id"))
        for table in tables
        for field in table.get("fields", [])
    }
    mapped = set(SCALAR_COLUMNS) | set(COMPUTED_TARGETS) | set(LINK_SPECS)
    missing = field_ids - mapped
    stale = mapped - field_ids
    if missing or stale:
        raise AirtableMappingError(
            f"Airtable field mapping неповний: missing={sorted(missing)}, stale={sorted(stale)}"
        )


def install_airtable_catalog(
    connection: sqlite3.Connection,
    path: Path | None = None,
) -> str:
    schema_path = path or AIRTABLE_SCHEMA_PATH
    raw = schema_path.read_bytes()
    schema = json.loads(raw.decode("utf-8"))
    validate_airtable_mapping(schema)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    now = _now()

    with connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO airtable_schema_snapshots(
                source_sha256, schema_version, captured_at, base_id, base_name,
                schema_json, installed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_sha256,
                int(schema["schema_version"]),
                str(schema["captured_at"]),
                str(schema["base"]["id"]),
                str(schema["base"]["name"]),
                raw.decode("utf-8"),
                now,
            ),
        )
        for table in schema["tables"]:
            table_id = str(table["id"])
            connection.execute(
                """
                INSERT INTO airtable_table_mappings(
                    airtable_table_id, airtable_name, sql_table_name, field_count
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(airtable_table_id) DO UPDATE SET
                    airtable_name = excluded.airtable_name,
                    sql_table_name = excluded.sql_table_name,
                    field_count = excluded.field_count
                """,
                (table_id, table["name"], TABLE_SQL_NAMES[table_id], len(table["fields"])),
            )

        for table in schema["tables"]:
            table_id = str(table["id"])
            for field in table["fields"]:
                field_id = str(field["id"])
                kind, target = _field_sql_mapping(field_id)
                config = field.get("config") or {}
                connection.execute(
                    """
                    INSERT INTO airtable_field_mappings(
                        airtable_field_id, airtable_table_id, airtable_name,
                        airtable_type, sql_kind, sql_target, config_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(airtable_field_id) DO UPDATE SET
                        airtable_table_id = excluded.airtable_table_id,
                        airtable_name = excluded.airtable_name,
                        airtable_type = excluded.airtable_type,
                        sql_kind = excluded.sql_kind,
                        sql_target = excluded.sql_target,
                        config_json = excluded.config_json
                    """,
                    (
                        field_id,
                        table_id,
                        field["name"],
                        field["type"],
                        kind,
                        target,
                        _json(config),
                    ),
                )
                _replace_choices(connection, field_id, config)
                _replace_dependencies(connection, field_id, field["type"], config)
                if field_id in LINK_SPECS:
                    connection.execute(
                        """
                        INSERT INTO airtable_relationship_mappings(
                            airtable_field_id, target_table_id, inverse_field_id, sql_target
                        ) VALUES (?, ?, ?, ?)
                        ON CONFLICT(airtable_field_id) DO UPDATE SET
                            target_table_id = excluded.target_table_id,
                            inverse_field_id = excluded.inverse_field_id,
                            sql_target = excluded.sql_target
                        """,
                        (
                            field_id,
                            config["linkedTableId"],
                            config.get("inverseLinkFieldId"),
                            LINK_SPECS[field_id].sql_target,
                        ),
                    )
    return source_sha256


def import_airtable_snapshot(
    connection: sqlite3.Connection,
    snapshot: dict[str, Any],
    audit: Callable[[str, str, str | None, dict[str, Any] | None], None] | None = None,
) -> AirtableImportSummary:
    schema = load_airtable_schema()
    table_by_id = {str(table["id"]): table for table in schema["tables"]}
    table_by_key: dict[str, dict[str, Any]] = {}
    for table_id, table in table_by_id.items():
        table_by_key[table_id] = table
        table_by_key[str(table["name"])] = table
        table_by_key[TABLE_SQL_NAMES[table_id]] = table

    records_by_table = snapshot.get("tables", snapshot)
    if not isinstance(records_by_table, dict):
        raise AirtableMappingError("Airtable snapshot має бути object із таблицями")

    prepared: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    with connection:
        for table_key, raw_records in records_by_table.items():
            table = table_by_key.get(str(table_key))
            if table is None:
                raise AirtableMappingError(f"Невідома Airtable table: {table_key}")
            if isinstance(raw_records, dict):
                raw_records = raw_records.get("records", [])
            if not isinstance(raw_records, list):
                raise AirtableMappingError(f"Records таблиці {table_key} мають бути масивом")
            for record in raw_records:
                if not isinstance(record, dict) or not record.get("id"):
                    raise AirtableMappingError(f"Таблиця {table_key} містить record без id")
                fields = _normalize_record_fields(table, record.get("fields", {}))
                local_id = _upsert_airtable_record(
                    connection, table, str(record["id"]), fields
                )
                prepared.append((table, local_id, fields))

        link_count = 0
        for table, local_id, fields in prepared:
            link_count += _replace_record_links(connection, table, local_id, fields)
        _resolve_record_links(connection)
        _materialize_domain_links(connection)
        unresolved = int(
            connection.execute("SELECT COUNT(*) FROM v_airtable_unresolved_links").fetchone()[0]
        )
        if audit is not None:
            audit(
                "airtable_import",
                "airtable_record_map",
                None,
                {
                    "records": len(prepared),
                    "links": link_count,
                    "unresolved_links": unresolved,
                },
            )
    return AirtableImportSummary(len(prepared), link_count, unresolved)


def _field_sql_mapping(field_id: str) -> tuple[str, str]:
    scalar = SCALAR_COLUMNS.get(field_id)
    if scalar is not None:
        return "column", f"{scalar[0]}.{scalar[1]}"
    computed = COMPUTED_TARGETS.get(field_id)
    if computed is not None:
        return computed
    link = LINK_SPECS.get(field_id)
    if link is not None:
        return "relation", link.sql_target
    raise AirtableMappingError(f"Немає SQL mapping для Airtable field {field_id}")


def _replace_choices(
    connection: sqlite3.Connection,
    field_id: str,
    config: dict[str, Any],
) -> None:
    connection.execute(
        "DELETE FROM airtable_select_choices WHERE airtable_field_id = ?", (field_id,)
    )
    for position, choice in enumerate(config.get("choices", [])):
        connection.execute(
            """
            INSERT INTO airtable_select_choices(
                airtable_field_id, airtable_choice_id, choice_name, color, position
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (field_id, choice["id"], choice["name"], choice.get("color"), position),
        )


def _replace_dependencies(
    connection: sqlite3.Connection,
    field_id: str,
    field_type: str,
    config: dict[str, Any],
) -> None:
    connection.execute(
        "DELETE FROM airtable_computed_dependencies WHERE computed_field_id = ?",
        (field_id,),
    )
    dependencies: list[tuple[str, str]] = []
    if field_type == "multipleLookupValues":
        dependencies.extend(
            [
                (str(config["recordLinkFieldId"]), "link"),
                (str(config["fieldIdInLinkedTable"]), "value"),
            ]
        )
    elif field_type == "formula":
        dependencies.extend((str(item), "formula") for item in config["referencedFieldIds"])
    for position, (dependency_id, dependency_kind) in enumerate(dependencies):
        connection.execute(
            """
            INSERT INTO airtable_computed_dependencies(
                computed_field_id, dependency_field_id, dependency_kind, position
            ) VALUES (?, ?, ?, ?)
            """,
            (field_id, dependency_id, dependency_kind, position),
        )


def _normalize_record_fields(table: dict[str, Any], raw_fields: Any) -> dict[str, Any]:
    if not isinstance(raw_fields, dict):
        raise AirtableMappingError(f"Record fields у {table['name']} мають бути object")
    by_id = {str(field["id"]): field for field in table["fields"]}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for field in table["fields"]:
        by_name.setdefault(str(field["name"]), []).append(field)
    normalized: dict[str, Any] = {}
    for key, value in raw_fields.items():
        field = by_id.get(str(key))
        if field is None:
            candidates = by_name.get(str(key), [])
            if len(candidates) > 1:
                raise AirtableMappingError(
                    f"Поле {table['name']}.{key} дублюється; імпорт потребує field ID"
                )
            if not candidates:
                raise AirtableMappingError(f"Невідоме поле {table['name']}.{key}")
            field = candidates[0]
        normalized[str(field["id"])] = value
    return normalized


def _upsert_airtable_record(
    connection: sqlite3.Connection,
    table: dict[str, Any],
    airtable_record_id: str,
    fields: dict[str, Any],
) -> str:
    table_id = str(table["id"])
    sql_table = TABLE_SQL_NAMES[table_id]
    existing = connection.execute(
        """
        SELECT local_id FROM airtable_record_map
        WHERE airtable_table_id = ? AND airtable_record_id = ?
        """,
        (table_id, airtable_record_id),
    ).fetchone()
    local_id = (
        str(existing["local_id"])
        if existing is not None
        else str(uuid.uuid5(_LOCAL_ID_NAMESPACE, f"{table_id}:{airtable_record_id}"))
    )
    values: dict[str, Any] = {}
    field_types = {str(field["id"]): str(field["type"]) for field in table["fields"]}
    for field_id, value in fields.items():
        scalar = SCALAR_COLUMNS.get(field_id)
        if scalar is None:
            continue
        if scalar[0] != sql_table:
            raise AirtableMappingError(f"Field {field_id} спрямовано до іншої SQL table")
        values[scalar[1]] = _convert_scalar(field_id, field_types[field_id], value)
    if sql_table == "contacts":
        if not str(values.get("full_name") or "").strip():
            raise AirtableMappingError("Контакт потребує ПІБ / Назву")
        values.setdefault("participant_type", "person")
    now = _now()
    columns = ["id", "airtable_record_id", *values, "created_at", "updated_at"]
    parameters = [local_id, airtable_record_id, *values.values(), now, now]
    assignments = [f"{column} = excluded.{column}" for column in values]
    assignments.append("updated_at = excluded.updated_at")
    connection.execute(
        f"INSERT INTO {sql_table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)}) "
        f"ON CONFLICT(airtable_record_id) DO UPDATE SET {', '.join(assignments)}",
        parameters,
    )
    raw_json = _json(fields)
    connection.execute(
        """
        INSERT INTO airtable_record_map(
            airtable_table_id, airtable_record_id, local_id, raw_fields_json, imported_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(airtable_table_id, airtable_record_id) DO UPDATE SET
            local_id = excluded.local_id,
            raw_fields_json = excluded.raw_fields_json,
            imported_at = excluded.imported_at
        """,
        (table_id, airtable_record_id, local_id, raw_json, now),
    )
    return local_id


def _replace_record_links(
    connection: sqlite3.Connection,
    table: dict[str, Any],
    local_id: str,
    fields: dict[str, Any],
) -> int:
    table_id = str(table["id"])
    source = connection.execute(
        "SELECT id FROM airtable_record_map WHERE airtable_table_id = ? AND local_id = ?",
        (table_id, local_id),
    ).fetchone()
    assert source is not None
    field_by_id = {str(field["id"]): field for field in table["fields"]}
    count = 0
    for field_id, value in fields.items():
        if field_id not in LINK_SPECS:
            continue
        field = field_by_id[field_id]
        target_table_id = str(field["config"]["linkedTableId"])
        connection.execute(
            "DELETE FROM airtable_record_links WHERE source_map_id = ? AND airtable_field_id = ?",
            (source["id"], field_id),
        )
        for position, target_record_id in enumerate(_linked_record_ids(value)):
            target = connection.execute(
                """
                SELECT id FROM airtable_record_map
                WHERE airtable_table_id = ? AND airtable_record_id = ?
                """,
                (target_table_id, target_record_id),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO airtable_record_links(
                    source_map_id, airtable_field_id, target_table_id,
                    target_airtable_record_id, target_map_id, position
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source["id"],
                    field_id,
                    target_table_id,
                    target_record_id,
                    target["id"] if target is not None else None,
                    position,
                ),
            )
            count += 1
    return count


def _resolve_record_links(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE airtable_record_links
        SET target_map_id = (
            SELECT target.id
            FROM airtable_record_map AS target
            WHERE target.airtable_table_id = airtable_record_links.target_table_id
              AND target.airtable_record_id = airtable_record_links.target_airtable_record_id
        )
        WHERE target_map_id IS NULL
        """
    )


def _materialize_domain_links(connection: sqlite3.Connection) -> None:
    join_tables = sorted(
        {spec.table for spec in LINK_SPECS.values() if isinstance(spec, JoinLink)}
    )
    for table in join_tables:
        connection.execute(f"DELETE FROM {table} WHERE origin = 'airtable'")
    for table, columns in {
        "case_participants": ("contact_id", "case_id"),
        "document_links": ("source_document_id", "target_document_id"),
        "compliance_flags": ("document_id",),
        "document_version_match": ("user_document_id", "court_document_id"),
    }.items():
        assignments = ", ".join(f"{column} = NULL" for column in columns)
        connection.execute(
            f"UPDATE {table} SET {assignments} WHERE airtable_record_id IS NOT NULL"
        )

    rows = connection.execute(
        """
        SELECT
            links.airtable_field_id,
            source.local_id AS source_local_id,
            target.local_id AS target_local_id
        FROM airtable_record_links AS links
        JOIN airtable_record_map AS source ON source.id = links.source_map_id
        JOIN airtable_record_map AS target ON target.id = links.target_map_id
        ORDER BY links.source_map_id, links.airtable_field_id, links.position
        """
    ).fetchall()
    now = _now()
    for row in rows:
        spec = LINK_SPECS[str(row["airtable_field_id"])]
        if isinstance(spec, ReferenceLink):
            entity_id = row["source_local_id"] if spec.entity_side == "source" else row["target_local_id"]
            reference_id = row["target_local_id"] if spec.entity_side == "source" else row["source_local_id"]
            connection.execute(
                f"UPDATE {spec.table} SET {spec.column} = ? WHERE id = ?",
                (reference_id, entity_id),
            )
            continue
        values: dict[str, Any] = {
            spec.source_column: row["source_local_id"],
            spec.target_column: row["target_local_id"],
            **dict(spec.constants),
            "origin": "airtable",
            "created_at": now,
        }
        connection.execute(
            f"INSERT OR IGNORE INTO {spec.table} ({', '.join(values)}) "
            f"VALUES ({', '.join('?' for _ in values)})",
            list(values.values()),
        )


def _convert_scalar(field_id: str, field_type: str, value: Any) -> Any:
    if value is None:
        return None
    if field_id == "fldAbyAGj8TTMlgx6":
        participant_type = _choice_name(value)
        aliases = {
            "Фізична особа": "person",
            "Юридична особа": "organization",
            "person": "person",
            "organization": "organization",
        }
        try:
            return aliases[participant_type]
        except KeyError as exc:
            raise AirtableMappingError(f"Невідомий тип учасника: {participant_type}") from exc
    if field_type == "checkbox":
        return int(bool(value))
    if field_type == "number":
        return float(value)
    if field_type == "multipleAttachments":
        return _json(value if isinstance(value, list) else [value])
    if field_type == "singleSelect":
        return _choice_name(value)
    return value


def _choice_name(value: Any) -> str:
    if isinstance(value, dict) and "name" in value:
        return str(value["name"])
    return str(value)


def _linked_record_ids(value: Any) -> Iterable[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in items:
        record_id = item.get("id") if isinstance(item, dict) else item
        if record_id:
            result.append(str(record_id))
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
