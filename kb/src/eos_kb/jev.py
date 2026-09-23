"""TypeSafe Jev API client for EOS knowledge-base context management.

Uses only stdlib (urllib) to avoid adding dependencies to the kb package.
Falls back gracefully when Jev is unavailable.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class JevError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class JevAnswer:
    question_id: str
    type: str
    noul: float | None = None
    choice: str | None = None
    probabilities: dict[str, float] | None = None
    confidence: float | None = None
    score: float | None = None
    legend: dict[str, str] | None = None


@dataclass(frozen=True)
class JevResponse:
    model: str
    answers: dict[str, JevAnswer]
    input_tokens: int
    output_tokens: int


def _api_key(profile: str) -> str | None:
    env_map = {
        "work": "TYPESAFE_API_KEY_WORK",
        "personal": "TYPESAFE_API_KEY_PERSONAL",
    }
    var = env_map.get(profile, "TYPESAFE_API_KEY_PERSONAL")
    return os.environ.get(var) or os.environ.get("TYPESAFE_API_KEY")


def derive_jev_profile(kb: Path | str) -> str:
    """Derive the work/personal profile from a KB root path.

    Matches the KB path against EOS_WORK_KNOWLEDGE_ROOT (or the standard
    ~/work/knowledge default), mirroring eos-kb-pending-reminder.
    """
    work_root = os.environ.get("EOS_WORK_KNOWLEDGE_ROOT") or str(
        Path.home() / "work" / "knowledge"
    )
    try:
        if Path(kb).resolve() == Path(work_root).expanduser().resolve():
            return "work"
    except OSError:
        pass
    return "personal"


def _post(url: str, payload: dict[str, Any], api_key: str, timeout: float = 10.0) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise JevError(
            f"jev.http_{exc.code}",
            f"Jev API returned {exc.code}: {error_body[:200]}",
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise JevError("jev.unavailable", f"Jev API is unreachable: {exc}") from exc
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JevError("jev.bad_response", f"Jev API returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise JevError(
            "jev.bad_response",
            f"Jev API response must be an object, got {type(parsed).__name__}",
        )
    return parsed


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _parse_answer(question_id: str, raw: dict[str, Any]) -> JevAnswer:
    answer_type = str(raw.get("type", ""))
    return JevAnswer(
        question_id=question_id,
        type=answer_type,
        noul=_coerce_float(raw.get("noul")),
        choice=raw.get("choice"),
        probabilities=raw.get("probabilities"),
        confidence=_coerce_float(raw.get("confidence")),
        score=_coerce_float(raw.get("score")),
        legend=raw.get("legend"),
    )


def evaluate(
    state: str | dict | list,
    questions: dict[str, dict[str, Any]],
    *,
    profile: str = "personal",
    model: str = "jev-latest",
    timeout: float = 10.0,
) -> JevResponse:
    """Evaluate state against typed questions using the Jev API.

    Raises JevError on failure. Caller should catch and fall back.
    """
    api_key = _api_key(profile)
    if not api_key:
        raise JevError(
            "jev.no_api_key",
            f"No TypeSafe API key found for profile '{profile}'. "
            "Set TYPESAFE_API_KEY_WORK or TYPESAFE_API_KEY_PERSONAL.",
        )
    payload = {
        "state": state,
        "model": model,
        "questions": questions,
    }
    raw = _post("https://api.typesafe.ai/v1/systemone", payload, api_key, timeout=timeout)
    try:
        answers_raw = raw.get("answers", {})
        if not isinstance(answers_raw, dict):
            raise TypeError(f"'answers' must be an object, got {type(answers_raw).__name__}")
        answers: dict[str, JevAnswer] = {}
        for qid, answer_raw in answers_raw.items():
            if not isinstance(answer_raw, dict):
                raise TypeError(
                    f"answer '{qid}' must be an object, got {type(answer_raw).__name__}"
                )
            answers[str(qid)] = _parse_answer(str(qid), answer_raw)
        usage = raw.get("usage", {})
        if not isinstance(usage, dict):
            raise TypeError(f"'usage' must be an object, got {type(usage).__name__}")
        return JevResponse(
            model=str(raw.get("model", "")),
            answers=answers,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise JevError("jev.bad_response", f"Jev API returned a malformed response: {exc}") from exc


def is_available(profile: str = "personal") -> bool:
    """Check if Jev API is configured (has a non-empty API key)."""
    return bool(_api_key(profile))
