from __future__ import annotations

import json
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from eos_kb.freshness import audit_freshness
from eos_kb.indexer import index_bundle
from eos_kb.retrieval import context, search


FIXTURE = Path(__file__).parent / "fixtures/benchmark/queries.yaml"


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _write(
    root: Path,
    relative: str,
    *,
    title: str,
    body: str,
    resource: str,
    tags: list[str] | None = None,
    status: str = "stable",
    eos: dict[str, object] | None = None,
) -> None:
    metadata: dict[str, object] = {
        "type": "Decision",
        "title": title,
        "resource": resource,
        "status": status,
        "tags": tags or [],
    }
    if eos:
        metadata["eos"] = eos
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        *[f"{key}: {json.dumps(value)}" for key, value in metadata.items()],
        "---",
        body,
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bundle(tmp_path: Path) -> tuple[Path, list[dict[str, object]]]:
    root = tmp_path / "knowledge"
    source_root = tmp_path / "source"
    root.mkdir()
    source_root.mkdir()
    _git(source_root, "init", "-q")
    _git(source_root, "config", "user.email", "benchmark@example.com")
    _git(source_root, "config", "user.name", "EOS Benchmark")
    stale_source = source_root / "src/resolver.py"
    stale_source.parent.mkdir(parents=True, exist_ok=True)
    stale_source.write_text("RETURN_GRAIN = 'item'\n", encoding="utf-8")
    _git(source_root, "add", ".")
    _git(source_root, "commit", "-qm", "baseline")
    revision = _git(source_root, "rev-parse", "HEAD")

    queries = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))["queries"]
    documents = [
        ("concept-01.md", "Booking Entity Contract", "Booking resolution uses the shipment item grain.", ["booking", "resolver"], {}),
        ("concept-02.md", "Booking Family Runbook", "The family route is owned by the booking domain.", ["family", "route"], {}),
        ("concept-03.md", "Master Entity Gate", "Validation rejects a master record until its gate passes.", ["master", "gate"], {}),
        ("concept-04.md", "SKU Grain Contract", "The SKU check compares item-level grain with catalog scope.", ["sku", "grain"], {}),
        ("concept-05.md", "Workspace Project Routing", "The editor resolves the project from the active workspace.", ["project", "editor"], {}),
        ("concept-06.md", "Identity Lifecycle", "Identity creation, rotation, and retirement share one lifecycle.", ["identity", "lifecycle"], {}),
        ("concept-07.md", "Execution Ownership", "The execution owner boundary is declared by the service contract.", ["execution", "ownership"], {}),
        ("concept-08.md", "Database Socket Access", "The local database socket requires the configured permission boundary.", ["database", "socket"], {}),
        ("concept-09.md", "Notebook Kernel Session", "Notebook cells share the kernel session until it is reset.", ["notebook", "kernel"], {}),
        ("concept-10.md", "Agent Profile Routing", "Agent launchers select a profile before opening the project.", ["agent", "profile"], {}),
        ("concept-11.md", "MCP Work Profile", "Work profile MCP servers are copied from the shared configuration.", ["MCP", "work"], {}),
        ("concept-12.md", "Pending Knowledge Review", "Pending proposals remain queued until an explicit review.", ["pending", "knowledge"], {}),
        ("concept-13.md", "Resolver Architecture Contract", "The resolver architecture contract is tied to the implementation source.", ["architecture", "resolver"], {"source_paths": ["src/resolver.py"], "source_revision": revision}),
    ]
    for relative, title, body, tags, eos in documents:
        number = relative[8:10]
        _write(root, relative, title=title, body=body, resource=f"kb:bench/alpha-{number}", tags=tags, eos=eos)
    _write(
        root,
        "concept-14.md",
        title="Scheduler Dispatch Contract",
        body="The scheduler dispatch contract uses the async mode as its default.",
        resource="kb:bench/alpha-14",
        tags=["scheduler", "dispatch"],
        eos={"project": "nova", "claims": [{"id": "scheduler.mode", "value": "async"}]},
    )
    _write(
        root,
        "concept-14-conflict.md",
        title="Scheduler Legacy Note",
        body="The legacy scheduler dispatch used a synchronous mode.",
        resource="kb:bench/alpha-14-conflict",
        tags=["legacy"],
        eos={"project": "nova", "claims": [{"id": "scheduler.mode", "value": "sync"}]},
    )
    _write(
        root,
        "archive/concept-15.md",
        title="Retired Allocator Policy",
        body="The retired allocator policy describes the previous resource selection rules.",
        resource="kb:bench/alpha-15",
        tags=["allocator", "retired"],
        status="deprecated",
    )

    index_bundle(root, source_root=source_root)
    stale_source.write_text("RETURN_GRAIN = 'order'\n", encoding="utf-8")
    audit_freshness(root, source_root, now=datetime(2026, 7, 29, tzinfo=timezone.utc))
    return root, queries


