from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eos_kb.cli import ExitCode, main
from eos_kb.jev import JevError, _api_key, derive_jev_profile, evaluate, is_available
from eos_kb.jev_retrieval import (
    adaptive_budget,
    expand_query,
    jev_context,
    plan_query,
    rerank_results,
    route_components_for,
    route_query,
)


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    root = tmp_path / "knowledge"
    root.mkdir()
    return root


def _mock_jev_response(answers: dict, input_tokens: int = 100) -> dict:
    return {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": input_tokens, "output_tokens": 20},
    }


class TestApiKey:
    def test_work_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_WORK", "work-key")
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "personal-key")
        assert _api_key("work") == "work-key"

    def test_personal_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_WORK", "work-key")
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "personal-key")
        assert _api_key("personal") == "personal-key"

    def test_fallback_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TYPESAFE_API_KEY_WORK", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.setenv("TYPESAFE_API_KEY", "fallback-key")
        assert _api_key("personal") == "fallback-key"

    def test_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TYPESAFE_API_KEY_WORK", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        assert _api_key("personal") is None

    def test_is_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "key")
        assert is_available("personal") is True
        assert is_available("work") is False


class TestEvaluate:
    def test_no_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TYPESAFE_API_KEY_WORK", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        with pytest.raises(JevError, match="no_api_key"):
            evaluate("test", {"q": {"type": "noul", "instructions": "test"}})

    @patch("eos_kb.jev._post")
    def test_evaluate_noul(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            "is_urgent": {"type": "noul", "noul": 0.95}
        })
        result = evaluate("test state", {"is_urgent": {"type": "noul", "instructions": "test"}}, profile="personal")
        assert result.answers["is_urgent"].noul == 0.95
        assert result.input_tokens == 100

    @patch("eos_kb.jev._post")
    def test_evaluate_choice(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            "section": {
                "type": "choice",
                "choice": "backend",
                "probabilities": {"backend": 0.9, "frontend": 0.1},
                "confidence": 0.85,
            }
        })
        result = evaluate("test", {"section": {"type": "choice", "instructions": "test", "criteria": {}}}, profile="personal")
        assert result.answers["section"].choice == "backend"
        assert result.answers["section"].confidence == 0.85

    @patch("eos_kb.jev._post")
    def test_answers_not_dict_raises_bad_response(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = {"answers": "not-a-dict", "usage": {"input_tokens": 1, "output_tokens": 1}}
        with pytest.raises(JevError, match="jev.bad_response"):
            evaluate("test", {"q": {"type": "noul", "instructions": "test"}}, profile="personal")

    @patch("eos_kb.jev._post")
    def test_answer_not_dict_raises_bad_response(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = {"answers": {"q": "oops"}, "usage": {"input_tokens": 1, "output_tokens": 1}}
        with pytest.raises(JevError, match="jev.bad_response"):
            evaluate("test", {"q": {"type": "noul", "instructions": "test"}}, profile="personal")

    @patch("eos_kb.jev._post")
    def test_usage_not_dict_raises_bad_response(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = {"answers": {"q": {"type": "noul", "noul": 0.5}}, "usage": "bad"}
        with pytest.raises(JevError, match="jev.bad_response"):
            evaluate("test", {"q": {"type": "noul", "instructions": "test"}}, profile="personal")

    @patch("eos_kb.jev._post")
    def test_non_numeric_usage_raises_bad_response(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = {"answers": {}, "usage": {"input_tokens": "NaN", "output_tokens": None}}
        with pytest.raises(JevError, match="jev.bad_response"):
            evaluate("test", {"q": {"type": "noul", "instructions": "test"}}, profile="personal")

    @patch("eos_kb.jev.urllib.request.urlopen")
    def test_invalid_json_body_raises_bad_response(self, mock_urlopen: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"not-json{"
        mock_urlopen.return_value = response
        with pytest.raises(JevError, match="jev.bad_response"):
            evaluate("test", {"q": {"type": "noul", "instructions": "test"}}, profile="personal")

    @patch("eos_kb.jev._post")
    def test_malformed_response_falls_back_not_crashes(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = {"answers": None}
        expanded, tokens = expand_query("oauth setup", profile="personal")
        assert expanded == "oauth setup"
        assert tokens == 0

    @patch("eos_kb.jev._post")
    def test_string_numeric_fields_are_coerced(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            "complexity": {"type": "score", "score": "3.0", "legend": {}, "probabilities": {}, "confidence": "0.9"},
            "kb_section": {"type": "choice", "choice": "backend", "probabilities": {}, "confidence": "0.8"},
            **{f"cluster_{k}": {"type": "noul", "noul": "0.9" if k == "auth" else "0.1"} for k in ["auth", "database", "api", "infra", "frontend", "agents", "testing", "knowledge", "messaging", "security"]},
        })
        budget, tokens = adaptive_budget("complex query", profile="personal", default_budget=2000)
        assert budget == 5000
        assert tokens > 0

    @patch("eos_kb.jev._post")
    def test_non_numeric_field_raises_bad_response(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            "complexity": {"type": "score", "score": "not-a-number", "legend": {}, "probabilities": {}, "confidence": 0.9},
        })
        budget, tokens = adaptive_budget("q", profile="personal", default_budget=2000)
        assert budget == 2000
        assert tokens == 0

    def test_is_available_treats_empty_string_as_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "")
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        assert is_available("personal") is False


class TestExpandQuery:
    def test_no_jev_returns_original(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        expanded, tokens = expand_query("auth setup", profile="personal")
        assert expanded == "auth setup"
        assert tokens == 0

    @patch("eos_kb.jev._post")
    def test_expands_matching_clusters(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            "cluster_auth": {"type": "noul", "noul": 0.9},
            "cluster_database": {"type": "noul", "noul": 0.3},
            **{f"cluster_{k}": {"type": "noul", "noul": 0.1} for k in ["api", "infra", "frontend", "agents", "testing", "knowledge", "messaging", "security"]},
        })
        expanded, tokens = expand_query("oauth setup", profile="personal")
        assert "oauth" in expanded
        assert "jwt" in expanded
        assert tokens > 0

    @patch("eos_kb.jev._post")
    def test_no_match_returns_original(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            f"cluster_{k}": {"type": "noul", "noul": 0.1}
            for k in ["auth", "database", "api", "infra", "frontend", "agents", "testing", "knowledge", "messaging", "security"]
        })
        expanded, tokens = expand_query("xyzzy nothing", profile="personal")
        assert expanded == "xyzzy nothing"
        assert tokens > 0

    @patch("eos_kb.jev._post")
    def test_expansion_terms_are_capped(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            f"cluster_{k}": {"type": "noul", "noul": 0.95}
            for k in ["auth", "database", "api", "infra", "frontend", "agents", "testing", "knowledge", "messaging", "security"]
        })
        expanded, tokens = expand_query("setup wizard", profile="personal")
        extra_terms = expanded.split()[2:]
        assert len(extra_terms) <= 8
        assert tokens > 0


class TestRouteQuery:
    def test_no_jev_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        section, tokens = route_query("database migration", profile="personal")
        assert section is None
        assert tokens == 0

    @patch("eos_kb.jev._post")
    def test_routes_to_section(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            "kb_section": {
                "type": "choice",
                "choice": "backend",
                "probabilities": {"backend": 0.85, "frontend": 0.05, "infra": 0.05, "agents": 0.03, "knowledge": 0.01, "general": 0.01},
                "confidence": 0.78,
            }
        })
        section, tokens = route_query("database schema design", profile="personal")
        assert section == "backend"
        assert tokens > 0

    @patch("eos_kb.jev._post")
    def test_low_confidence_returns_none(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            "kb_section": {
                "type": "choice",
                "choice": "general",
                "probabilities": {"backend": 0.2, "frontend": 0.2, "infra": 0.2, "agents": 0.2, "knowledge": 0.1, "general": 0.1},
                "confidence": 0.3,
            }
        })
        section, tokens = route_query("vague question", profile="personal")
        assert section is None
        assert tokens > 0


