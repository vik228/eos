from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from .freshness import freshness_overlays
from .indexer import valid_manifest
from .model import Status
from .storage import SCHEMA_VERSION, state_directory


_TOKEN_RE = re.compile(r"[A-Za-z0-9_:/.-]+|--[A-Za-z0-9-]+")
_FLAG_RE = re.compile(r"--[A-Za-z0-9-]+")
_TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_EXCLUDED_TYPES = {"session log", "knowledge proposal"}
_REQUIRED_INDEX_COLUMNS = {
    "claims": ("relative_file", "claim_id", "normalized_value"),
    "concepts": (
        "relative_file", "resource", "title", "description", "type", "status",
        "generated", "content_hash", "metadata_hash", "project", "tags",
        "components", "symptoms", "trust", "freshness", "verified", "body",
        "source_revision",
        "stale_after",
    ),
    "concepts_fts": ("relative_file", "text"),
    "headings": ("relative_file", "ordinal", "level", "title"),
    "links": ("source", "target"),
    "reverse_links": ("source", "target"),
    "sources": ("relative_file", "source_kind", "source_value"),
    "supersession": ("source", "target"),
}


class RetrievalValidationError(ValueError):
    def __init__(self, code: str, field_path: str, message: str) -> None:
        self.code = code
        self.field_path = field_path
        super().__init__(message)


@dataclass(frozen=True)
class ResultCard:
    relative_file: str
    resource: str
    title: str
    type: str
    status: str
    trust: str
    freshness: str
    authority_label: str
    score: float
    reasons: tuple[str, ...]
    excerpt: str
    section: str = ""
    warnings: tuple[str, ...] = ()
    graph_distance: int = 0
    components: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    source_revision: str | None = None
    supersession_refs: tuple[str, ...] = ()
    contradiction_refs: tuple[str, ...] = ()
    unresolved_questions: str = ""

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        value["warnings"] = list(self.warnings)
        for field in (
            "components", "sources", "source_paths", "supersession_refs",
            "contradiction_refs",
        ):
            value[field] = list(value[field])
        return value


@dataclass(frozen=True)
class ContextResult:
    query: str
    budget: int
    estimated_units: int
    estimator: str
    warnings_reserved: bool
    warnings: tuple[str, ...]
    cards: tuple[ResultCard, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "budget": self.budget,
            "estimated_units": self.estimated_units,
            "estimator": self.estimator,
            "warnings_reserved": self.warnings_reserved,
            "warnings": list(self.warnings),
            "cards": [card.as_dict() for card in self.cards],
        }


def estimate_units(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / 2)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _db(root: Path) -> sqlite3.Connection:
    path = state_directory(root) / "index.sqlite3"
    if not path.is_file():
        raise ValueError("knowledge index is missing; run kb index")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise RetrievalValidationError(
                "retrieval.schema_mismatch",
                "$.index",
                f"knowledge index schema mismatch; rebuild with schema {SCHEMA_VERSION}",
            )
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("quick_check failed")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not _REQUIRED_INDEX_COLUMNS.keys() <= tables:
            raise sqlite3.DatabaseError("required index tables are missing")
        for table, expected_columns in _REQUIRED_INDEX_COLUMNS.items():
            actual_columns = tuple(
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            )
            if actual_columns != expected_columns:
                raise sqlite3.DatabaseError(f"invalid index table structure: {table}")
        fts_sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'concepts_fts'"
        ).fetchone()
        fts_sql = " ".join(str(fts_sql_row[0]).split()).casefold() if fts_sql_row else ""
        if not fts_sql.startswith("create virtual table") or " using fts5" not in fts_sql:
            raise sqlite3.DatabaseError("concepts_fts is not an FTS5 virtual table")
        return connection
    except RetrievalValidationError:
        if connection is not None:
            connection.close()
        raise
    except (OSError, sqlite3.DatabaseError) as exc:
        if connection is not None:
            connection.close()
        raise RetrievalValidationError(
            "retrieval.index_corrupt",
            "$.index",
            "knowledge index is corrupt; run kb index --rebuild",
        ) from exc


