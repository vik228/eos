from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from eos_kb.frontmatter import parse_concept, parse_concept_text
from eos_kb.model import Freshness, Status, Trust
from eos_kb.schema import SchemaValidationError, load_schema


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "concepts"
SCHEMA_DIR = Path(__file__).parents[2] / "configs" / "kb" / "schemas"


def error_fields(error: SchemaValidationError) -> dict[str, str]:
    return {
        "code": error.code,
        "relative_file": error.relative_file,
        "field_path": error.field_path,
        "remediation": error.remediation,
    }


def test_frontmatter_rejects_utf8_bom() -> None:
    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text("\ufeff---\ntype: Reference\n---\n# Body\n", "areas/bom.md")

    assert error_fields(captured.value) == {
        "code": "frontmatter.bom",
        "relative_file": "areas/bom.md",
        "field_path": "$",
        "remediation": "Remove the UTF-8 BOM so the file starts with '---'.",
    }


def test_frontmatter_rejects_unsafe_yaml_tags() -> None:
    document = "---\ntype: !!python/object/apply:os.system ['echo unsafe']\n---\n"

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "areas/unsafe.md")

    assert captured.value.code == "frontmatter.unsafe_or_invalid_yaml"
    assert captured.value.relative_file == "areas/unsafe.md"
    assert captured.value.field_path == "$"
    assert "safe YAML" in captured.value.remediation


@pytest.mark.parametrize(
    ("document", "field_path"),
    (
        ("---\ntype: Reference\ntype: Decision\n---\n", "$"),
        (
            """---
type: Invariant
eos:
  claims:
    - id: invariant.value
      value:
        enabled: true
        enabled: false
---
""",
            "$.eos.claims[0].value",
        ),
    ),
)
def test_frontmatter_rejects_exact_duplicate_yaml_keys(
    document: str, field_path: str
) -> None:
    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "invariants/duplicate-key.md")

    assert captured.value.code == "frontmatter.duplicate_key"
    assert captured.value.relative_file == "invariants/duplicate-key.md"
    assert captured.value.field_path == field_path
    assert "duplicate YAML key" in captured.value.remediation


@pytest.mark.parametrize(
    "document",
    (
        """---
type: Reference
tags: &shared [yaml]
sources: *shared
---
""",
        """---
type: Invariant
eos:
  claims:
    - id: invariant.cycle
      value: &cycle
        self: *cycle
---
""",
    ),
)
def test_frontmatter_rejects_yaml_aliases_and_cycles(document: str) -> None:
    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "invariants/alias.md")

    assert error_fields(captured.value) == {
        "code": "frontmatter.alias_not_allowed",
        "relative_file": "invariants/alias.md",
        "field_path": "$",
        "remediation": "Remove YAML aliases; write each value explicitly.",
    }


def test_frontmatter_reports_golden_error_for_missing_type() -> None:
    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text("---\ntitle: Missing type\n---\n# Body\n", "patterns/missing.md")

    assert error_fields(captured.value) == {
        "code": "schema.required",
        "relative_file": "patterns/missing.md",
        "field_path": "$.type",
        "remediation": "Add a non-empty string 'type' to the YAML frontmatter.",
    }


@pytest.mark.parametrize("invalid_type", ("", "   ", 3, None))
def test_frontmatter_rejects_invalid_type(invalid_type: object) -> None:
    document = f"---\ntype: {json.dumps(invalid_type)}\n---\n"

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "invalid-type.md")

    assert captured.value.code == "schema.type"
    assert captured.value.field_path == "$.type"


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("title", 3),
        ("description", False),
        ("resource", ["kb:test/reference"]),
        ("tags", "reference"),
        ("tags", ["reference", 3]),
        ("generated", "yes"),
        ("verified", "automated"),
        ("sources", "references/source.md"),
        ("sources", ["references/source.md", 3]),
        ("stale_after", 30),
    ),
)
def test_frontmatter_rejects_standard_fields_forbidden_by_schema(
    field: str, invalid_value: object
) -> None:
    document = f"---\ntype: Reference\n{field}: {json.dumps(invalid_value)}\n---\n"

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "references/invalid-standard.md")

    assert captured.value.code == "schema.type"
    assert captured.value.relative_file == "references/invalid-standard.md"
    assert captured.value.field_path == f"$.{field}"


