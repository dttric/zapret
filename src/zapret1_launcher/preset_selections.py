"""
Utilities for treating preset-zapret1.txt as the source of truth.

Goal: infer GUI category -> strategy_id selections from the preset file, without using registry storage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from config import MAIN_DIRECTORY
from log import log


def get_preset_zapret1_path() -> Path:
    return Path(MAIN_DIRECTORY) / "preset-zapret1.txt"


def _read_preset_tokens(preset_path: Path) -> list[str]:
    lines = preset_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    tokens: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens.append(line)
    return tokens


def _split_args(text: str) -> list[str]:
    return [t for t in (text or "").split() if t]


def _find_subseq_start(haystack: list[str], needle: list[str]) -> int | None:
    if not needle:
        return None
    n = len(needle)
    for i in range(0, len(haystack) - n + 1):
        if haystack[i:i + n] == needle:
            return i
    return None


def _subsequence_full_match(needle: Iterable[str], haystack: list[str]) -> bool:
    """
    True if all tokens from needle appear in haystack in the same order (not necessarily contiguous).
    """
    it = iter(haystack)
    for n in needle:
        for h in it:
            if h == n:
                break
        else:
            return False
    return True


def infer_direct_zapret1_selections_from_preset() -> dict[str, str]:
    """
    Returns {category_key: strategy_id} inferred from preset-zapret1.txt.

    If parsing fails or file missing, returns empty dict.
    """
    preset_path = get_preset_zapret1_path()
    if not preset_path.exists():
        return {}

    tokens = _read_preset_tokens(preset_path)
    try:
        from strategy_menu.strategies_registry import registry
    except Exception:
        return {}

    if not tokens:
        return {k: "none" for k in registry.get_all_category_keys()}

    try:
        from zapret1_launcher.strategy_builder import _sanitize_args_for_v1

        selections: dict[str, str] = {k: "none" for k in registry.get_all_category_keys()}

        # Step 1: split preset into per-category blocks by finding base_filter occurrences.
        starts: list[tuple[int, str, list[str]]] = []
        for category_key in registry.get_all_category_keys():
            cat = registry.get_category_info(category_key)
            if not cat:
                continue

            base_candidates = [cat.base_filter]
            if cat.base_filter_hostlist:
                base_candidates.append(cat.base_filter_hostlist)
            if cat.base_filter_ipset:
                base_candidates.append(cat.base_filter_ipset)

            base_tokens_variants = [_split_args(c) for c in base_candidates if c]
            base_tokens_variants.sort(key=len, reverse=True)

            for base_tokens in base_tokens_variants:
                idx = _find_subseq_start(tokens, base_tokens)
                if idx is not None:
                    starts.append((idx, category_key, base_tokens))
                    break

        starts.sort(key=lambda x: x[0])
        category_blocks: dict[str, list[str]] = {}
        for i, (start, category_key, base_tokens) in enumerate(starts):
            end = starts[i + 1][0] if i + 1 < len(starts) else len(tokens)
            block = tokens[start:end]
            if block[:len(base_tokens)] == base_tokens:
                block = block[len(base_tokens):]
            category_blocks[category_key] = block

        if not category_blocks:
            return selections

        # Step 2: infer strategy_id per category by matching strategy args to the block.
        wssize_tokens = {"--wssize", "1:6", "--wssize-forced-cutoff=0"}

        for category_key, block_tokens in category_blocks.items():
            cleaned_block = [t for t in block_tokens if t not in wssize_tokens]

            best_id: str | None = None
            best_len = 0

            strategies = registry.get_category_strategies(category_key)
            for strategy_id, strategy in strategies.items():
                base_args = (strategy or {}).get("args", "")
                if not base_args:
                    continue

                candidate = _sanitize_args_for_v1(base_args)
                candidate_tokens = [t for t in _split_args(candidate) if t not in wssize_tokens]
                if not candidate_tokens:
                    continue

                if _subsequence_full_match(candidate_tokens, cleaned_block):
                    if len(candidate_tokens) > best_len:
                        best_len = len(candidate_tokens)
                        best_id = strategy_id

            if best_id:
                selections[category_key] = best_id

        return selections

    except Exception as e:
        log(f"Ошибка разбора preset-zapret1.txt для выбора стратегий: {e}", "DEBUG")
        return {}
