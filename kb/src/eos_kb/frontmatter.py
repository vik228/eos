from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from .model import Claim, Concept, Freshness, Heading, Link, Status, Trust
from .normalize import ClaimNormalizationError, normalize_claim, normalized_content_hash
from .schema import SchemaValidationError


_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_LINK_RE = re.compile(r"!??\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")


class _DuplicateKeyError(yaml.YAMLError):
    def __init__(self, field_path: str, key: str) -> None:
        super().__init__(f"duplicate key {key!r} at {field_path}")
        self.field_path = field_path
        self.key = key


class _AliasNotAllowedError(yaml.YAMLError):
    pass


class _StrictSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent: Node | None, index: object) -> Node:
        if self.check_event(AliasEvent):
            event = self.get_event()
            raise _AliasNotAllowedError(f"YAML alias '*{event.anchor}' is not allowed")
        return super().compose_node(parent, index)

    def get_single_data(self) -> Any:
        node = self.get_single_node()
        if node is None:
            return None
        self._reject_duplicate_keys(node, "$")
        return self.construct_document(node)

    def _reject_duplicate_keys(self, node: Node, field_path: str) -> None:
        if isinstance(node, MappingNode):
            seen: set[tuple[str, str]] = set()
            for key_node, value_node in node.value:
                if isinstance(key_node, ScalarNode):
                    identity = (key_node.tag, key_node.value)
                    if identity in seen:
                        raise _DuplicateKeyError(field_path, key_node.value)
                    seen.add(identity)
                    child_path = f"{field_path}.{key_node.value}"
                else:
                    child_path = field_path
                self._reject_duplicate_keys(value_node, child_path)
        elif isinstance(node, SequenceNode):
            for index, item in enumerate(node.value):
                self._reject_duplicate_keys(item, f"{field_path}[{index}]")


def _error(code: str, filename: str, path: str, remediation: str) -> SchemaValidationError:
    return SchemaValidationError(code, filename, path, remediation)


def _load_yaml(raw: str, filename: str) -> Any:
    try:
        value = yaml.load(raw, Loader=_StrictSafeLoader)
    except _DuplicateKeyError as exc:
        raise _error(
            "frontmatter.duplicate_key",
            filename,
            exc.field_path,
            f"Remove the duplicate YAML key '{exc.key}'.",
        ) from exc
    except _AliasNotAllowedError as exc:
        raise _error(
            "frontmatter.alias_not_allowed",
            filename,
            "$",
            "Remove YAML aliases; write each value explicitly.",
        ) from exc
    except yaml.YAMLError as exc:
        raise _error(
            "frontmatter.unsafe_or_invalid_yaml", filename, "$", "Use safe YAML with valid scalar, sequence, and mapping values."
        ) from exc
    return {} if value is None else value


def _validate_non_blank_string(
    metadata: dict[str, Any], field: str, filename: str, prefix: str = "$"
) -> None:
    if field not in metadata:
        return
    value = metadata[field]
    if not isinstance(value, str) or not value.strip():
        raise _error(
            "schema.type",
            filename,
            f"{prefix}.{field}",
            f"Set '{field}' to a non-empty string.",
        )


def _validate_non_blank_string_list(
    metadata: dict[str, Any], field: str, filename: str, prefix: str = "$"
) -> None:
    if field not in metadata:
        return
    value = metadata[field]
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise _error(
            "schema.type",
            filename,
            f"{prefix}.{field}",
            f"Set '{field}' to a list of non-empty strings.",
        )


def _validate_eos_metadata(eos: dict[str, Any], filename: str) -> None:
    for field in ("project", "source_revision", "owner"):
        _validate_non_blank_string(eos, field, filename, "$.eos")
    for field in ("components", "symptoms", "source_paths", "supersedes"):
        _validate_non_blank_string_list(eos, field, filename, "$.eos")
    if "claims" in eos and not isinstance(eos["claims"], list):
        raise _error(
            "schema.type",
            filename,
            "$.eos.claims",
            "Set 'eos.claims' to a list of claim objects.",
        )
    if "verified" in eos and not isinstance(eos["verified"], list):
        raise _error(
            "schema.type", filename, "$.eos.verified",
            "Set 'eos.verified' to a list of evidence records.",
        )