@pytest.mark.parametrize(
    "field",
    ("type", "title", "description", "resource", "stale_after"),
)
def test_frontmatter_rejects_blank_standard_strings(field: str) -> None:
    metadata = "type: '   '" if field == "type" else f"type: Reference\n{field}: '   '"
    document = f"---\n{metadata}\n---\n"

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "references/blank-standard.md")

    assert captured.value.code == "schema.type"
    assert captured.value.field_path == f"$.{field}"


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("project", 3),
        ("components", "parser"),
        ("components", ["parser", 3]),
        ("symptoms", "invalid-frontmatter"),
        ("symptoms", ["invalid-frontmatter", False]),
        ("source_paths", "src/parser.py"),
        ("source_paths", ["src/parser.py", 3]),
        ("source_revision", 1234),
        ("owner", ["team:knowledge"]),
        ("supersedes", "references/old.md"),
        ("supersedes", ["references/old.md", None]),
        ("claims", {"id": "reference.value", "value": 1}),
    ),
)
def test_frontmatter_rejects_eos_fields_forbidden_by_schema(
    field: str, invalid_value: object
) -> None:
    eos = json.dumps({field: invalid_value})
    document = f"---\ntype: Reference\neos: {eos}\n---\n"

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "references/invalid-eos.md")

    assert captured.value.code == "schema.type"
    assert captured.value.relative_file == "references/invalid-eos.md"
    assert captured.value.field_path == f"$.eos.{field}"


def test_frontmatter_rejects_null_eos_mapping() -> None:
    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text("---\ntype: Reference\neos: null\n---\n", "references/null-eos.md")

    assert captured.value.code == "schema.type"
    assert captured.value.field_path == "$.eos"


@pytest.mark.parametrize(
    "field",
    ("project", "source_revision", "owner"),
)
def test_frontmatter_rejects_blank_eos_strings(field: str) -> None:
    document = f"---\ntype: Reference\neos:\n  {field}: '   '\n---\n"

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "references/blank-eos.md")

    assert captured.value.code == "schema.type"
    assert captured.value.field_path == f"$.eos.{field}"


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("tags", ["   "]),
        ("sources", [""]),
        ("components", ["   "]),
        ("symptoms", [""]),
        ("source_paths", ["   "]),
        ("supersedes", [""]),
    ),
)
def test_frontmatter_rejects_blank_string_array_items(
    field: str, invalid_value: object
) -> None:
    if field in {"tags", "sources"}:
        metadata = f"{field}: {json.dumps(invalid_value)}"
        field_path = f"$.{field}"
    else:
        metadata = f"eos: {json.dumps({field: invalid_value})}"
        field_path = f"$.eos.{field}"
    document = f"---\ntype: Reference\n{metadata}\n---\n"

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "references/blank-list-item.md")

    assert captured.value.code == "schema.type"
    assert captured.value.field_path == field_path


def test_unknown_type_is_accepted_and_absent_status_defaults_to_stable() -> None:
    concept = parse_concept(FIXTURE_DIR / "unknown-type.md", root=FIXTURE_DIR)

    assert concept.concept_type == "Research Notebook"
    assert concept.status is Status.STABLE
    assert concept.trust is Trust.UNVERIFIED
    assert concept.freshness is Freshness.UNKNOWN
    assert concept.authoritative is False


def test_concept_exposes_parsed_content_and_eos_extensions() -> None:
    concept = parse_concept(
        FIXTURE_DIR / "unknown-type.md",
        root=FIXTURE_DIR,
        trust=Trust.HUMAN_REVIEWED,
        freshness=Freshness.FRESH,
    )

    assert concept.relative_file == "unknown-type.md"
    assert concept.resource == "kb:test/research-notebook"
    assert concept.authoritative is True
    assert tuple(heading.title for heading in concept.headings) == (
        "Research Notes",
        "Details",
    )
    assert concept.body.startswith("# Research Notes")
    assert tuple(link.target for link in concept.links) == ("../references/source.md",)
    assert concept.source_paths == ("src/research.py",)
    assert len(concept.claims) == 1
    assert concept.claims[0].id == "research.mode"
    assert concept.claims[0].normalized_value == '{"a":["é",true],"b":2}'
    assert concept.content_hash.startswith("sha256:")


