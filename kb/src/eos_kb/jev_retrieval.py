"""Jev-enhanced retrieval: query expansion, semantic re-ranking, routing, adaptive budget.

Each stage falls back to standard BM25 behavior when Jev is unavailable.
Routing narrows via component filters (with unfiltered fallback), never via
project, because routed sections are not KB project names. Adaptive budget
only applies when the caller opts in; explicit user budgets are never overridden.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jev import JevError, evaluate, is_available
from .retrieval import (
    ResultCard,
    RetrievalValidationError,
    package_context,
    search as base_search,
)


@dataclass(frozen=True)
class JevContextResult:
    cards: tuple[ResultCard, ...]
    estimated_units: int
    jev_used: bool
    warnings: tuple[str, ...] = ()
    expanded_query: str | None = None
    routed_section: str | None = None
    adaptive_budget: int | None = None
    jev_tokens_used: int = 0


@dataclass(frozen=True)
class JevPlan:
    """Single-call plan: routing, expansion, and complexity in one evaluate()."""

    section: str | None
    expanded_query: str | None
    complexity: int | None
    tokens: int


_TERM_CLUSTERS: dict[str, tuple[str, ...]] = {
    "auth": ("oauth", "jwt", "login", "authentication", "credentials", "token", "session", "sso", "saml", "permission", "role", "rbac"),
    "database": ("sql", "query", "schema", "migration", "index", "postgres", "sqlite", "clickhouse", "table", "join"),
    "api": ("rest", "endpoint", "http", "request", "response", "grpc", "graphql", "webhook", "rate-limit", "pagination"),
    "infra": ("docker", "kubernetes", "deploy", "ci-cd", "pipeline", "terraform", "aws", "gcp", "monitoring", "logging"),
    "frontend": ("react", "component", "css", "layout", "responsive", "state", "render", "dom", "browser", "ui"),
    "agents": ("llm", "prompt", "tool-call", "mcp", "context", "claude", "codex", "gemini", "opencode", "skill"),
    "testing": ("pytest", "unit-test", "integration", "e2e", "mock", "fixture", "assert", "coverage", "tdd"),
    "knowledge": ("kb", "concept", "frontmatter", "index", "search", "retrieval", "summary", "governance", "proposal"),
    "messaging": ("kafka", "queue", "pubsub", "event", "stream", "consumer", "producer", "topic", "partition"),
    "security": ("encryption", "hash", "vulnerability", "xss", "csrf", "injection", "sanitize", "firewall", "ssl", "tls"),
}

_KB_SECTIONS: dict[str, dict[str, Any]] = {
    "backend": {"types": ["Pattern", "Decision", "Note"], "components": ["backend"]},
    "frontend": {"types": ["Pattern", "Decision", "Note"], "components": ["frontend"]},
    "infra": {"types": ["Pattern", "Decision", "Runbook", "Note"], "components": ["infra"]},
    "agents": {"types": ["Pattern", "Decision", "Note", "Research Notebook"], "components": ["agents"]},
    "knowledge": {"types": ["Pattern", "Decision", "Note", "Index"], "components": ["knowledge"]},
    "general": {},
}

_COMPLEXITY_BUDGET_MAP = {
    1: 500,
    2: 1500,
    3: 3000,
    4: 5000,
    5: 8000,
}

_MAX_EXPANSION_TERMS = 8
_MAX_EXPANSION_CLUSTERS = 2
_MAX_TERMS_PER_CLUSTER = 4


def route_components_for(section: str | None) -> list[str] | None:
    """Map a routed KB section to component filter values, or None when unmapped."""
    if not section or section not in _KB_SECTIONS:
        return None
    components = _KB_SECTIONS[section].get("components")
    return list(components) if components else None


def _route_question(query: str) -> dict[str, Any]:
    criteria = {
        name: f"Knowledge about {name} systems and patterns"
        for name in _KB_SECTIONS
    }
    return {
        "type": "choice",
        "instructions": (
            f"Which section of the engineering knowledge base is most relevant "
            f"to this search query? Query: \"{query}\""
        ),
        "criteria": criteria,
    }


def _complexity_question(query: str) -> dict[str, Any]:
    return {
        "type": "score",
        "instructions": (
            f"How much context does this search query need to answer well?\n"
            f"Query: \"{query}\"\n"
            f"Rate using the criteria from simplest (first) to deepest (last). "
            f"Simple factual lookup = first criterion, "
            f"moderate exploration = middle, complex architecture question = last."
        ),
        "criteria": [
            "Simple factual lookup, one concept needed",
            "Straightforward question, few concepts needed",
            "Moderate exploration, several concepts needed",
            "Complex question, many concepts needed",
            "Deep architecture or design question, broad context needed",
        ],
    }


def _cluster_questions(query: str) -> dict[str, dict[str, Any]]:
    return {
        f"cluster_{cluster_name}": {
            "type": "noul",
            "instructions": (
                f"Is this search query related to {cluster_name} concepts? "
                f"Query: \"{query}\""
            ),
        }
        for cluster_name in _TERM_CLUSTERS
    }


def _parse_route(answer: Any) -> str | None:
    if (
        answer
        and answer.type == "choice"
        and answer.choice
        and answer.confidence
        and answer.confidence > 0.5
        and answer.choice in _KB_SECTIONS
    ):
        return answer.choice
    return None


def _parse_expansion(query: str, answers: dict[str, Any]) -> str | None:
    matched: list[tuple[float, str]] = []
    for qid, answer in answers.items():
        if not qid.startswith("cluster_"):
            continue
        if answer.type == "noul" and answer.noul is not None and answer.noul > 0.6:
            matched.append((answer.noul, qid.removeprefix("cluster_")))
    matched.sort(reverse=True)
    existing = {term.lower() for term in query.split()}
    extra: list[str] = []
    for _, cluster_name in matched[:_MAX_EXPANSION_CLUSTERS]:
        for term in _TERM_CLUSTERS.get(cluster_name, ())[: _MAX_TERMS_PER_CLUSTER]:
            if term.lower() not in existing and term not in extra:
                extra.append(term)
            if len(extra) >= _MAX_EXPANSION_TERMS:
                break
        if len(extra) >= _MAX_EXPANSION_TERMS:
            break
    if not extra:
        return None
    return f"{query} {' '.join(extra[:_MAX_EXPANSION_TERMS])}"


def _parse_complexity(answer: Any) -> int | None:
    """Score answers use a 0-indexed criteria scale; map to 1-5 budget levels."""
    if answer is None or answer.score is None:
        return None
    return max(1, min(5, round(answer.score) + 1))


def plan_query(query: str, *, profile: str = "personal") -> JevPlan | None:
    """Run routing, expansion, and complexity in one Jev evaluate() call.

    Returns None when Jev is unavailable or the call fails. Callers fall back
    to unfiltered BM25 behavior.
    """
    if not is_available(profile):
        return None
    questions = {
        "kb_section": _route_question(query),
        "complexity": _complexity_question(query),
        **_cluster_questions(query),
    }
    try:
        response = evaluate(query, questions, profile=profile)
    except JevError:
        return None
    return JevPlan(
        section=_parse_route(response.answers.get("kb_section")),
        expanded_query=_parse_expansion(query, response.answers),
        complexity=_parse_complexity(response.answers.get("complexity")),
        tokens=response.input_tokens,
    )


def expand_query(query: str, *, profile: str = "personal") -> tuple[str, int]:
    """Expand query with related terms using Jev Noul questions.

    Returns (expanded_query, jev_tokens_used).
    Falls back to original query on failure. Expansion terms are capped.
    """
    if not is_available(profile):
        return query, 0
    try:
        response = evaluate(query, _cluster_questions(query), profile=profile)
    except JevError:
        return query, 0
    expanded = _parse_expansion(query, response.answers)
    return (expanded if expanded else query), response.input_tokens


def rerank_results(
    query: str,
    cards: list[ResultCard],
    *,
    profile: str = "personal",
    top_k: int = 20,
) -> tuple[list[ResultCard], int]:
    """Re-rank BM25 results using Jev Score for semantic relevance.

    Returns (reranked_cards, jev_tokens_used).
    Falls back to original order on failure.
    """
    if not is_available(profile) or not cards:
        return cards, 0
    try:
        candidates = cards[:top_k]
        questions = {}
        for index, card in enumerate(candidates):
            questions[f"relevance_{index}"] = {
                "type": "score",
                "instructions": (
                    f"How relevant is this knowledge base document to the search query?\n"
                    f"Query: \"{query}\"\n"
                    f"Document title: {card.title}\n"
                    f"Document type: {card.type}\n"
                    f"Document excerpt: {card.excerpt[:300]}"
                ),
                "criteria": [
                    "Completely irrelevant",
                    "Slightly related",
                    "Moderately relevant",
                    "Highly relevant",
                    "Exactly what the query needs",
                ],
            }
        state = f"Query: {query}\nDocuments to evaluate: {len(candidates)}"
        response = evaluate(state, questions, profile=profile)
        scored: list[tuple[float, int, ResultCard]] = []
        for index, card in enumerate(candidates):
            answer = response.answers.get(f"relevance_{index}")
            jev_score = answer.score if answer and answer.score is not None else 0.0
            scored.append((jev_score, index, card))
        scored.sort(key=lambda item: (-item[0], item[1]))
        reranked = [card for _, _, card in scored]
        remaining = [card for card in cards if card not in candidates]
        return reranked + remaining, response.input_tokens
    except JevError:
        return cards, 0


def route_query(query: str, *, profile: str = "personal") -> tuple[str | None, int]:
    """Route query to the most relevant KB section using Jev Choice.

    Returns (section_name_or_None, jev_tokens_used).
    Returns None when routing is unavailable or uncertain.
    """
    if not is_available(profile):
        return None, 0
    try:
        response = evaluate(query, {"kb_section": _route_question(query)}, profile=profile)
    except JevError:
        return None, 0
    return _parse_route(response.answers.get("kb_section")), response.input_tokens


def adaptive_budget(
    query: str, *, profile: str = "personal", default_budget: int = 2000
) -> tuple[int, int]:
    """Determine context budget based on query complexity using Jev Score.

    Returns (budget, jev_tokens_used).
    Falls back to default_budget on failure. Callers must only use this when
    default_budget is a default, never to override an explicit user budget.
    """
    if not is_available(profile):
        return default_budget, 0
    try:
        response = evaluate(
            query, {"complexity": _complexity_question(query)}, profile=profile
        )
    except JevError:
        return default_budget, 0
    level = _parse_complexity(response.answers.get("complexity"))
    if level is None:
        return default_budget, response.input_tokens
    return _COMPLEXITY_BUDGET_MAP.get(level, default_budget), response.input_tokens


def jev_context(
    root: Path,
    query: str,
    *,
    budget: int = 2000,
    profile: str = "personal",
    project: str | None = None,
    related_projects: tuple[str, ...] = (),
    components: list[str] | None = None,
    use_expansion: bool = True,
    use_reranking: bool = True,
    use_routing: bool = True,
    use_adaptive_budget: bool = False,
) -> JevContextResult:
    """Full Jev-enhanced context retrieval pipeline.

    Pipeline: one plan call (route + expand + complexity) -> BM25 search ->
    rerank -> package. Max two Jev API calls. Each stage falls back gracefully
    when Jev is unavailable.

    Adaptive budget is opt-in and must only be enabled when `budget` is a
    default; explicit user budgets are never overridden.
    """
    total_tokens = 0
    routed_section: str | None = None
    route_components: list[str] | None = None
    effective_query = query
    expanded_query: str | None = None
    effective_budget = budget
    chosen_adaptive_budget: int | None = None

    wants_plan = use_routing or use_expansion or use_adaptive_budget
    plan = plan_query(query, profile=profile) if wants_plan else None
    if plan is not None:
        total_tokens += plan.tokens
        if use_routing and not project and not components and plan.section and plan.section != "general":
            candidate_components = route_components_for(plan.section)
            if candidate_components:
                routed_section = plan.section
                route_components = candidate_components
        if use_expansion and plan.expanded_query:
            effective_query = plan.expanded_query
            expanded_query = plan.expanded_query
        if use_adaptive_budget and plan.complexity is not None:
            adaptive = _COMPLEXITY_BUDGET_MAP.get(plan.complexity, budget)
            if adaptive != budget:
                chosen_adaptive_budget = adaptive
                effective_budget = adaptive

    search_components = components if components is not None else route_components
    cards = base_search(
        root, effective_query, project=project, related_projects=related_projects,
        components=search_components, limit=100,
    )
    if route_components and not cards and components is None:
        cards = base_search(
            root, effective_query, project=project, related_projects=related_projects, limit=100
        )
        if cards:
            routed_section = None
            route_components = None

    if use_reranking:
        cards, tokens = rerank_results(query, cards, profile=profile)
        total_tokens += tokens

    warnings = tuple(sorted({warning for card in cards for warning in card.warnings}))
    base = package_context(query, effective_budget, warnings, ())
    if base.estimated_units > effective_budget:
        raise RetrievalValidationError(
            "context.budget_too_small",
            "$.budget",
            "context budget too small: mandatory base package and warnings "
            f"require {base.estimated_units} units, requested {effective_budget}",
        )
    selected: list[ResultCard] = []
    for card in cards:
        if package_context(query, effective_budget, warnings, [*selected, card]).estimated_units > effective_budget:
            break
        selected.append(card)
    packed = package_context(query, effective_budget, warnings, selected)

    return JevContextResult(
        cards=packed.cards,
        estimated_units=packed.estimated_units,
        jev_used=total_tokens > 0,
        warnings=packed.warnings,
        expanded_query=expanded_query,
        routed_section=routed_section,
        adaptive_budget=chosen_adaptive_budget,
        jev_tokens_used=total_tokens,
    )