def _validate_metadata(metadata: Any, filename: str) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise _error("schema.type", filename, "$", "Use a YAML mapping for the frontmatter.")
    if "type" not in metadata:
        raise _error("schema.required", filename, "$.type", "Add a non-empty string 'type' to the YAML frontmatter.")
    for field in ("type", "title", "description", "resource", "stale_after"):
        _validate_non_blank_string(metadata, field, filename)
    for field in ("tags", "sources"):
        _validate_non_blank_string_list(metadata, field, filename)
    if "authoritative" in metadata:
        raise _error("schema.derived_field", filename, "$.authoritative", "Remove 'authoritative'; it is derived from lifecycle and evidence.")
    if "status" in metadata and metadata["status"] not in tuple(item.value for item in Status):
        raise _error("schema.enum", filename, "$.status", "Set 'status' to draft, stable, or deprecated.")
    if "generated" in metadata and not isinstance(metadata["generated"], bool):
        raise _error("schema.type", filename, "$.generated", "Set 'generated' to a boolean.")
    if "verified" in metadata and not isinstance(metadata["verified"], list):
        raise _error("schema.type", filename, "$.verified", "Set 'verified' to a list.")
    if "eos" in metadata:
        eos = metadata["eos"]
        if not isinstance(eos, dict):
            raise _error("schema.type", filename, "$.eos", "Set 'eos' to a YAML mapping.")
        _validate_eos_metadata(eos, filename)
    return metadata


def _frontmatter_parts(document: str, filename: str) -> tuple[dict[str, Any], str]:
    if document.startswith("\ufeff"):
        raise _error("frontmatter.bom", filename, "$", "Remove the UTF-8 BOM so the file starts with '---'.")
    lines = document.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise _error("frontmatter.missing", filename, "$", "Start the document with a YAML frontmatter delimiter '---'.")
    close = next((index for index, line in enumerate(lines[1:], 1) if line.rstrip("\r\n") in {"---", "..."}), None)
    if close is None:
        raise _error("frontmatter.unclosed", filename, "$", "Close the YAML frontmatter with '---'.")
    metadata = _validate_metadata(_load_yaml("".join(lines[1:close]), filename), filename)
    return metadata, "".join(lines[close + 1 :])


def parse_concept_text(document: str, relative_file: str, *, trust: Trust = Trust.UNVERIFIED, freshness: Freshness = Freshness.UNKNOWN) -> Concept:
    metadata, body = _frontmatter_parts(document, relative_file)
    eos = metadata.get("eos") or {}
    claims: list[Claim] = []
    raw_claims = eos.get("claims", [])
    if not isinstance(raw_claims, list):
        raise _error("schema.type", relative_file, "$.eos.claims", "Set 'eos.claims' to a list of claim objects.")
    for index, raw_claim in enumerate(raw_claims):
        path = f"$.eos.claims[{index}]"
        if not isinstance(raw_claim, dict) or not isinstance(raw_claim.get("id"), str) or not raw_claim["id"].strip() or "value" not in raw_claim:
            raise _error("schema.claim", relative_file, path, "Each claim needs a non-empty string 'id' and a 'value'.")
        try:
            normalized = normalize_claim(raw_claim["value"])
        except ClaimNormalizationError as exc:
            value_path = f"{path}.value"
            suffix = exc.field_path[1:] if exc.field_path.startswith("$") else exc.field_path
            raise _error(exc.code, relative_file, f"{value_path}{suffix}", exc.remediation) from exc
        claims.append(Claim(raw_claim["id"], normalized))
    headings = tuple(Heading(len(match.group(1)), match.group(2)) for match in _HEADING_RE.finditer(body))
    links = tuple(Link(match.group(1)) for match in _LINK_RE.finditer(body))
    status = Status(metadata.get("status", Status.STABLE.value))
    generated = metadata.get("generated", False)
    source_paths = eos.get("source_paths", [])
    return Concept(
        relative_file=relative_file,
        concept_type=metadata["type"],
        resource=metadata.get("resource"),
        status=status,
        generated=generated,
        trust=trust,
        freshness=freshness,
        headings=headings,
        body=body,
        links=links,
        claims=tuple(claims),
        source_paths=tuple(source_paths),
        content_hash=normalized_content_hash(document),
        title=metadata.get("title", ""),
        description=metadata.get("description", ""),
        supersedes=tuple(eos.get("supersedes", [])),
        sources=tuple(metadata.get("sources", [])),
        tags=tuple(metadata.get("tags", [])),
        project=eos.get("project"),
        components=tuple(eos.get("components", [])),
        symptoms=tuple(eos.get("symptoms", [])),
        verified=tuple(metadata.get("verified", [])),
        source_revision=eos.get("source_revision"),
        stale_after=metadata.get("stale_after"),
    )


def parse_concept(path: Path, *, root: Path | None = None, trust: Trust = Trust.UNVERIFIED, freshness: Freshness = Freshness.UNKNOWN) -> Concept:
    base = root or path.parent
    relative_file = path.relative_to(base).as_posix()
    try:
        document = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise _error("frontmatter.unsafe_or_invalid_yaml", relative_file, "$", "Use UTF-8 Markdown with safe YAML frontmatter.") from exc
    return parse_concept_text(document, relative_file, trust=trust, freshness=freshness)
