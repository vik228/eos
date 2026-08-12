from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ClaimNormalizationError(ValueError):
    code: str
    field_path: str
    remediation: str

    def __str__(self) -> str:
        return f"{self.code} at {self.field_path}: {self.remediation}"


def _normalize(value: Any, path: str) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise ClaimNormalizationError(
            "claim.float_not_allowed", path, "Use integer values instead of floating-point values."
        )
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ClaimNormalizationError(
                    "claim.non_string_key", path, "Use string keys for JSON objects."
                )
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in result:
                raise ClaimNormalizationError(
                    "claim.duplicate_normalized_key",
                    path,
                    "Object keys must be unique after Unicode NFC normalization.",
                )
            result[normalized_key] = _normalize(item, f"{path}.{normalized_key}")
        return {key: result[key] for key in sorted(result)}
    raise ClaimNormalizationError(
        "claim.invalid_value", path, "Use only JSON-compatible values."
    )


def normalize_claim(value: Any) -> str:
    normalized = _normalize(value, "$")
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def normalized_content_hash(content: str) -> str:
    canonical = unicodedata.normalize("NFC", content).replace("\r\n", "\n").replace("\r", "\n")
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
