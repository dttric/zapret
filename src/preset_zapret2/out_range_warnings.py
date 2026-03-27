from __future__ import annotations

from pathlib import Path

from .block_semantics import analyze_block_semantics, has_explicit_out_range as _has_explicit_out_range
from .txt_preset_parser import parse_preset_file

def has_explicit_out_range(args_text: str) -> bool:
    return _has_explicit_out_range(args_text)


def _block_warning_label(block) -> str:
    category = str(getattr(block, "category", "") or "").strip()
    protocol = str(getattr(block, "protocol", "") or "").strip().lower() or "tcp"
    filter_file = str(getattr(block, "filter_file", "") or "").strip()

    if category and category != "unknown":
        return f"{category}/{protocol}"
    if filter_file:
        return f"{Path(filter_file).name}/{protocol}"
    return f"block/{protocol}"


def _should_warn_for_launch(semantics) -> bool:
    status = str(getattr(getattr(semantics, "out_range", None), "status", "") or "").strip().lower()
    raw_value = str(getattr(getattr(semantics, "out_range", None), "raw_value", "") or "").strip()

    if status == "absent":
        return True

    # Launch warning is about missing explicit narrowing, not about whether the
    # block can be losslessly round-tripped as one structured out-range value.
    # Mixed forms like top-level --out-range plus inline :out_range=... are
    # valid explicit narrowing for runtime and must not trigger this warning.
    if status == "invalid" and not raw_value:
        return True

    return False


def collect_missing_out_range_labels_from_file(preset_path: str | Path) -> list[str]:
    data = parse_preset_file(Path(preset_path))
    labels: list[str] = []
    seen: set[str] = set()

    for block in data.categories:
        block_text = str(getattr(block, "raw_args", "") or getattr(block, "args", "") or "")
        semantics = analyze_block_semantics(block_text)
        if not _should_warn_for_launch(semantics):
            continue

        label = _block_warning_label(block)
        dedupe_key = label.strip().lower()
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        labels.append(label)

    return labels
