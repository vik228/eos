from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import kb_config_path


@dataclass(frozen=True)
class SchemaValidationError(ValueError):
    code: str
    relative_file: str
    field_path: str
    remediation: str

    def __str__(self) -> str:
        return f"{self.code} at {self.relative_file}:{self.field_path}: {self.remediation}"


def load_schema(name: str, *, version: int = 1, schema_dir: Path | None = None) -> dict[str, Any]:
    directory = schema_dir or kb_config_path("schemas")
    path = directory / f"{name}-v{version}.json"
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load schema {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Schema {path} must contain a JSON object")
    return value