class TestAdaptiveBudget:
    def test_no_jev_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        budget, tokens = adaptive_budget("simple query", profile="personal", default_budget=2000)
        assert budget == 2000
        assert tokens == 0

    @patch("eos_kb.jev._post")
    def test_simple_query_small_budget(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            "complexity": {
                "type": "score",
                "score": 0.2,
                "legend": {"0": "Simple", "1": "Easy", "2": "Moderate", "3": "Complex", "4": "Deep"},
                "probabilities": {"0": 0.8, "1": 0.15, "2": 0.05, "3": 0.0, "4": 0.0},
                "confidence": 0.9,
            }
        })
        budget, tokens = adaptive_budget("what is a variable", profile="personal", default_budget=2000)
        assert budget == 500
        assert tokens > 0

    @patch("eos_kb.jev._post")
    def test_complex_query_large_budget(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            "complexity": {
                "type": "score",
                "score": 4.0,
                "legend": {"0": "Simple", "1": "Easy", "2": "Moderate", "3": "Complex", "4": "Deep"},
                "probabilities": {"0": 0.0, "1": 0.0, "2": 0.05, "3": 0.15, "4": 0.8},
                "confidence": 0.92,
            }
        })
        budget, tokens = adaptive_budget("explain the entire auth architecture", profile="personal", default_budget=2000)
        assert budget == 8000
        assert tokens > 0