def _json_tuple(value: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return ()
    return tuple(str(item) for item in parsed) if isinstance(parsed, list) else ()


def _allowed(
    row: sqlite3.Row,
    *,
    project: str | None,
    types: Iterable[str] | None,
    components: Iterable[str] | None,
    status: str | None,
    freshness: str | None,
    include_draft: bool,
    include_deprecated: bool,
    history_intent: bool,
    freshness_override: str | None = None,
) -> bool:
    row_type = str(row["type"])
    row_status = str(row["status"])
    requested_types = set(types or ())
    requested_components = set(components or ())
    if project and row["project"] != project:
        return False
    if requested_types and row_type not in requested_types:
        return False
    if requested_components and not requested_components.intersection(_json_tuple(row["components"])):
        return False
    if status and row_status != status:
        return False
    if freshness and (freshness_override or row["freshness"]) != freshness:
        return False
    if row_status == Status.DRAFT and not (include_draft or status == Status.DRAFT):
        return False
    if row_status == Status.DEPRECATED and not (
        include_deprecated or status == Status.DEPRECATED
    ):
        return False
    if row_type.casefold() in _EXCLUDED_TYPES and row_type not in requested_types:
        return False
    if row["relative_file"].startswith("archive/") and not (history_intent or requested_types):
        return False
    return True


def _ranking_penalty(
    row: sqlite3.Row,
    freshness_override: str | None = None,
) -> tuple[float, list[str]]:
    penalty = 0.0
    reasons: list[str] = []
    if (freshness_override or row["freshness"]) == "stale":
        penalty -= 4.0
        reasons.append("penalty stale")
    if row["status"] == "draft":
        penalty -= 2.0
        reasons.append("penalty draft")
    if row["trust"] == "machine-confirmed":
        penalty -= 1.0
        reasons.append("penalty machine-confirmed")
    if row["status"] == "deprecated":
        penalty -= 6.0
        reasons.append("penalty deprecated")
    return penalty, reasons


def _card(
    row: sqlite3.Row,
    *,
    score: float,
    reasons: list[str],
    excerpt: str = "",
    section: str = "",
    graph_distance: int = 0,
    sources: tuple[str, ...] = (),
    source_paths: tuple[str, ...] = (),
    supersession_refs: tuple[str, ...] = (),
    contradiction_refs: tuple[str, ...] = (),
    unresolved_questions: str = "",
    freshness_override: str | None = None,
    extra_warnings: tuple[str, ...] = (),
) -> ResultCard:
    warnings: list[str] = []
    freshness = freshness_override or str(row["freshness"])
    trust = str(row["trust"])
    if freshness != "fresh":
        warnings.append(f"freshness: {freshness}")
    if trust == "unverified":
        warnings.append("trust: unverified")
    if contradiction_refs:
        warnings.append(f"contradiction: {', '.join(contradiction_refs)}")
    warnings.extend(extra_warnings)
    return ResultCard(
        relative_file=row["relative_file"], resource=row["resource"] or row["relative_file"],
        title=row["title"] or row["relative_file"], type=row["type"], status=row["status"],
        trust=trust, freshness=freshness,
        authority_label="authoritative" if trust == "human-reviewed" and freshness == "fresh" and row["status"] == "stable" else trust,
        score=round(score, 6), reasons=tuple(dict.fromkeys(reasons)), excerpt=excerpt,
        section=section, warnings=tuple(warnings), graph_distance=graph_distance,
        components=_json_tuple(row["components"]), sources=sources,
        source_paths=source_paths, source_revision=row["source_revision"],
        supersession_refs=supersession_refs,
        contradiction_refs=contradiction_refs,
        unresolved_questions=unresolved_questions,
    )


def _compact_lines(text: str, *, limit: int = 600) -> str:
    selected: list[str] = []
    used = 0
    for line in text.strip().splitlines():
        added = len(line) + (1 if selected else 0)
        if selected and used + added > limit:
            break
        if not selected and len(line) > limit:
            return line[:limit].rstrip()
        selected.append(line)
        used += added
    return "\n".join(selected).strip()


def _body_sections(body: str) -> tuple[tuple[str, str], ...]:
    lines = body.splitlines()
    starts = [index for index, line in enumerate(lines) if re.match(r"^#{1,6}\s+", line)]
    if not starts:
        return (("", body.strip()),) if body.strip() else ()
    sections: list[tuple[str, str]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        title = lines[start].lstrip("#").strip().rstrip("#").strip()
        sections.append((title, "\n".join(lines[start:end]).strip()))
    return tuple(sections)


def _selected_content(body: str, tokens: tuple[str, ...]) -> tuple[str, str, str]:
    sections = _body_sections(body)
    if not sections:
        return "", "", ""
    selected = max(
        enumerate(sections),
        key=lambda item: (
            sum(item[1][1].casefold().count(token) for token in tokens),
            -item[0],
        ),
    )[1]
    unresolved = next(
        (
            _compact_lines(text)
            for title, text in sections
            if title.casefold() in {"unresolved questions", "open questions"}
        ),
        "",
    )
    return selected[0], _compact_lines(selected[1]), unresolved


def _resource_refs(
    connection: sqlite3.Connection,
    relative_file: str,
    resource_by_file: dict[str, str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    supersession_paths = {
        other
        for source, target in connection.execute(
            "SELECT source, target FROM supersession WHERE source = ? OR target = ?",
            (relative_file, relative_file),
        )
        for other in (target if source == relative_file else source,)
    }
    contradiction_paths = {
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT other.relative_file FROM claims current "
            "JOIN claims other ON current.claim_id = other.claim_id "
            "AND current.normalized_value <> other.normalized_value "
            "WHERE current.relative_file = ? AND other.relative_file <> ?",
            (relative_file, relative_file),
        )
    }
    return (
        tuple(sorted(resource_by_file.get(path, path) for path in supersession_paths)),
        tuple(sorted(resource_by_file.get(path, path) for path in contradiction_paths)),
    )


def _fts_tokens(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(token.casefold() for token in _TOKEN_RE.findall(query)))


def _fts_query(tokens: tuple[str, ...]) -> str:
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _exact_field_match(value: str, token: str) -> bool:
    return token in _fts_tokens(value)


def _body_exact_terms(query: str) -> tuple[tuple[str, str], ...]:
    terms: list[tuple[str, str]] = []
    classified: set[str] = set()
    for label, pattern in (("flag", _FLAG_RE), ("ticket", _TICKET_RE)):
        for match in pattern.finditer(query):
            value = match.group(0).casefold()
            terms.append((label, value))
            classified.add(value)
    for token in _TOKEN_RE.findall(query):
        value = token.casefold()
        if value in classified:
            continue
        if "/" in token or re.search(r"\.[A-Za-z0-9]{1,8}$", token):
            terms.append(("path", value))
        elif "_" in token or token.endswith("()"):
            label = "error" if token.upper() == token and "_" in token else "symbol"
            terms.append((label, value.removesuffix("()")))
    return tuple(terms)


def _bm25_scores(connection: sqlite3.Connection, tokens: tuple[str, ...]) -> dict[str, float]:
    if not tokens:
        return {}
    rows = connection.execute(
        "SELECT relative_file, bm25(concepts_fts) AS rank "
        "FROM concepts_fts WHERE concepts_fts MATCH ?",
        (_fts_query(tokens),),
    ).fetchall()
    relevance = {row["relative_file"]: max(0.0, -float(row["rank"])) for row in rows}
    maximum = max(relevance.values(), default=0.0)
    if maximum == 0:
        return {relative_file: 0.0 for relative_file in relevance}
    return {relative_file: value / maximum for relative_file, value in relevance.items()}


def _resolve_rows(connection: sqlite3.Connection, concept: str) -> list[sqlite3.Row]:
    rows = connection.execute("SELECT * FROM concepts ORDER BY relative_file").fetchall()
    exact = [row for row in rows if concept == row["relative_file"] or concept == row["resource"]]
    if exact:
        return exact
    name = concept.casefold()
    matches = [row for row in rows if name in (row["relative_file"] or "").casefold() or name in (row["title"] or "").casefold()]
    if len(matches) > 1:
        raise ValueError(f"ambiguous concept: {concept}")
    if not matches:
        raise ValueError(f"concept not found: {concept}")
    return matches


def search(root: Path, query: str, *, project: str | None = None, types: list[str] | None = None,
           components: list[str] | None = None, status: str | None = None,
           freshness: str | None = None, include_draft: bool = False,
           include_deprecated: bool = False, limit: int = 10) -> list[ResultCard]:
    connection = _db(root)
    history_intent = bool(re.search(r"\b(history|deprecated|supersed(?:ed|es))\b", query, re.IGNORECASE))
    include_deprecated = include_deprecated or history_intent
    try:
        all_rows = connection.execute("SELECT * FROM concepts").fetchall()
        resource_by_file = {
            row["relative_file"]: row["resource"] or row["relative_file"]
            for row in all_rows
        }
        try:
            overlays = freshness_overlays(root)
        except ValueError:
            overlays = {}
        rows = [
            row
            for row in all_rows
            if _allowed(
                row,
                project=project,
                types=types,
                components=components,
                status=status,
                freshness=freshness,
                include_draft=include_draft,
                include_deprecated=include_deprecated,
                history_intent=history_intent,
                freshness_override=(
                    overlays.get(resource_by_file[row["relative_file"]]).state
                    if resource_by_file[row["relative_file"]] in overlays
                    else None
                ),
            )
        ]
        tokens = _fts_tokens(query)
        lexical_scores = _bm25_scores(connection, tokens)
        body_exact_terms = _body_exact_terms(query)
        indexed_sources: dict[str, dict[str, list[str]]] = {}
        for source_row in connection.execute(
            "SELECT relative_file, source_kind, source_value FROM sources "
            "ORDER BY relative_file, source_kind, source_value"
        ):
            by_kind = indexed_sources.setdefault(source_row["relative_file"], {})
            by_kind.setdefault(source_row["source_kind"], []).append(source_row["source_value"])
        scored: dict[str, tuple[float, list[str], int]] = {}
        for row in rows:
            body = connection.execute("SELECT text FROM concepts_fts WHERE relative_file = ?", (row["relative_file"],)).fetchone()[0]
            body_fold = body.casefold()
            score = 0.0
            reasons: list[str] = []
            source_fields = indexed_sources.get(row["relative_file"], {})
            fields = (("path", row["relative_file"]), ("source", " ".join(source_fields.get("source", []))), ("source_path", " ".join(source_fields.get("source_path", []))), ("title", row["title"] or ""), ("resource", row["resource"] or ""), ("tag", " ".join(_json_tuple(row["tags"]))), ("component", " ".join(_json_tuple(row["components"]))), ("symptom", " ".join(_json_tuple(row["symptoms"]))), ("project", row["project"] or ""))
            for token in tokens:
                for label, value in fields:
                    if _exact_field_match(str(value), token):
                        score += {"title": 9, "resource": 8, "tag": 8, "component": 8, "symptom": 8, "project": 7, "path": 9, "source": 9, "source_path": 9, "ticket": 10, "flag": 10, "symbol": 10, "error": 10}.get(label, 4)
                        reasons.append(f"exact {label}")
            for label, term in body_exact_terms:
                if term in body_fold:
                    score += {"ticket": 10, "flag": 10, "symbol": 10, "error": 10, "path": 9}[label]
                    reasons.append(f"exact {label}")
            lexical_score = lexical_scores.get(row["relative_file"], 0.0)
            if lexical_score:
                score += lexical_score
                reasons.append("BM25 lexical text")
            if score:
                scored[row["relative_file"]] = (score, reasons, 0)
        strong = [key for key, value in scored.items() if value[0] >= 8]
        neighbors: dict[str, int] = {}
        for source in strong:
            for row in connection.execute("SELECT target FROM links WHERE source = ? UNION SELECT source FROM reverse_links WHERE target = ? ORDER BY target", (source, source)):
                neighbors[row[0]] = 1
        by_file = {row["relative_file"]: row for row in rows}
        for filename, distance in neighbors.items():
            if filename in by_file and filename not in scored:
                scored[filename] = (2.0, ["one-hop graph expansion"], distance)
        for filename, (score, reasons, distance) in tuple(scored.items()):
            resource = resource_by_file[filename]
            overlay = overlays.get(resource)
            penalty, penalty_reasons = _ranking_penalty(
                by_file[filename], overlay.state if overlay else None
            )
            scored[filename] = (score + penalty, [*reasons, *penalty_reasons], distance)
        cards: list[ResultCard] = []
        for filename, value in scored.items():
            row = by_file[filename]
            overlay = overlays.get(resource_by_file[filename])
            source_fields = indexed_sources.get(filename, {})
            section, excerpt, unresolved = _selected_content(row["body"], tokens)
            supersession_refs, contradiction_refs = _resource_refs(
                connection, filename, resource_by_file
            )
            cards.append(
                _card(
                    row,
                    score=value[0],
                    reasons=value[1],
                    graph_distance=value[2],
                    section=section,
                    excerpt=excerpt,
                    sources=tuple(source_fields.get("source", [])),
                    source_paths=tuple(source_fields.get("source_path", [])),
                    supersession_refs=supersession_refs,
                    contradiction_refs=contradiction_refs,
                    unresolved_questions=unresolved,
                    freshness_override=overlay.state if overlay else None,
                    extra_warnings=overlay.warnings if overlay else (),
                )
            )
        return sorted(cards, key=lambda card: (-card.score, card.resource, card.relative_file))[:limit]
    finally:
        connection.close()


def _extract_section(body: str, heading: str) -> str:
    lines = body.splitlines()
    wanted = heading.strip().lstrip("#").strip().casefold()
    start = next((i for i, line in enumerate(lines) if line.startswith("#") and line.lstrip("#").strip().rstrip("#").strip().casefold() == wanted), None)
    if start is None:
        raise ValueError(f"section not found: {heading}")
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#") and len(lines[i]) - len(lines[i].lstrip("#")) <= level), len(lines))
    return "\n".join(lines[start:end]).strip()


def show(root: Path, concept: str, *, section: str | None = None) -> ResultCard:
    connection = _db(root)
    try:
        row = _resolve_rows(connection, concept)[0]
        root_path = root.resolve()
        relative_file = Path(row["relative_file"])
        candidate = (root_path / relative_file).resolve()
        if (
            relative_file.is_absolute()
            or ".." in relative_file.parts
            or not candidate.is_relative_to(root_path)
            or not candidate.is_file()
        ):
            raise RetrievalValidationError(
                "show.path_outside_kb",
                "$.concept",
                "indexed concept path is outside the knowledge root; rebuild the index",
            )
        body = candidate.read_text(encoding="utf-8")
        body = body.split("---", 2)[-1].lstrip("\r\n")
        selected = _extract_section(body, section) if section else body.strip()
        return _card(row, score=0, reasons=["resolved concept"], excerpt=selected, section=section or "")
    finally:
        connection.close()


def related(root: Path, concept: str, *, limit: int = 10) -> list[ResultCard]:
    connection = _db(root)
    try:
        source = _resolve_rows(connection, concept)[0]["relative_file"]
        rows = connection.execute("SELECT * FROM concepts WHERE relative_file IN (SELECT target FROM links WHERE source = ? UNION SELECT source FROM reverse_links WHERE target = ?) ORDER BY relative_file LIMIT ?", (source, source, limit)).fetchall()
        return [_card(row, score=1, reasons=["one-hop graph neighbor"]) for row in rows]
    finally:
        connection.close()


def context(
    root: Path,
    query: str,
    *,
    budget: int,
    project: str | None = None,
    components: list[str] | None = None,
) -> ContextResult:
    cards = search(root, query, project=project, components=components, limit=100)
    warnings = tuple(sorted({warning for card in cards for warning in card.warnings}))

    def package(selected: Iterable[ResultCard]) -> ContextResult:
        selected_cards = tuple(selected)
        estimated = 0
        while True:
            result = ContextResult(
                query, budget, estimated, "utf8-bytes-div-2-ceil", True,
                warnings, selected_cards,
            )
            measured = estimate_units(_canonical_json(result.as_dict()))
            if measured == estimated:
                return result
            estimated = measured

    base = package(())
    if base.estimated_units > budget:
        raise RetrievalValidationError(
            "context.budget_too_small",
            "$.budget",
            "context budget too small: mandatory base package and warnings "
            f"require {base.estimated_units} units, requested {budget}",
        )
    selected: list[ResultCard] = []
    for card in cards:
        candidate = [*selected, card]
        candidate_result = package(candidate)
        if candidate_result.estimated_units > budget:
            break
        selected = candidate
    return package(selected)


def status(root: Path) -> dict[str, Any]:
    state = state_directory(root)
    database = state / "index.sqlite3"
    manifest = state / "manifest.json"
    missing = [name for name, path in (("database", database), ("manifest", manifest)) if not path.is_file()]
    concepts = 0
    corrupt: list[str] = []
    if database.is_file():
        connection: sqlite3.Connection | None = None
        try:
            connection = _db(root)
            concepts = connection.execute("SELECT count(*) FROM concepts").fetchone()[0]
        except (RetrievalValidationError, sqlite3.DatabaseError):
            corrupt.append("database")
        finally:
            if connection is not None:
                connection.close()
    if manifest.is_file():
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            if not valid_manifest(value):
                corrupt.append("manifest")
        except (OSError, json.JSONDecodeError):
            corrupt.append("manifest")
    return {"schema_version": SCHEMA_VERSION, "bundle": {"concepts": concepts}, "state": {"missing": missing, "corrupt": sorted(set(corrupt))}}
