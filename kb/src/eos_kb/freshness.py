from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from .indexer import valid_manifest
from .storage import SCHEMA_VERSION, atomic_write, state_directory, writer_lock


_REPORT_FIELDS = {
    "schema_version",
    "generated_at",
    "index_manifest_hash",
    "overall",
    "concepts",
    "sources",
    "external_sources",
    "time",
    "contradictions",
    "coverage",
    "warnings",
}
_FINDING_STATES = {"current", "pending", "drifted", "fresh", "stale", "unknown"}


class FreshnessValidationError(ValueError):
    def __init__(self, code: str, field_path: str, message: str) -> None:
        self.code = code
        self.field_path = field_path
        super().__init__(message)


@dataclass(frozen=True)
class CoverageRule:
    paths: tuple[str, ...]
    concepts: tuple[str, ...]
    ignore: tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingCoverage:
    resource: str
    path: str
    blob_hash: str


@dataclass(frozen=True)
class SourceFinding:
    resource: str
    path: str
    state: str
    baseline_blob: str | None = None
    current_blob: str | None = None
    current_path: str | None = None
    renamed: bool = False
    reason: str = ""


@dataclass(frozen=True)
class TimeFinding:
    resource: str
    stale_after: str
    state: str


@dataclass(frozen=True)
class ExternalSourceFinding:
    resource: str
    source: str
    state: str
    baseline_hash: str | None = None
    current_hash: str | None = None


@dataclass(frozen=True)
class Contradiction:
    project: str
    claim_id: str
    resources: tuple[str, ...]
    values: tuple[str, ...]


@dataclass(frozen=True)
class CoverageFinding:
    path: str
    state: str
    resources: tuple[str, ...] = ()
    current_blob: str | None = None