def test_retrieval_benchmark_has_independent_targets_and_meets_budget_thresholds(tmp_path: Path) -> None:
    root, queries = _bundle(tmp_path)
    hits = 0
    top_five_hits = 0
    units: list[int] = []
    latencies: list[float] = []
    precisions: list[float] = []
    bodies = "\n".join(
        path.read_text(encoding="utf-8").split("---", 2)[-1].casefold()
        for path in root.rglob("*.md")
        if path.name not in {"index.md", "00-index.md"}
    )
    for item in queries:
        query = str(item["query"])
        started = time.monotonic()
        cards = search(root, query, limit=5)
        latencies.append(time.monotonic() - started)
        assert query.casefold() not in bodies
        resources = [card.resource for card in cards]
        expected = str(item["expected"])
        found = expected in resources
        hits += int(found)
        top_five_hits += int(found and resources.index(expected) < 5)
        precisions.append((1.0 if found else 0.0) / max(1, len(cards)))
        package = context(root, query, budget=2500)
        units.append(package.estimated_units)
        assert package.estimated_units <= 2500

    report = {
        "recall_at_5": top_five_hits / len(queries),
        "precision_at_5": statistics.mean(precisions),
        "median_units": statistics.median(units),
        "max_latency_seconds": max(latencies),
    }
    print(json.dumps(report, sort_keys=True))
    assert hits == len(queries)
    assert top_five_hits == len(queries)
    assert report["recall_at_5"] >= 0.90
    assert report["median_units"] <= 1500
    assert report["max_latency_seconds"] < 2.0


def test_warning_recall_is_independent_and_reserved_before_context_cards(tmp_path: Path) -> None:
    root, queries = _bundle(tmp_path)
    warning_cases = [item for item in queries if item.get("warning_fragments")]
    assert {item["scenario"] for item in warning_cases} == {"stale", "contradiction", "history-only"}
    for item in warning_cases:
        query = str(item["query"])
        target = next(card for card in search(root, query, limit=5) if card.resource == item["expected"])
        package = context(root, query, budget=2500)
        warnings = set(target.warnings) | set(package.warnings)
        assert set(item["warning_fragments"]) <= warnings
        assert package.warnings_reserved is True


def test_conceptual_result_reserves_unverified_warning(tmp_path: Path) -> None:
    root, _ = _bundle(tmp_path)
    _write(
        root,
        "conceptual.md",
        title="Inference Boundary Note",
        body="This note explains the inference boundary and its intended interpretation.",
        resource="kb:bench/conceptual",
        tags=["inference", "boundary"],
    )
    index_bundle(root)
    target = search(root, "meaning of inference boundary", limit=5)[0]
    assert target.resource == "kb:bench/conceptual"
    assert "trust: unverified" in target.warnings
    package = context(root, "meaning of inference boundary", budget=2500)
    assert "trust: unverified" in package.warnings
