from __future__ import annotations

import pytest

from eos_kb.normalize import (
    ClaimNormalizationError,
    normalize_claim,
    normalized_content_hash,
)


def test_claim_normalization_is_canonical() -> None:
    assert normalize_claim({"b": 2, "a": ["e\u0301", True]}) == '{"a":["é",true],"b":2}'


def test_claim_normalization_preserves_array_order() -> None:
    assert normalize_claim([3, 1, 2]) == "[3,1,2]"


def test_claim_normalization_uses_json_integer_boolean_and_null_literals() -> None:
    assert normalize_claim({"integer": -12, "false": False, "none": None}) == (
        '{"false":false,"integer":-12,"none":null}'
    )


@pytest.mark.parametrize("value", (1.0, {"nested": [0, 2.5]}))
def test_claim_normalization_rejects_floats(value: object) -> None:
    with pytest.raises(ClaimNormalizationError) as captured:
        normalize_claim(value)

    assert captured.value.code == "claim.float_not_allowed"
    assert "integer" in captured.value.remediation


def test_claim_normalization_rejects_duplicate_keys_after_nfc() -> None:
    with pytest.raises(ClaimNormalizationError) as captured:
        normalize_claim({"é": 1, "e\u0301": 2})

    assert captured.value.code == "claim.duplicate_normalized_key"
    assert captured.value.field_path == "$"
    assert "unique after Unicode NFC normalization" in captured.value.remediation


def test_claim_normalization_rejects_non_string_object_keys() -> None:
    with pytest.raises(ClaimNormalizationError) as captured:
        normalize_claim({1: "value"})

    assert captured.value.code == "claim.non_string_key"
    assert captured.value.field_path == "$"


def test_normalized_content_hash_ignores_line_endings_and_unicode_form() -> None:
    composed = normalized_content_hash("Résumé\nLine two\n")
    decomposed = normalized_content_hash("Re\u0301sume\u0301\r\nLine two\r\n")

    assert decomposed == composed
    assert composed.startswith("sha256:")
    assert len(composed) == len("sha256:") + 64
