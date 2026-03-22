import re


_STRATEGY_TAG_RE = re.compile(r":strategy=\d+")
_CIRCULAR_RE = re.compile(r"^--lua-desync=(?:circular|circular_quality)(?::|$)", re.IGNORECASE)


def strip_strategy_tags(content: str) -> str:
    """Removes all ':strategy=N' tags from text."""
    if not content:
        return ""
    return _STRATEGY_TAG_RE.sub("", content)


def renumber_circular_strategies(content: str) -> str:
    """Assigns :strategy=N to strategy lines after circular/circular_quality.

    Numbering rules:
    - Counter resets at each `--new` block.
    - Counter resets when a new `--payload=...` group starts.
    - `--lua-desync=circular...` / `--lua-desync=circular_quality...` lines are not numbered.
    - Multiple `--lua-desync=...` on the same line get the same strategy number.
    """
    lines = (content or "").splitlines()
    result: list[str] = []

    after_circular = False
    strategy_counter = 0
    current_payload: object = object()

    for raw in lines:
        stripped = (raw or "").strip()

        if stripped == "--new":
            after_circular = False
            strategy_counter = 0
            current_payload = object()
            result.append(raw)
            continue

        cleaned = _STRATEGY_TAG_RE.sub("", stripped)

        if _CIRCULAR_RE.match(cleaned):
            after_circular = True
            strategy_counter = 0
            current_payload = object()
            result.append(cleaned)
            continue

        if after_circular and cleaned.startswith("--payload="):
            payload = cleaned[len("--payload="):]
            if payload != current_payload:
                current_payload = payload
                strategy_counter = 0
            result.append(cleaned)
            continue

        if after_circular and cleaned.startswith("--lua-desync="):
            strategy_counter += 1
            parts = re.split(r"(?<=\S)\s+(?=--)", cleaned)
            tagged_parts: list[str] = []
            for part in parts:
                part_clean = _STRATEGY_TAG_RE.sub("", part)
                if part_clean.startswith("--lua-desync="):
                    part_clean = f"{part_clean}:strategy={strategy_counter}"
                tagged_parts.append(part_clean)
            result.append(" ".join(tagged_parts))
            continue

        result.append(_STRATEGY_TAG_RE.sub("", raw))

    return "\n".join(result)