class TestRerankResults:
    def test_no_jev_returns_original(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        from eos_kb.retrieval import ResultCard
        card = ResultCard(
            relative_file="test.md", resource="kb:test", title="Test",
            type="Note", status="stable", trust="unverified", freshness="unknown",
            authority_label="unverified", score=1.0, reasons=(), excerpt="test",
        )
        reranked, tokens = rerank_results("test", [card], profile="personal")
        assert len(reranked) == 1
        assert tokens == 0

    @patch("eos_kb.jev._post")
    def test_reranks_by_jev_score(self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        from eos_kb.retrieval import ResultCard
        cards = [
            ResultCard(
                relative_file="low.md", resource="kb:low", title="Low relevance",
                type="Note", status="stable", trust="unverified", freshness="unknown",
                authority_label="unverified", score=1.0, reasons=(), excerpt="not relevant",
            ),
            ResultCard(
                relative_file="high.md", resource="kb:high", title="High relevance",
                type="Note", status="stable", trust="unverified", freshness="unknown",
                authority_label="unverified", score=2.0, reasons=(), excerpt="exactly relevant",
            ),
        ]
        mock_post.return_value = _mock_jev_response({
            "relevance_0": {
                "type": "score", "score": 1.0,
                "legend": {"0": "Irrelevant", "1": "Slightly", "2": "Moderate", "3": "High", "4": "Exact"},
                "probabilities": {"0": 0.8, "1": 0.1, "2": 0.1, "3": 0.0, "4": 0.0},
                "confidence": 0.9,
            },
            "relevance_1": {
                "type": "score", "score": 4.5,
                "legend": {"0": "Irrelevant", "1": "Slightly", "2": "Moderate", "3": "High", "4": "Exact"},
                "probabilities": {"0": 0.0, "1": 0.0, "2": 0.05, "3": 0.1, "4": 0.85},
                "confidence": 0.95,
            },
        })
        reranked, tokens = rerank_results("auth setup", cards, profile="personal")
        assert reranked[0].title == "High relevance"
        assert reranked[1].title == "Low relevance"
        assert tokens > 0


class TestJevContext:
    def test_no_jev_fallback(self, state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        concept = state_root / "concept.md"
        concept.write_text(
            "---\ntype: Note\ntitle: Test Concept\nresource: kb:test/concept\n---\n# Test\nA test concept.\n",
            encoding="utf-8",
        )
        from eos_kb.indexer import index_bundle
        index_bundle(state_root)
        result = jev_context(state_root, "test query", profile="personal")
        assert result.jev_used is False
        assert result.jev_tokens_used == 0

    @patch("eos_kb.jev._post")
    def test_route_component_filter_falls_back_when_empty(
        self, mock_post: MagicMock, state_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        concept = state_root / "concept.md"
        concept.write_text(
            "---\ntype: Note\ntitle: Auth Note\nresource: kb:test/auth\n---\n# Auth\noauth jwt login session.\n",
            encoding="utf-8",
        )
        from eos_kb.indexer import index_bundle
        index_bundle(state_root)
        mock_post.return_value = _mock_jev_response({
            "kb_section": {
                "type": "choice",
                "choice": "backend",
                "probabilities": {"backend": 0.9, "general": 0.1},
                "confidence": 0.8,
            },
            "complexity": {"type": "score", "score": 0.1, "legend": {}, "probabilities": {}, "confidence": 0.9},
            **{f"cluster_{k}": {"type": "noul", "noul": 0.1} for k in ["auth", "database", "api", "infra", "frontend", "agents", "testing", "knowledge", "messaging", "security"]},
        })
        result = jev_context(state_root, "oauth jwt", profile="personal", budget=4000)
        assert result.cards, "routing to an empty component filter must fall back to unfiltered results"
        assert result.routed_section is None

    @patch("eos_kb.jev._post")
    def test_explicit_budget_not_overridden_by_adaptive(
        self, mock_post: MagicMock, state_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        concept = state_root / "concept.md"
        concept.write_text(
            "---\ntype: Note\ntitle: Test Concept\nresource: kb:test/concept\n---\n# Test\nA test concept about oauth.\n",
            encoding="utf-8",
        )
        from eos_kb.indexer import index_bundle
        index_bundle(state_root)
        mock_post.return_value = _mock_jev_response({
            "kb_section": {"type": "choice", "choice": "general", "probabilities": {"general": 0.9}, "confidence": 0.9},
            "complexity": {"type": "score", "score": 0.0, "legend": {}, "probabilities": {}, "confidence": 0.9},
            **{f"cluster_{k}": {"type": "noul", "noul": 0.1} for k in ["auth", "database", "api", "infra", "frontend", "agents", "testing", "knowledge", "messaging", "security"]},
        })
        result = jev_context(state_root, "oauth", profile="personal", budget=5000)
        assert result.adaptive_budget is None

    @patch("eos_kb.jev._post")
    def test_adaptive_budget_applies_when_opted_in(
        self, mock_post: MagicMock, state_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        concept = state_root / "concept.md"
        concept.write_text(
            "---\ntype: Note\ntitle: Test Concept\nresource: kb:test/concept\n---\n# Test\nA test concept about oauth.\n",
            encoding="utf-8",
        )
        from eos_kb.indexer import index_bundle
        index_bundle(state_root)
        mock_post.return_value = _mock_jev_response({
            "kb_section": {"type": "choice", "choice": "general", "probabilities": {"general": 0.9}, "confidence": 0.9},
            "complexity": {"type": "score", "score": 0.0, "legend": {}, "probabilities": {}, "confidence": 0.9},
            **{f"cluster_{k}": {"type": "noul", "noul": 0.1} for k in ["auth", "database", "api", "infra", "frontend", "agents", "testing", "knowledge", "messaging", "security"]},
        })
        result = jev_context(
            state_root, "oauth", profile="personal", budget=2000, use_adaptive_budget=True
        )
        assert result.adaptive_budget == 500

    def test_warnings_carried_into_result(self, state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        concept = state_root / "concept.md"
        concept.write_text(
            "---\ntype: Note\ntitle: Test Concept\nresource: kb:test/concept\ntrust: unverified\n---\n# Test\nA test concept.\n",
            encoding="utf-8",
        )
        from eos_kb.indexer import index_bundle
        index_bundle(state_root)
        result = jev_context(state_root, "test", profile="personal", budget=4000)
        assert any("unverified" in warning for warning in result.warnings)


class TestDeriveProfile:
    def test_work_kb_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        work_kb = tmp_path / "work" / "knowledge"
        work_kb.mkdir(parents=True)
        monkeypatch.setenv("EOS_WORK_KNOWLEDGE_ROOT", str(work_kb))
        assert derive_jev_profile(work_kb) == "work"

    def test_personal_kb_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        work_kb = tmp_path / "work" / "knowledge"
        personal_kb = tmp_path / "personal" / "knowledge"
        work_kb.mkdir(parents=True)
        personal_kb.mkdir(parents=True)
        monkeypatch.setenv("EOS_WORK_KNOWLEDGE_ROOT", str(work_kb))
        assert derive_jev_profile(personal_kb) == "personal"


class TestRouteComponents:
    def test_maps_section_to_components(self) -> None:
        assert route_components_for("backend") == ["backend"]
        assert route_components_for("general") is None
        assert route_components_for("unknown") is None
        assert route_components_for(None) is None


class TestPlanQuery:
    def test_no_jev_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        assert plan_query("anything", profile="personal") is None

    @patch("eos_kb.jev._post")
    def test_single_call_batches_route_expand_complexity(
        self, mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        mock_post.return_value = _mock_jev_response({
            "kb_section": {"type": "choice", "choice": "backend", "probabilities": {"backend": 0.9}, "confidence": 0.8},
            "complexity": {"type": "score", "score": 3.0, "legend": {}, "probabilities": {}, "confidence": 0.9},
            "cluster_auth": {"type": "noul", "noul": 0.9},
            **{f"cluster_{k}": {"type": "noul", "noul": 0.1} for k in ["database", "api", "infra", "frontend", "agents", "testing", "knowledge", "messaging", "security"]},
        })
        plan = plan_query("oauth login", profile="personal")
        assert plan is not None
        assert plan.section == "backend"
        assert plan.complexity == 4
        assert plan.expanded_query is not None
        assert mock_post.call_count == 1


class TestCliJevFlags:
    @pytest.fixture
    def jev_bundle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
        root = tmp_path / "knowledge"
        root.mkdir()
        registry = tmp_path / "workspaces.yaml"
        registry.write_text(
            f"workspaces:\n  {tmp_path}:\n    kb: {root}\n    project: backend-project\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("EOS_KB_REGISTRY", str(registry))
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TYPESAFE_API_KEY_PERSONAL", raising=False)
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        concept = root / "concept.md"
        concept.write_text(
            "---\ntype: Note\ntitle: Family Note\nresource: kb:test/family\n"
            "eos:\n  project: backend-project\n  components: [identity]\n---\n"
            "# Note\nfamily split error retry.\n",
            encoding="utf-8",
        )
        from eos_kb.indexer import index_bundle
        index_bundle(root)
        return root

    def test_search_jev_without_key_matches_plain_search(
        self, jev_bundle: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["search", "family", "--kb", str(jev_bundle), "--json"]) == ExitCode.SUCCESS
        plain = json.loads(capsys.readouterr().out)
        assert main(["search", "family", "--kb", str(jev_bundle), "--jev", "--json"]) == ExitCode.SUCCESS
        jev = json.loads(capsys.readouterr().out)
        assert jev["data"] == plain["data"]

    def test_context_jev_respects_component_filter(
        self, jev_bundle: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([
            "context", "family", "--kb", str(jev_bundle), "--budget", "4000",
            "--component", "identity", "--jev", "--json",
        ]) == ExitCode.SUCCESS
        data = json.loads(capsys.readouterr().out)["data"]
        assert [card["resource"] for card in data["cards"]] == ["kb:test/family"]
        assert data["jev"]["adaptive_budget"] is None

    def test_context_jev_wrong_component_returns_empty(
        self, jev_bundle: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([
            "context", "family", "--kb", str(jev_bundle), "--budget", "4000",
            "--component", "nonexistent", "--jev", "--json",
        ]) == ExitCode.SUCCESS
        data = json.loads(capsys.readouterr().out)["data"]
        assert data["cards"] == []

    def test_context_jev_uses_explicit_budget(
        self, jev_bundle: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([
            "context", "family", "--kb", str(jev_bundle), "--budget", "5000", "--jev", "--json",
        ]) == ExitCode.SUCCESS
        data = json.loads(capsys.readouterr().out)["data"]
        assert data["budget"] == 5000
        assert data["jev"]["adaptive_budget"] is None


class TestCliJevRoutingInWorkspace:
    """Routing must work under the implicit workspace scope, for search and context alike."""

    @pytest.fixture
    def routed_workspace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
        monkeypatch.setenv("TYPESAFE_API_KEY_PERSONAL", "test-key")
        root = tmp_path / "knowledge"
        for name, components in (("api", "[backend]"), ("ui", "[frontend]")):
            path = root / "projects" / "alpha" / f"{name}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"---\ntype: Note\ntitle: {name}\nresource: kb:test/{name}\n"
                f"eos:\n  components: {components}\n---\n# Note\nsharedterm\n",
                encoding="utf-8",
            )
        from eos_kb.indexer import index_bundle
        index_bundle(root)
        registry = tmp_path / "workspaces.yaml"
        registry.write_text(
            f"workspaces:\n  {tmp_path}:\n    kb: {root}\n    project: alpha\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("EOS_KB_REGISTRY", str(registry))
        monkeypatch.chdir(tmp_path)
        return root

    @staticmethod
    def _plan_to_backend() -> dict:
        return _mock_jev_response({
            "kb_section": {"type": "choice", "choice": "backend", "probabilities": {"backend": 0.9}, "confidence": 0.9},
            "complexity": {"type": "score", "score": 1.0, "legend": {}, "probabilities": {}, "confidence": 0.9},
            **{f"cluster_{k}": {"type": "noul", "noul": 0.1} for k in ["auth", "database", "api", "infra", "frontend", "agents", "testing", "knowledge", "messaging", "security"]},
        })

    @patch("eos_kb.jev._post")
    def test_context_routes_under_workspace_scope(
        self, mock_post: MagicMock, routed_workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_post.return_value = self._plan_to_backend()
        assert main(["context", "sharedterm", "--budget", "4000", "--jev", "--json"]) == ExitCode.SUCCESS
        data = json.loads(capsys.readouterr().out)["data"]
        assert data["jev"]["routed_section"] == "backend"
        assert [card["resource"] for card in data["cards"]] == ["kb:test/api"]

    @patch("eos_kb.jev._post")
    def test_search_routes_under_workspace_scope(
        self, mock_post: MagicMock, routed_workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_post.return_value = self._plan_to_backend()
        assert main(["search", "sharedterm", "--jev", "--json"]) == ExitCode.SUCCESS
        data = json.loads(capsys.readouterr().out)["data"]
        assert [card["resource"] for card in data] == ["kb:test/api"]

    @pytest.mark.parametrize("command", [["context", "--budget", "4000"], ["search"]])
    @patch("eos_kb.jev._post")
    def test_explicit_project_disables_routing(
        self, mock_post: MagicMock, command: list[str],
        routed_workspace: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_post.return_value = self._plan_to_backend()
        verb, *rest = command
        assert main([verb, "sharedterm", *rest, "--project", "alpha", "--jev", "--json"]) == ExitCode.SUCCESS
        data = json.loads(capsys.readouterr().out)["data"]
        cards = data["cards"] if verb == "context" else data
        assert sorted(card["resource"] for card in cards) == ["kb:test/api", "kb:test/ui"]
        if verb == "context":
            assert data["jev"]["routed_section"] is None


class TestFilterScript:
    @pytest.fixture
    def script_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
        keys = ("TYPESAFE_API_KEY_WORK", "TYPESAFE_API_KEY_PERSONAL", "TYPESAFE_API_KEY")
        for key in keys:
            monkeypatch.delenv(key, raising=False)
        repo_root = Path(__file__).resolve().parents[2]
        env = {k: v for k, v in os.environ.items() if k not in keys}
        env["EOS_ROOT"] = str(repo_root)
        # The script loads EOS config; keep the host .eos.local and profiles out of tests.
        env["EOS_CONFIG_FILE"] = str(tmp_path / "missing-eos.local")
        env["EOS_PROFILE_ROOT"] = str(tmp_path / "profiles")
        return env

    def _run(self, script_env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
        repo_root = Path(script_env["EOS_ROOT"])
        return subprocess.run(
            ["bash", str(repo_root / "scripts" / "eos-jev-filter"), *args],
            capture_output=True,
            text=True,
            env=script_env,
            timeout=30,
        )

    def test_status(self, script_env: dict[str, str]) -> None:
        proc = self._run(script_env, "status")
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload == {"work": False, "personal": False}

    def test_apostrophe_query_does_not_crash(self, script_env: dict[str, str]) -> None:
        proc = self._run(script_env, "expand", "--query", "what's auth setup")
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["original"] == "what's auth setup"
        assert payload["expanded"] == "what's auth setup"

    def test_injection_payload_is_inert(self, script_env: dict[str, str]) -> None:
        payload_query = "'); import os; os.system('touch /tmp/jev-pwned')#"
        marker = Path("/tmp/jev-pwned")
        if marker.exists():
            marker.unlink()
        proc = self._run(script_env, "expand", "--query", payload_query)
        assert proc.returncode == 0, proc.stderr
        assert not marker.exists()
        payload = json.loads(proc.stdout)
        assert payload["original"] == payload_query

    def test_invalid_budget_rejected(self, script_env: dict[str, str]) -> None:
        proc = self._run(script_env, "budget", "--query", "x", "--budget", "abc")
        assert proc.returncode == 2
        assert "positive integer" in proc.stderr

    def test_unknown_command_rejected(self, script_env: dict[str, str]) -> None:
        proc = self._run(script_env, "nope")
        assert proc.returncode == 2

    def test_derives_work_profile_from_kb_path(
        self, script_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        work_kb = tmp_path / "work" / "knowledge"
        work_kb.mkdir(parents=True)
        concept = work_kb / "concept.md"
        concept.write_text(
            "---\ntype: Note\ntitle: Work Note\nresource: kb:work/note\n---\n# Note\nwork knowledge.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
        from eos_kb.indexer import index_bundle
        index_bundle(work_kb)
        script_env["EOS_WORK_KNOWLEDGE_ROOT"] = str(work_kb)
        script_env["EOS_KB_STATE_ROOT"] = str(tmp_path / "state")
        proc = self._run(script_env, "context", "--kb", str(work_kb), "--query", "work", "--budget", "4000")
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["jev_used"] is False
        assert payload["cards"]