def test_concept_preserves_standard_sources_separately_from_eos_source_paths() -> None:
    concept = parse_concept_text(
        """---
type: Reference
sources: [https://example.test/reference]
eos:
  source_paths: [src/reference.py]
---
# Reference
""",
        "references/source.md",
    )

    assert concept.sources == ("https://example.test/reference",)
    assert concept.source_paths == ("src/reference.py",)


@pytest.mark.parametrize(
    "changed_frontmatter",
    (
        "status: draft\nresource: kb:test/reference\neos:\n  claims:\n    - id: reference.value\n      value: 1",
        "status: stable\nresource: kb:test/changed\neos:\n  claims:\n    - id: reference.value\n      value: 1",
        "status: stable\nresource: kb:test/reference\neos:\n  claims:\n    - id: reference.value\n      value: 2",
    ),
)
def test_concept_hash_changes_with_meaningful_frontmatter(
    changed_frontmatter: str,
) -> None:
    baseline = """---
type: Reference
status: stable
resource: kb:test/reference
eos:
  claims:
    - id: reference.value
      value: 1
---
# Body
"""
    changed = f"---\ntype: Reference\n{changed_frontmatter}\n---\n# Body\n"

    baseline_concept = parse_concept_text(baseline, "references/hash.md")
    changed_concept = parse_concept_text(changed, "references/hash.md")

    assert changed_concept.body == baseline_concept.body
    assert changed_concept.content_hash != baseline_concept.content_hash


def test_concept_hash_normalizes_full_document_line_endings_and_unicode() -> None:
    composed = """---
type: Reference
title: Résumé
resource: kb:test/résumé
---
# Résumé
"""
    decomposed = composed.replace("é", "e\u0301").replace("\n", "\r\n")

    composed_concept = parse_concept_text(composed, "references/resume.md")
    decomposed_concept = parse_concept_text(decomposed, "references/resume.md")

    assert decomposed_concept.content_hash == composed_concept.content_hash


def test_concept_records_are_frozen() -> None:
    concept = parse_concept(FIXTURE_DIR / "unknown-type.md", root=FIXTURE_DIR)

    with pytest.raises(FrozenInstanceError):
        concept.status = Status.DRAFT  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        concept.headings[0].title = "Changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        concept.claims[0].id = "changed"  # type: ignore[misc]


def test_generated_concept_is_never_authoritative() -> None:
    concept = parse_concept(
        FIXTURE_DIR / "generated-router.md",
        root=FIXTURE_DIR,
        trust=Trust.HUMAN_REVIEWED,
        freshness=Freshness.FRESH,
    )

    assert concept.generated is True
    assert concept.authoritative is False


@pytest.mark.parametrize("invalid_status", ("current", ["stable"]))
def test_invalid_status_has_structured_remediation(invalid_status: object) -> None:
    document = f"---\ntype: Decision\nstatus: {json.dumps(invalid_status)}\n---\n"

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "decisions/invalid.md")

    assert error_fields(captured.value) == {
        "code": "schema.enum",
        "relative_file": "decisions/invalid.md",
        "field_path": "$.status",
        "remediation": "Set 'status' to draft, stable, or deprecated.",
    }


def test_authoritative_cannot_be_stored_in_frontmatter() -> None:
    document = "---\ntype: Decision\nauthoritative: true\n---\n"

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "decisions/stored-authority.md")

    assert captured.value.code == "schema.derived_field"
    assert captured.value.field_path == "$.authoritative"
    assert "Remove" in captured.value.remediation


