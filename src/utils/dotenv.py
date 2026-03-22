from __future__ import annotations

import os
from pathlib import Path


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_dotenv(*paths: Path, override: bool = False) -> Path | None:
    """
    Minimal .env loader (no external deps).

    - Supports lines: KEY=VALUE or export KEY=VALUE
    - Ignores empty lines and comments starting with '#'
    - Does NOT expand ${VARS}; keeps values as-is
    - By default does not override existing environment variables
    - Loads ALL existing files from *paths* (not just the first one)
    """
    first_loaded: Path | None = None

    for p in paths:
        try:
            p = Path(p)
        except Exception:
            continue
        if not p.exists() or not p.is_file():
            continue

        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if first_loaded is None:
            first_loaded = p

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            if not key or any(ch.isspace() for ch in key):
                continue

            # Support inline comments: KEY=VALUE # comment
            # (only when value is not quoted)
            value = value.strip()
            if value and value[0] not in {"'", '"'} and " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            value = _strip_quotes(value)

            if override or key not in os.environ:
                os.environ[key] = value

    return first_loaded
