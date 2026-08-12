from __future__ import annotations

import hashlib
import json
import os
import posixpath
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Protocol
from urllib.parse import urlsplit

from .frontmatter import parse_concept
from .model import Concept, Status
from .schema import SchemaValidationError
from .storage import (
    SCHEMA_VERSION,
    begin_transaction,
    create_database,
    recover_stale_transaction,
    state_directory,
    transactional_replace,
    write_staged,
    writer_lock,
)


@dataclass(frozen=True)
class IndexError:
    code: str
    relative_file: str = ""
    message: str = ""


@dataclass
class IndexReport:
    database_path: Path
    manifest: dict
    errors: list[IndexError]
    connection: sqlite3.Connection | None


@dataclass(frozen=True)
class GraphAnalysis:
    errors: tuple[IndexError, ...]
    links: tuple[tuple[str, str], ...]
    supersession: tuple[tuple[str, str], ...]


class CoverageContract(Protocol):
    paths: tuple[str, ...]
    concepts: tuple[str, ...]
    ignore: tuple[str, ...]


_EXCLUDED_DIRECTORY_NAMES = {".eos", ".git"}


def _metadata_hash(concept: Concept) -> str:
    payload = {
        "claims": [
            {"id": claim.id, "normalized_value": claim.normalized_value}
            for claim in concept.claims
        ],
        "description": concept.description,
        "generated": concept.generated,
        "resource": concept.resource,
        "source_paths": list(concept.source_paths),
        "sources": list(concept.sources),
        "status": concept.status.value,
        "supersedes": list(concept.supersedes),
        "title": concept.title,
        "type": concept.concept_type,
        "tags": list(concept.tags),
        "project": concept.project,
        "components": list(concept.components),
        "symptoms": list(concept.symptoms),
        "verified": list(concept.verified),
        "source_revision": concept.source_revision,
        "stale_after": concept.stale_after,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_excluded(relative: Path) -> bool:
    return any(part in _EXCLUDED_DIRECTORY_NAMES for part in relative.parts)


def _discover(root: Path) -> tuple[list[Concept], list[IndexError]]:
    if not root.is_dir():
        return [], [
            IndexError(
                "invalid_kb_root",
                root.as_posix(),
                "Knowledge root must be an existing directory.",
            )
        ]
    concepts: list[Concept] = []
    errors: list[IndexError] = []
    for path in sorted(root.rglob("*.md")):
        relative_path = path.relative_to(root)
        if _is_excluded(relative_path):
            continue
        relative = relative_path.as_posix()
        try:
            concept = parse_concept(path, root=root)
        except SchemaValidationError as exc:
            if _is_generated(path):
                continue
            errors.append(IndexError("invalid_concept", relative, str(exc)))
            continue
        if not concept.generated:
            concepts.append(concept)
    return concepts, errors


def _local_target(source: str, link: str) -> str | None:
    if link.startswith("//"):
        return None
    parsed = urlsplit(link)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    return posixpath.normpath(
        posixpath.join(Path(source).parent.as_posix(), parsed.path)
    )


def _cycle_errors(edges: dict[str, set[str]]) -> list[IndexError]:
    errors: list[IndexError] = []
    reported: set[frozenset[str]] = set()

    def visit(node: str, path: list[str]) -> None:
        for target in sorted(edges.get(node, set())):
            if target in path:
                cycle = frozenset(path[path.index(target) :])
                if cycle not in reported:
                    reported.add(cycle)
                    errors.append(
                        IndexError(
                            "supersession_cycle",
                            min(cycle),
                            "Supersession relationships must be acyclic.",
                        )
                    )
            else:
                visit(target, [*path, target])

    for start in sorted(edges):
        visit(start, [start])
    return errors


def _analyze_graph(
    root: Path,
    concepts: list[Concept],
    discovery_errors: list[IndexError],
    generated_incoming: set[str] | None = None,
) -> GraphAnalysis:
    errors = list(discovery_errors)
    by_path = {concept.relative_file: concept for concept in concepts}
    by_resource: dict[str, str] = {}
    for concept in concepts:
        if not concept.resource:
            continue
        if concept.resource in by_resource:
            errors.append(
                IndexError(
                    "duplicate_resource",
                    concept.relative_file,
                    concept.resource,
                )
            )
        else:
            by_resource[concept.resource] = concept.relative_file

    links: list[tuple[str, str]] = []
    incoming = set(generated_incoming or ())
    for concept in concepts:
        for link in concept.links:
            target = _local_target(concept.relative_file, link.target)
            if target is None:
                continue
            links.append((concept.relative_file, target))
            target_concept = by_path.get(target)
            if target_concept is not None:
                incoming.add(target)
                if (
                    concept.status is not Status.DEPRECATED
                    and target_concept.status is Status.DEPRECATED
                ):
                    errors.append(
                        IndexError(
                            "deprecated_current_link",
                            concept.relative_file,
                            target,
                        )
                    )
            elif target.endswith(".md") and not (root / target).is_file():
                errors.append(IndexError("broken_link", concept.relative_file, target))

    for concept in concepts:
        if concept.relative_file not in incoming:
            errors.append(
                IndexError(
                    "orphan",
                    concept.relative_file,
                    "No concept links to this concept.",
                )
            )

    supersession: list[tuple[str, str]] = []
    supersession_edges: dict[str, set[str]] = {
        concept.relative_file: set() for concept in concepts
    }
    for concept in concepts:
        for declared_target in concept.supersedes:
            target = (
                declared_target
                if declared_target in by_path
                else by_resource.get(declared_target)
            )
            if target is None:
                errors.append(
                    IndexError(
                        "invalid_supersession",
                        concept.relative_file,
                        declared_target,
                    )
                )
                continue
            supersession.append((concept.relative_file, target))
            supersession_edges[concept.relative_file].add(target)
    errors.extend(_cycle_errors(supersession_edges))
    errors.sort(key=lambda item: (item.code, item.relative_file, item.message))
    return GraphAnalysis(tuple(errors), tuple(links), tuple(supersession))


def _is_generated(path: Path) -> bool:
    try:
        return parse_concept(path, root=path.parent).generated
    except Exception:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return False
        if not lines or lines[0] != "---":
            return False
        for line in lines[1:]:
            if line in {"---", "..."}:
                return False
            key, separator, value = line.partition(":")
            if separator and key.strip() == "generated":
                return value.strip().lower() == "true"
        return False


def _directories(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    directories = [Path(".")]
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_dir() and not path.is_symlink() and not _is_excluded(relative):
            directories.append(relative)
    return sorted(set(directories), key=lambda item: (len(item.parts), item.as_posix()))


def _router_content(
    directory: str,
    concepts: list[Concept],
    child_dirs: list[str],
) -> bytes:
    title = (
        "Knowledge Index"
        if directory == "."
        else Path(directory).name.replace("-", " ").title()
    )
    lines = [
        "---",
        "type: index",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        "description: Generated directory router.",
        "generated: true",
        "---",
        f"# {title}",
        "",
    ]
    base = Path(directory)
    for concept in sorted(
        concepts,
        key=lambda item: (item.title.casefold(), item.relative_file),
    ):
        link = Path(os.path.relpath(concept.relative_file, base)).as_posix()
        marker = f" ({concept.concept_type}, {concept.status.value})"
        lines.append(
            f"- [{concept.title or concept.relative_file}]({link}) - "
            f"{concept.description or concept.title}{marker}"
        )
    for child in child_dirs:
        link = Path(os.path.relpath(Path(child) / "index.md", base)).as_posix()
        child_title = Path(child).name.replace("-", " ").title()
        lines.append(f"- [{child_title}]({link}) - Child directory")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _routers(
    root: Path,
    concepts: list[Concept],
) -> tuple[dict[str, bytes], dict, set[str]]:
    by_dir: dict[Path, list[Concept]] = {}
    for concept in concepts:
        by_dir.setdefault(Path(concept.relative_file).parent, []).append(concept)
    concept_paths = {concept.relative_file for concept in concepts}
    contents: dict[str, bytes] = {}
    manifest: dict[str, dict] = {}
    generated_incoming: set[str] = set()
    for directory in _directories(root):
        router = (directory / "index.md").as_posix()
        existing_router = root / router
        if existing_router.exists() and not _is_generated(existing_router):
            continue
        directory_path = root if directory == Path(".") else root / directory
        child_dirs = sorted(
            child.relative_to(root).as_posix()
            for child in directory_path.iterdir()
            if child.is_dir()
            and not child.is_symlink()
            and child.name not in _EXCLUDED_DIRECTORY_NAMES
        )
        immediate = by_dir.get(directory, [])
        generated_incoming.update(concept.relative_file for concept in immediate)
        generated_incoming.update(
            f"{child}/index.md"
            for child in child_dirs
            if f"{child}/index.md" in concept_paths
        )
        data = _router_content(directory.as_posix(), immediate, child_dirs)
        inputs: list[dict[str, str]] = [
            {
                "path": concept.relative_file,
                "metadata_hash": _metadata_hash(concept),
            }
            for concept in sorted(immediate, key=lambda item: item.relative_file)
        ]
        inputs.extend({"directory": child} for child in child_dirs)
        input_hash = hashlib.sha256(
            json.dumps(inputs, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        contents[router] = data
        manifest[router] = {
            "input_hash": input_hash,
            "content_hash": hashlib.sha256(data).hexdigest(),
            "inputs": inputs,
        }
    return contents, manifest, generated_incoming


def _git_output(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _tracked_source_paths(root: Path) -> tuple[str, ...]:
    output = _git_output(root, "ls-files", "-z")
    if output is None:
        return ()
    return tuple(sorted(path for path in output.split("\0") if path))


def _safe_source_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts


def _is_git_object_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) in {40, 64}
        and all(character in "0123456789abcdef" for character in value)
    )


def _revision_blob(root: Path, revision: str, path: str) -> str | None:
    if not revision or revision.startswith("-") or not _safe_source_path(path):
        return None
    resolved = _git_output(
        root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{revision}^{{commit}}",
    )
    if not _is_git_object_id(resolved):
        return None
    output = _git_output(
        root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{resolved}:{path}",
    )
    return output if _is_git_object_id(output) else None


def _matches_source(path: str, patterns: Iterable[str]) -> bool:
    candidate = PurePosixPath(path)
    return any(candidate.match(pattern) for pattern in patterns)


def _manifest_source_blobs(
    concepts: list[Concept],
    source_root: Path | None,
    coverage_rules: tuple[CoverageContract, ...],
) -> dict[str, list[dict[str, str]]]:
    if source_root is None or not source_root.is_dir():
        return {}
    by_resource = {
        concept.resource: concept
        for concept in concepts
        if concept.resource is not None
    }
    blobs: dict[str, dict[str, str]] = {
        resource: {} for resource in by_resource
    }
    tracked_paths = _tracked_source_paths(source_root)
    for rule in coverage_rules:
        for path in tracked_paths:
            if not _matches_source(path, rule.paths) or _matches_source(path, rule.ignore):
                continue
            for resource in rule.concepts:
                concept = by_resource.get(resource)
                if concept is None or not concept.source_revision:
                    continue
                blob = _revision_blob(source_root, concept.source_revision, path)
                if blob is not None:
                    blobs[resource].setdefault(path, blob)
    for concept in concepts:
        if concept.resource is None:
            continue
        for path in concept.source_paths:
            blob = (
                _revision_blob(source_root, concept.source_revision, path)
                if concept.source_revision
                else None
            )
            if blob is not None:
                blobs[concept.resource][path] = blob
    return {
        resource: [
            {"path": path, "blob_hash": blob_hash}
            for path, blob_hash in sorted(resource_blobs.items())
        ]
        for resource, resource_blobs in sorted(blobs.items())
        if resource_blobs
    }


def _manifest(
    concepts: list[Concept],
    routers: dict,
    *,
    source_root: Path | None = None,
    coverage_rules: tuple[CoverageContract, ...] = (),
) -> dict:
    source_blobs = _manifest_source_blobs(concepts, source_root, coverage_rules)
    return {
        "schema_version": 1,
        "concepts": [
            dict(
                {
                    "path": concept.relative_file,
                    "resource": concept.resource,
                    "content_hash": concept.content_hash,
                    "metadata_hash": _metadata_hash(concept),
                },
                **(
                    {"source_blobs": source_blobs[concept.resource]}
                    if concept.resource in source_blobs
                    else {}
                ),
            )
            for concept in sorted(concepts, key=lambda item: item.relative_file)
        ],
        "routers": routers,
    }


def _build_database(
    path: Path,
    concepts: list[Concept],
    analysis: GraphAnalysis,
) -> None:
    connection = create_database(path)
    try:
        for concept in concepts:
            connection.execute(
                "INSERT INTO concepts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    concept.relative_file,
                    concept.resource,
                    concept.title,
                    concept.description,
                    concept.concept_type,
                    concept.status.value,
                    int(concept.generated),
                    concept.content_hash,
                    _metadata_hash(concept),
                    concept.project,
                    json.dumps(concept.tags, ensure_ascii=False),
                    json.dumps(concept.components, ensure_ascii=False),
                    json.dumps(concept.symptoms, ensure_ascii=False),
                    concept.trust.value,
                    concept.freshness.value,
                    json.dumps(concept.verified, ensure_ascii=False, sort_keys=True),
                    concept.body,
                    concept.source_revision,
                    concept.stale_after,
                ),
            )
            connection.execute(
                "INSERT INTO concepts_fts VALUES (?, ?)",
                (
                    concept.relative_file,
                    "\n".join((
                        concept.title,
                        concept.description,
                        concept.resource or "",
                        concept.concept_type,
                        concept.project or "",
                        *concept.tags,
                        *concept.components,
                        *concept.symptoms,
                        *concept.source_paths,
                        concept.body,
                    )),
                ),
            )
            for ordinal, heading in enumerate(concept.headings):
                connection.execute(
                    "INSERT INTO headings VALUES (?, ?, ?, ?)",
                    (concept.relative_file, ordinal, heading.level, heading.title),
                )
            for claim in concept.claims:
                connection.execute(
                    "INSERT INTO claims VALUES (?, ?, ?)",
                    (concept.relative_file, claim.id, claim.normalized_value),
                )
            for source in concept.sources:
                connection.execute(
                    "INSERT INTO sources VALUES (?, ?, ?)",
                    (concept.relative_file, "source", source),
                )
            for source_path in concept.source_paths:
                connection.execute(
                    "INSERT INTO sources VALUES (?, ?, ?)",
                    (concept.relative_file, "source_path", source_path),
                )
        for source, target in analysis.links:
            connection.execute("INSERT INTO links VALUES (?, ?)", (source, target))
            connection.execute(
                "INSERT INTO reverse_links VALUES (?, ?)",
                (source, target),
            )
        for source, target in analysis.supersession:
            connection.execute(
                "INSERT INTO supersession VALUES (?, ?)",
                (source, target),
            )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


def _is_sha256(value: object, *, content: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    expected_length = 71 if content else 64
    digest = value.removeprefix("sha256:") if content else value
    return (
        len(value) == expected_length
        and (not content or value.startswith("sha256:"))
        and all(character in "0123456789abcdef" for character in digest)
    )


def valid_manifest(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "concepts",
        "routers",
    }:
        return False
    concepts = value["concepts"]
    routers = value["routers"]
    if value["schema_version"] != 1 or not isinstance(concepts, list) or not isinstance(routers, dict):
        return False
    for concept in concepts:
        if not isinstance(concept, dict) or set(concept) not in ({
            "path",
            "resource",
            "content_hash",
            "metadata_hash",
        }, {
            "path",
            "resource",
            "content_hash",
            "metadata_hash",
            "source_blobs",
        }):
            return False
        if (
            not isinstance(concept["path"], str)
            or not concept["path"]
            or concept["resource"] is not None
            and not isinstance(concept["resource"], str)
            or not _is_sha256(concept["content_hash"], content=True)
            or not _is_sha256(concept["metadata_hash"])
        ):
            return False
        source_blobs = concept.get("source_blobs", [])
        if not isinstance(source_blobs, list):
            return False
        source_paths: set[str] = set()
        for source_blob in source_blobs:
            if (
                not isinstance(source_blob, dict)
                or set(source_blob) != {"path", "blob_hash"}
                or not isinstance(source_blob["path"], str)
                or not _safe_source_path(source_blob["path"])
                or source_blob["path"] in source_paths
                or not _is_git_object_id(source_blob["blob_hash"])
            ):
                return False
            source_paths.add(source_blob["path"])
    for router in routers.values():
        if not isinstance(router, dict) or set(router) != {
            "input_hash",
            "content_hash",
            "inputs",
        }:
            return False
        if (
            not _is_sha256(router["input_hash"])
            or not _is_sha256(router["content_hash"])
            or not isinstance(router["inputs"], list)
        ):
            return False
        for item in router["inputs"]:
            if not isinstance(item, dict):
                return False
            if set(item) == {"directory"}:
                if not isinstance(item["directory"], str) or not item["directory"]:
                    return False
            elif set(item) == {"path", "metadata_hash"}:
                if (
                    not isinstance(item["path"], str)
                    or not item["path"]
                    or not _is_sha256(item["metadata_hash"])
                ):
                    return False
            else:
                return False
    return True


def _load_manifest(path: Path) -> tuple[dict | None, IndexError | None]:
    if not path.exists():
        return None, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, IndexError(
            "manifest_corrupt",
            "manifest.json",
            "External index manifest is unreadable or malformed.",
        )
    if not valid_manifest(value):
        return None, IndexError(
            "manifest_corrupt",
            "manifest.json",
            "External index manifest does not match schema version 1.",
        )
    assert isinstance(value, dict)
    return value, None


def _open_existing_database(
    path: Path,
) -> tuple[sqlite3.Connection | None, IndexError | None]:
    if not path.is_file():
        return None, None
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            connection.close()
            return None, IndexError(
                "index_schema_mismatch",
                "index.sqlite3",
                f"External SQLite index schema is not version {SCHEMA_VERSION}; rebuild the index.",
            )
        connection.execute("PRAGMA schema_version").fetchone()
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("quick_check failed")
        return connection, None
    except sqlite3.DatabaseError:
        if connection is not None:
            connection.close()
        return None, IndexError(
            "index_corrupt",
            "index.sqlite3",
            "External SQLite index is corrupt or unreadable.",
        )


def _current_report(
    database: Path,
    manifest_path: Path,
    errors: list[IndexError],
) -> IndexReport:
    manifest, manifest_error = _load_manifest(manifest_path)
    connection, database_error = _open_existing_database(database)
    state_errors = [error for error in (manifest_error, database_error) if error]
    return IndexReport(
        database,
        manifest or {},
        sorted(
            [*errors, *state_errors],
            key=lambda item: (item.code, item.relative_file, item.message),
        ),
        connection,
    )


def _allowed_index_destinations(
    root: Path,
    database: Path,
    manifest_path: Path,
    router_contents: dict[str, bytes],
) -> frozenset[Path]:
    return frozenset(
        [
            database,
            manifest_path,
            *(root / relative for relative in router_contents),
        ]
    )


def index_bundle(
    root: Path,
    *,
    rebuild: bool = False,
    source_root: Path | None = None,
    coverage_rules: Iterable[CoverageContract] = (),
    state_path: Path | None = None,
) -> IndexReport:
    del rebuild
    root = root.expanduser().resolve()
    resolved_source_root = source_root.expanduser().resolve() if source_root else None
    resolved_coverage_rules = tuple(coverage_rules)
    state = state_path.expanduser().resolve() if state_path is not None else state_directory(root)
    database = state / "index.sqlite3"
    manifest_path = state / "manifest.json"
    recovery = state / "transaction.json"

    if recovery.exists():
        with writer_lock(state):
            recovery_concepts, _ = _discover(root)
            recovery_routers, _, _ = _routers(root, recovery_concepts)
            recover_stale_transaction(
                recovery,
                allowed_destinations=_allowed_index_destinations(
                    root,
                    database,
                    manifest_path,
                    recovery_routers,
                ),
            )

    concepts, discovery_errors = _discover(root)
    _, _, generated_incoming = _routers(root, concepts)
    analysis = _analyze_graph(root, concepts, discovery_errors, generated_incoming)
    if analysis.errors:
        return _current_report(database, manifest_path, list(analysis.errors))

    with writer_lock(state):
        concepts, discovery_errors = _discover(root)
        router_contents, router_manifest, generated_incoming = _routers(root, concepts)
        allowed_destinations = _allowed_index_destinations(
            root,
            database,
            manifest_path,
            router_contents,
        )
        recover_stale_transaction(
            recovery,
            allowed_destinations=allowed_destinations,
        )
        concepts, discovery_errors = _discover(root)
        router_contents, router_manifest, generated_incoming = _routers(root, concepts)
        allowed_destinations = _allowed_index_destinations(
            root,
            database,
            manifest_path,
            router_contents,
        )
        analysis = _analyze_graph(root, concepts, discovery_errors, generated_incoming)
        if analysis.errors:
            return _current_report(database, manifest_path, list(analysis.errors))

        manifest = _manifest(
            concepts,
            router_manifest,
            source_root=resolved_source_root,
            coverage_rules=resolved_coverage_rules,
        )
        transaction_id = uuid.uuid4().hex
        destinations = [database, manifest_path]
        destinations.extend(
            root / relative
            for relative in router_contents
            if not (root / relative).exists() or _is_generated(root / relative)
        )
        replacements = begin_transaction(
            destinations,
            recovery_path=recovery,
            transaction_id=transaction_id,
            allowed_destinations=allowed_destinations,
        )
        staged_db = replacements[database]
        try:
            write_staged(staged_db, b"")
            _build_database(staged_db, concepts, analysis)
            write_staged(
                replacements[manifest_path],
                json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
            )
            for relative, data in router_contents.items():
                destination = root / relative
                if destination in replacements:
                    write_staged(replacements[destination], data)
            transactional_replace(
                replacements,
                recovery_path=recovery,
                transaction_id=transaction_id,
                allowed_destinations=allowed_destinations,
            )
        except Exception:
            recover_stale_transaction(
                recovery,
                allowed_destinations=allowed_destinations,
            )
            raise
    return IndexReport(database, manifest, [], sqlite3.connect(database))


def _has_matching_direct_change_approval(
    root: Path,
    relative_file: str,
    content_hash: str,
) -> bool:
    approvals = root / ".eos" / "approvals.jsonl"
    if not approvals.is_file():
        return False
    try:
        records = [
            json.loads(line)
            for line in approvals.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return False
    return any(
        isinstance(record, dict)
        and record.get("proposal_id") == f"direct-change:{relative_file}"
        and record.get("decision") == "accepted"
        and record.get("base_target_hash") == content_hash
        and record.get("proposed_result_hash") == content_hash
        for record in records
    )


def validate_bundle(
    root: Path,
    *,
    strict: bool = False,
    source_root: Path | None = None,
    coverage_rules: Iterable[CoverageContract] = (),
) -> IndexReport:
    root = root.expanduser().resolve()
    resolved_source_root = source_root.expanduser().resolve() if source_root else None
    state = state_directory(root)
    database = state / "index.sqlite3"
    manifest_path = state / "manifest.json"
    concepts, discovery_errors = _discover(root)
    router_contents, router_manifest, generated_incoming = _routers(root, concepts)
    analysis = _analyze_graph(root, concepts, discovery_errors, generated_incoming)
    errors = list(analysis.errors)
    expected_manifest = _manifest(
        concepts,
        router_manifest,
        source_root=resolved_source_root,
        coverage_rules=tuple(coverage_rules),
    )
    current_manifest, manifest_error = _load_manifest(manifest_path)
    connection, database_error = _open_existing_database(database)
    errors.extend(error for error in (manifest_error, database_error) if error)

    if (
        current_manifest is None
        and manifest_error is None
        or connection is None
        and database_error is None
    ):
        errors.append(
            IndexError(
                "index_missing",
                "manifest.json",
                "Run kb index to create the external search state.",
            )
        )
    elif (
        connection is not None
        and connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
    ):
        errors.append(
            IndexError(
                "index_schema_mismatch",
                "index.sqlite3",
                "Run kb index --rebuild.",
            )
        )

    for relative, data in router_contents.items():
        path = root / relative
        if path.exists() and _is_generated(path):
            if path.read_bytes() != data:
                errors.append(
                    IndexError(
                        "router_drift",
                        relative,
                        "Generated router differs from deterministic output.",
                    )
                )
        elif strict:
            errors.append(
                IndexError(
                    "router_drift",
                    relative,
                    "Generated router is missing.",
                )
            )
    if strict and current_manifest is not None and current_manifest != expected_manifest:
        errors.append(
            IndexError(
                "index_drift",
                "manifest.json",
                "Manifest inputs or hashes are stale.",
            )
        )
    if strict and current_manifest is not None:
        baseline_by_path = {
            item["path"]: item
            for item in current_manifest.get("concepts", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        for concept in concepts:
            baseline = baseline_by_path.get(concept.relative_file)
            if baseline is not None and baseline.get("content_hash") == concept.content_hash:
                continue
            if _has_matching_direct_change_approval(root, concept.relative_file, concept.content_hash):
                continue
            errors.append(
                IndexError(
                    "unreviewed_direct_change",
                    concept.relative_file,
                    "Stable knowledge changed without an approval for its exact current content hash.",
                )
            )
    errors.sort(key=lambda item: (item.code, item.relative_file, item.message))
    return IndexReport(database, current_manifest or {}, errors, connection)