def test_claim_errors_include_concept_file_and_claim_field_path() -> None:
    document = """---
type: Invariant
eos:
  claims:
    - id: invariant.value
      value: 1.5
---
"""

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "invariants/value.md")

    assert captured.value.code == "claim.float_not_allowed"
    assert captured.value.relative_file == "invariants/value.md"
    assert captured.value.field_path == "$.eos.claims[0].value"
    assert "integer" in captured.value.remediation


def test_claim_keys_that_collide_after_nfc_are_rejected_during_parse() -> None:
    document = """---
type: Invariant
eos:
  claims:
    - id: invariant.value
      value:
        "é": 1
        "e\u0301": 2
---
"""

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "invariants/duplicate.md")

    assert captured.value.code == "claim.duplicate_normalized_key"
    assert captured.value.field_path == "$.eos.claims[0].value"


@pytest.mark.parametrize(
    "claim",
    (
        "not-a-mapping",
        {"id": 3, "value": 1},
        {"id": "   ", "value": 1},
        {"id": "reference.value"},
    ),
)
def test_frontmatter_rejects_malformed_claim_shapes(claim: object) -> None:
    document = (
        "---\ntype: Reference\neos:\n  claims:\n    - "
        f"{json.dumps(claim)}\n---\n"
    )

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "references/invalid-claim.md")

    assert captured.value.code == "schema.claim"
    assert captured.value.field_path == "$.eos.claims[0]"


def test_frontmatter_rejects_nested_float_claim_values() -> None:
    document = """---
type: Reference
eos:
  claims:
    - id: reference.value
      value:
        nested: [1, {value: 2.5}]
---
"""

    with pytest.raises(SchemaValidationError) as captured:
        parse_concept_text(document, "references/nested-float.md")

    assert captured.value.code == "claim.float_not_allowed"
    assert captured.value.field_path == "$.eos.claims[0].value.nested[1].value"


def test_checked_in_schemas_are_versioned_json_schema_documents() -> None:
    concept_schema = load_schema("concept", version=1, schema_dir=SCHEMA_DIR)
    registry_schema = load_schema("registry", version=1, schema_dir=SCHEMA_DIR)

    assert concept_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert concept_schema["$id"].endswith("concept-v1.json")
    assert concept_schema["required"] == ["type"]
    assert registry_schema["$id"].endswith("registry-v1.json")
    assert registry_schema["required"] == ["workspaces"]


def test_concept_schema_recursively_allows_json_claim_values_without_numbers() -> None:
    concept_schema = load_schema("concept", version=1, schema_dir=SCHEMA_DIR)
    claim_value = concept_schema["$defs"]["claim_value"]
    variants = {variant.get("type"): variant for variant in claim_value["oneOf"]}

    assert claim_value["x-eos-no-floats"] is True
    assert claim_value["$comment"] == (
        "EOS raw YAML validation rejects floating-point nodes before JSON Schema "
        "validation because Draft 2020-12 integer semantics accept mathematically "
        "integral decimals such as 1.0."
    )
    assert set(variants) == {"null", "boolean", "integer", "string", "array", "object"}
    assert variants["array"]["items"] == {"$ref": "#/$defs/claim_value"}
    assert variants["object"]["additionalProperties"] == {
        "$ref": "#/$defs/claim_value"
    }
    assert concept_schema["$defs"]["claim"]["properties"]["value"] == {
        "$ref": "#/$defs/claim_value"
    }


def test_concept_schema_uses_non_blank_strings_where_runtime_does() -> None:
    concept_schema = load_schema("concept", version=1, schema_dir=SCHEMA_DIR)
    non_blank = {"type": "string", "pattern": r"\S"}

    for field in ("type", "title", "description", "resource", "stale_after"):
        assert concept_schema["properties"][field] == non_blank
    for field in ("tags", "sources"):
        assert concept_schema["properties"][field]["items"] == non_blank
    for field in ("project", "source_revision", "owner"):
        assert concept_schema["$defs"]["eos"]["properties"][field] == non_blank
    for field in ("components", "symptoms", "source_paths", "supersedes"):
        assert concept_schema["$defs"]["eos"]["properties"][field]["items"] == non_blank
    assert concept_schema["$defs"]["claim"]["properties"]["id"] == non_blank