@dataclass(frozen=True)
class ConceptFreshness:
    resource: str
    state: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class FreshnessReport:
    schema_version: int
    generated_at: str
    index_manifest_hash: str
    overall: str
    concepts: tuple[ConceptFreshness, ...]
    sources: tuple[SourceFinding, ...]
    external_sources: tuple[ExternalSourceFinding, ...]
    time: tuple[TimeFinding, ...]
    contradictions: tuple[Contradiction, ...]
    coverage: tuple[CoverageFinding, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FreshnessOverlay:
    state: str
    warnings: tuple[str, ...]


def _git(root: Path, *arguments: str) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return 127, ""
    return completed.returncode, completed.stdout.strip()


def _valid_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _diff_entries(root: Path, revision: str) -> tuple[dict[str, str], set[str]]:
    code, output = _git(root, "diff", "--find-renames", "--name-status", revision, "--")
    if code != 0:
        return {}, set()
    renames: dict[str, str] = {}
    changed: set[str] = set()
    for line in output.splitlines():
        fields = line.split("\t")
        if not fields:
            continue
        if fields[0].startswith("R") and len(fields) == 3:
            renames[fields[1]] = fields[2]
            changed.add(fields[2])
        elif len(fields) >= 2:
            changed.add(fields[1])
    return renames, changed


def _untracked(root: Path) -> set[str]:
    code, output = _git(root, "ls-files", "--others", "--exclude-standard")
    return set(output.splitlines()) if code == 0 and output else set()


def _blob_at_revision(root: Path, revision: str, path: str) -> str | None:
    code, output = _git(root, "rev-parse", f"{revision}:{path}")
    return output if code == 0 and output else None


def _resolve_revision(root: Path, revision: str) -> str | None:
    if re.fullmatch(r"[0-9a-fA-F]{7,64}", revision) is None:
        return None
    code, output = _git(
        root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{revision}^{{commit}}",
    )
    return output if code == 0 and re.fullmatch(r"[0-9a-f]{40,64}", output) else None


def _current_blob(root: Path, path: str) -> str | None:
    candidate = (root / path).resolve()
    root_resolved = root.resolve()
    if not candidate.is_relative_to(root_resolved) or not candidate.is_file():
        return None
    code, output = _git(root, "hash-object", "--", path)
    return output if code == 0 and output else None


def _matches(path: str, patterns: Iterable[str]) -> bool:
    candidate = PurePosixPath(path)
    return any(candidate.match(pattern) for pattern in patterns)


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _external_path(source: str) -> Path | None:
    parsed = urlparse(source)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if not parsed.scheme:
        return Path(source).expanduser()
    return None


def _sha256(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _index_manifest(root: Path) -> tuple[dict[str, Any], str]:
    path = state_directory(root) / "manifest.json"
    try:
        data = path.read_bytes()
        value = json.loads(data)
    except (OSError, json.JSONDecodeError) as exc:
        raise FreshnessValidationError(
            "freshness.index_corrupt",
            "$.index",
            "knowledge index manifest is missing or corrupt; run kb index --rebuild",
        ) from exc
    if not valid_manifest(value):
        raise FreshnessValidationError(
            "freshness.index_corrupt",
            "$.index",
            "knowledge index manifest is missing or corrupt; run kb index --rebuild",
        )
    return value, hashlib.sha256(data).hexdigest()


def _index_manifest_hash(root: Path) -> str:
    return _index_manifest(root)[1]


def _report_from_dict(value: dict[str, Any]) -> FreshnessReport:
    return FreshnessReport(
        schema_version=int(value["schema_version"]),
        generated_at=str(value["generated_at"]),
        index_manifest_hash=str(value["index_manifest_hash"]),
        overall=str(value["overall"]),
        concepts=tuple(
            ConceptFreshness(
                resource=item["resource"],
                state=item["state"],
                reasons=tuple(item.get("reasons", [])),
            )
            for item in value.get("concepts", [])
        ),
        sources=tuple(SourceFinding(**item) for item in value.get("sources", [])),
        external_sources=tuple(
            ExternalSourceFinding(**item) for item in value.get("external_sources", [])
        ),
        time=tuple(TimeFinding(**item) for item in value.get("time", [])),
        contradictions=tuple(
            Contradiction(
                project=item["project"],
                claim_id=item["claim_id"],
                resources=tuple(item["resources"]),
                values=tuple(item["values"]),
            )
            for item in value.get("contradictions", [])
        ),
        coverage=tuple(
            CoverageFinding(
                path=item["path"],
                state=item["state"],
                resources=tuple(item.get("resources", [])),
                current_blob=item.get("current_blob"),
            )
            for item in value.get("coverage", [])
        ),
        warnings=tuple(value.get("warnings", [])),
    )


def load_freshness(root: Path) -> FreshnessReport:
    path = state_directory(root) / "freshness.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("freshness state is missing or corrupt; run kb audit") from exc
    if (
        not isinstance(value, dict)
        or set(value) != _REPORT_FIELDS
        or value.get("schema_version") != 1
        or value.get("overall") not in {"fresh", "stale", "unknown"}
        or not all(
            isinstance(value.get(field), list)
            for field in (
                "sources",
                "concepts",
                "external_sources",
                "time",
                "contradictions",
                "coverage",
                "warnings",
            )
        )
        or not all(isinstance(item, str) for item in value.get("warnings", []))
    ):
        raise ValueError("freshness state is missing or corrupt; run kb audit")
    try:
        report = _report_from_dict(value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("freshness state is missing or corrupt; run kb audit") from exc
    finding_states = [item.state for item in report.concepts]
    finding_states.extend(item.state for item in report.sources)
    finding_states.extend(item.state for item in report.external_sources)
    finding_states.extend(item.state for item in report.time)
    finding_states.extend(item.state for item in report.coverage)
    if any(state not in _FINDING_STATES for state in finding_states):
        raise ValueError("freshness state is missing or corrupt; run kb audit")
    try:
        current_manifest_hash = _index_manifest_hash(root)
    except FreshnessValidationError as exc:
        raise ValueError("freshness state does not match current index; run kb audit") from exc
    if report.index_manifest_hash != current_manifest_hash:
        raise ValueError("freshness state does not match current index; run kb audit")
    return report


def freshness_overlays(root: Path) -> dict[str, FreshnessOverlay]:
    report = load_freshness(root)
    states: dict[str, list[str]] = {}
    warnings: dict[str, set[str]] = {}

    def record(resource: str, state: str, warning: str | None = None) -> None:
        states.setdefault(resource, []).append(state)
        if warning is not None:
            warnings.setdefault(resource, set()).add(warning)

    for item in report.concepts:
        record(
            item.resource,
            item.state,
            f"freshness unknown: {item.resource}" if item.state == "unknown" else None,
        )

    for item in report.sources:
        warning = None
        if item.state == "drifted":
            warning = f"source drift: {item.resource} ({item.path})"
        elif item.state == "unknown":
            warning = f"source unknown: {item.resource} ({item.path})"
        record(item.resource, item.state, warning)
    for item in report.external_sources:
        warning = (
            f"external source {item.state}: {item.resource} ({item.source})"
            if item.state != "current"
            else None
        )
        record(item.resource, item.state, warning)
    for item in report.time:
        warning = (
            f"time {item.state}: {item.resource} ({item.stale_after})"
            if item.state != "current"
            else None
        )
        record(item.resource, item.state, warning)
    for item in report.contradictions:
        for resource in item.resources:
            record(
                resource,
                "stale",
                f"contradiction: {item.project}:{item.claim_id}",
            )
    for item in report.coverage:
        for resource in item.resources:
            record(
                resource,
                item.state,
                f"coverage {item.state}: {item.path}" if item.state != "current" else None,
            )

    overlays: dict[str, FreshnessOverlay] = {}
    for resource, values in states.items():
        if any(value in {"drifted", "stale", "pending"} for value in values):
            state = "stale"
        elif "unknown" in values:
            state = "unknown"
        else:
            state = "fresh"
        overlays[resource] = FreshnessOverlay(
            state,
            tuple(sorted(warnings.get(resource, set()))),
        )
    return overlays


def audit_freshness(
    root: Path,
    source_root: Path,
    *,
    now: datetime | None = None,
    coverage_rules: Iterable[CoverageRule] = (),
    pending_coverage: Iterable[PendingCoverage] = (),
) -> FreshnessReport:
    supplied_now = now or datetime.now(timezone.utc)
    if supplied_now.tzinfo is None:
        supplied_now = supplied_now.replace(tzinfo=timezone.utc)
    generated = supplied_now.astimezone(timezone.utc)
    if not source_root.is_dir():
        raise FreshnessValidationError(
            "freshness.source_root_missing",
            "$.source_root",
            "source workspace is missing or not a directory",
        )
    database = state_directory(root) / "index.sqlite3"
    if not database.is_file():
        raise FreshnessValidationError(
            "freshness.index_missing",
            "$.index",
            "knowledge index is missing; run kb index",
        )
    manifest, manifest_hash = _index_manifest(root)
    manifest_baselines = {
        (concept["resource"] or concept["path"], source["path"]): source["blob_hash"]
        for concept in manifest["concepts"]
        for source in concept.get("source_blobs", [])
    }
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise sqlite3.DatabaseError("schema version mismatch")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("quick_check failed")
        concepts = connection.execute(
            "SELECT relative_file, resource, project, status, verified, stale_after, "
            "source_revision FROM concepts ORDER BY relative_file"
        ).fetchall()
        indexed_sources: dict[str, dict[str, list[str]]] = {}
        for row in connection.execute(
            "SELECT relative_file, source_kind, source_value FROM sources "
            "ORDER BY relative_file, source_kind, source_value"
        ):
            indexed_sources.setdefault(row["relative_file"], {}).setdefault(
                row["source_kind"], []
            ).append(row["source_value"])
        claims = connection.execute(
            "SELECT c.project, c.status, c.resource, c.relative_file, cl.claim_id, "
            "cl.normalized_value FROM claims cl JOIN concepts c USING(relative_file) "
            "ORDER BY c.project, cl.claim_id, c.resource, c.relative_file"
        ).fetchall()
    except (OSError, sqlite3.DatabaseError) as exc:
        raise FreshnessValidationError(
            "freshness.index_corrupt",
            "$.index",
            "knowledge index is corrupt; run kb index --rebuild",
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    untracked = _untracked(source_root)
    revisions = sorted({row["source_revision"] for row in concepts if row["source_revision"]})
    resolved_revisions = {
        revision: _resolve_revision(source_root, revision)
        for revision in revisions
    }
    revision_diffs = {
        revision: _diff_entries(source_root, resolved)
        for revision, resolved in resolved_revisions.items()
        if resolved is not None
    }
    source_findings: list[SourceFinding] = []
    external_findings: list[ExternalSourceFinding] = []
    time_findings: list[TimeFinding] = []
    concept_by_resource: dict[str, sqlite3.Row] = {
        (row["resource"] or row["relative_file"]): row for row in concepts
    }
    rules = tuple(coverage_rules)
    for rule_index, rule in enumerate(rules):
        for concept_index, resource in enumerate(rule.concepts):
            if resource not in concept_by_resource:
                raise FreshnessValidationError(
                    "freshness.coverage_resource_missing",
                    f"$.coverage[{rule_index}].concepts[{concept_index}]",
                    f"coverage resource is not indexed: {resource}",
                )

    for row in concepts:
        resource = row["resource"] or row["relative_file"]
        sources = indexed_sources.get(row["relative_file"], {})
        raw_revision = row["source_revision"]
        revision = resolved_revisions.get(raw_revision) if raw_revision else None
        renames = revision_diffs.get(raw_revision, ({}, set()))[0] if revision else {}
        for declared_path in sources.get("source_path", []):
            current_path = renames.get(declared_path, declared_path)
            manifest_baseline = manifest_baselines.get((resource, declared_path))
            if not _valid_relative_path(declared_path):
                state, reason = "unknown", "invalid source path"
                baseline = current = None
            elif manifest_baseline is None and not revision:
                state, reason = "unknown", "source revision is missing"
                baseline = current = None
            else:
                baseline = manifest_baseline
                if baseline is None and revision:
                    baseline = _blob_at_revision(source_root, revision, declared_path)
                current = _current_blob(source_root, current_path)
                if current_path in untracked or baseline is None:
                    state, reason = "unknown", "source baseline is unavailable"
                elif current is None or current != baseline:
                    state, reason = "drifted", "source content changed"
                else:
                    state, reason = "current", "source content matches baseline"
            source_findings.append(
                SourceFinding(
                    resource=resource,
                    path=declared_path,
                    state=state,
                    baseline_blob=baseline,
                    current_blob=current,
                    current_path=current_path,
                    renamed=current_path != declared_path,
                    reason=reason,
                )
            )

        verified = json.loads(row["verified"] or "[]")
        baselines = {
            item.get("source"): item.get("content_hash")
            for item in verified
            if isinstance(item, dict)
            and isinstance(item.get("source"), str)
            and isinstance(item.get("content_hash"), str)
        }
        for source in sources.get("source", []):
            baseline_hash = baselines.get(source)
            approved_hash = (
                baseline_hash
                if baseline_hash
                and re.fullmatch(r"sha256:[0-9a-f]{64}", baseline_hash)
                else None
            )
            external_path = _external_path(source) if approved_hash else None
            current_hash = _sha256(external_path) if external_path else None
            if approved_hash is None or current_hash is None:
                external_state = "unknown"
            elif approved_hash == current_hash:
                external_state = "current"
            else:
                external_state = "drifted"
            external_findings.append(
                ExternalSourceFinding(
                    resource, source, external_state, approved_hash, current_hash
                )
            )

        if row["stale_after"]:
            stale_at = _parse_time(row["stale_after"])
            time_state = "unknown" if stale_at is None else (
                "stale" if generated >= stale_at else "current"
            )
            time_findings.append(TimeFinding(resource, row["stale_after"], time_state))

    grouped_claims: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for row in claims:
        if row["status"] == "deprecated":
            continue
        resource = row["resource"] or row["relative_file"]
        grouped_claims.setdefault((row["project"] or "", row["claim_id"]), []).append(
            (resource, row["normalized_value"])
        )
    contradictions: list[Contradiction] = []
    for (project, claim_id), entries in sorted(grouped_claims.items()):
        values = tuple(sorted({value for _, value in entries}))
        if len(values) > 1:
            contradictions.append(
                Contradiction(
                    project,
                    claim_id,
                    tuple(sorted({resource for resource, _ in entries})),
                    values,
                )
            )

    _, changed_since_head = _diff_entries(source_root, "HEAD")
    changed_paths = changed_since_head | untracked
    implicit: dict[str, set[str]] = {}
    findings_by_resource_path: dict[tuple[str, str], SourceFinding] = {}
    for finding in source_findings:
        effective_path = finding.current_path or finding.path
        implicit.setdefault(effective_path, set()).add(finding.resource)
        findings_by_resource_path[(finding.resource, effective_path)] = finding
    candidate_paths = changed_paths | set(implicit)
    pending = {
        (item.resource, item.path, item.blob_hash)
        for item in pending_coverage
    }
    coverage_findings: list[CoverageFinding] = []
    for path in sorted(candidate_paths):
        resources = set(implicit.get(path, set()))
        matching_rules = tuple(rule for rule in rules if _matches(path, rule.paths))
        applicable_rules = tuple(
            rule for rule in matching_rules if not _matches(path, rule.ignore)
        )
        for rule in applicable_rules:
            resources.update(rule.concepts)
        if matching_rules and not applicable_rules and not resources:
            continue
        current_blob = _current_blob(source_root, path)
        if not resources:
            coverage_state = "unknown"
        elif path in untracked or current_blob is None:
            coverage_state = "unknown"
        else:
            resource_states: list[str] = []
            for resource in sorted(resources):
                implicit_finding = findings_by_resource_path.get((resource, path))
                if implicit_finding and implicit_finding.state == "current":
                    resource_states.append("current")
                    continue
                if implicit_finding and implicit_finding.state == "unknown":
                    resource_states.append("unknown")
                    continue
                row = concept_by_resource.get(resource)
                raw_revision = row["source_revision"] if row is not None else None
                resolved_revision = (
                    resolved_revisions.get(raw_revision) if raw_revision else None
                )
                baseline = manifest_baselines.get((resource, path))
                if baseline is None and resolved_revision:
                    baseline = _blob_at_revision(source_root, resolved_revision, path)
                if baseline == current_blob:
                    resource_states.append("current")
                elif (resource, path, current_blob) in pending:
                    resource_states.append("pending")
                elif baseline is None:
                    resource_states.append("unknown")
                else:
                    resource_states.append("drifted")
            coverage_state = (
                "current" if "current" in resource_states else
                "pending" if "pending" in resource_states else
                "drifted" if "drifted" in resource_states else
                "unknown"
            )
        coverage_findings.append(
            CoverageFinding(path, coverage_state, tuple(sorted(resources)), current_blob)
        )

    warnings: set[str] = set()
    warnings.update(
        f"source drift: {item.resource} ({item.path})"
        for item in source_findings
        if item.state == "drifted"
    )
    warnings.update(
        f"source unknown: {item.resource} ({item.path})"
        for item in source_findings
        if item.state == "unknown"
    )
    warnings.update(
        f"external source {item.state}: {item.resource} ({item.source})"
        for item in external_findings
        if item.state != "current"
    )
    warnings.update(
        f"time {item.state}: {item.resource} ({item.stale_after})"
        for item in time_findings
        if item.state != "current"
    )
    warnings.update(
        f"contradiction: {item.project}:{item.claim_id}"
        for item in contradictions
    )
    warnings.update(
        f"coverage {item.state}: {item.path}"
        for item in coverage_findings
        if item.state != "current"
    )
    resource_states: dict[str, list[str]] = {
        (row["resource"] or row["relative_file"]): [] for row in concepts
    }
    for item in source_findings:
        resource_states[item.resource].append(item.state)
    for item in external_findings:
        resource_states[item.resource].append(item.state)
    for item in time_findings:
        resource_states[item.resource].append(item.state)
    for item in contradictions:
        for resource in item.resources:
            resource_states.setdefault(resource, []).append("stale")
    for item in coverage_findings:
        for resource in item.resources:
            if resource in resource_states:
                resource_states[resource].append(item.state)
    concept_freshness: list[ConceptFreshness] = []
    for resource, values in sorted(resource_states.items()):
        if any(value in {"drifted", "stale", "pending"} for value in values):
            concept_state = "stale"
        elif "unknown" in values or not values:
            concept_state = "unknown"
        else:
            concept_state = "fresh"
        concept_freshness.append(
            ConceptFreshness(resource, concept_state, tuple(sorted(set(values))))
        )
        if concept_state == "unknown":
            warnings.add(f"freshness unknown: {resource}")

    aggregate_states = [item.state for item in concept_freshness]
    aggregate_states.extend(
        item.state for item in coverage_findings if not item.resources
    )
    if any(state in {"drifted", "stale", "pending"} for state in aggregate_states):
        overall = "stale"
    elif any(state == "unknown" for state in aggregate_states):
        overall = "unknown"
    else:
        overall = "fresh"
    report = FreshnessReport(
        1,
        generated.isoformat(),
        manifest_hash,
        overall,
        tuple(concept_freshness),
        tuple(sorted(source_findings, key=lambda item: (item.resource, item.path))),
        tuple(sorted(external_findings, key=lambda item: (item.resource, item.source))),
        tuple(sorted(time_findings, key=lambda item: item.resource)),
        tuple(contradictions),
        tuple(coverage_findings),
        tuple(sorted(warnings)),
    )
    destination = state_directory(root) / "freshness.json"
    with writer_lock(destination.parent):
        atomic_write(
            destination,
            json.dumps(report.as_dict(), indent=2, sort_keys=True).encode("utf-8"),
        )
    return report
