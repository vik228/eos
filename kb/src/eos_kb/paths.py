from __future__ import annotations

import os
import sys
from pathlib import Path


def eos_root() -> Path:
    configured = os.environ.get("EOS_ROOT")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())

    marker = Path(sys.prefix) / ".eos-root"
    if marker.is_file():
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            candidates.append(Path(value).expanduser())

    candidates.append(Path(__file__).resolve().parents[3])
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "configs" / "kb").is_dir():
            return resolved
    raise RuntimeError("EOS config root is unavailable. Re-run scripts/setup-kb.")


def kb_config_path(*parts: str) -> Path:
    return eos_root() / "configs" / "kb" / Path(*parts)
