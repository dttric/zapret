# preset_zapret2/strategy_inference.py
"""
Strategy ID inference from arguments.

This module provides functions to determine strategy_id from strategy arguments
when loading presets from files. This is needed because preset files store
args but not strategy_id, and UI needs to know which strategy is active.

Usage:
    from preset_zapret2.strategy_inference import infer_strategy_id_from_args

    strategy_id = infer_strategy_id_from_args(
        category_key="youtube",
        args="--lua-desync=multisplit:pos=1,midsld",
        protocol="tcp"
    )
"""

from typing import Dict, Optional


def normalize_args(args: str) -> str:
    """
    Normalizes strategy arguments for comparison.

    Normalization rules:
    - Strips whitespace from each line
    - Removes empty lines
    - Sorts lines (order doesn't matter)
    - Converts to lowercase (for case-insensitive comparison)

    Args:
        args: Raw strategy arguments (can be multiline)

    Returns:
        Normalized arguments string

    Example:
        Input:  "--lua-desync=multisplit:pos=1,midsld\n--lua-desync=disorder:pos=1"
        Output: "--lua-desync=disorder:pos=1\n--lua-desync=multisplit:pos=1,midsld"
    """
    if not args:
        return ""

    # Keep `--new` separators (some strategies are multi-block).
    blocks: list[list[str]] = [[]]
    for raw in args.strip().split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line == "--new":
            blocks.append([])
            continue
        blocks[-1].append(line)

    # Sort lines inside each block (order inside block should not matter for matching)
    normalized_blocks = []
    for block in blocks:
        if not block:
            continue
        normalized_blocks.append("\n".join(sorted(block)).lower())

    return "\n--new\n".join(normalized_blocks)


def _get_strategy_type_for_category(category_key: str) -> Optional[str]:
    try:
        from .catalog import load_categories
        categories = load_categories()
        info = categories.get(category_key) or {}
        st = (info.get("strategy_type") or "").strip()
        return st or None
    except Exception:
        return None


def infer_strategy_id_from_args(
    category_key: str,
    args: str,
    protocol: str = "tcp",
    strategy_set: Optional[str] = None,
) -> str:
    """
    Infers strategy_id from strategy arguments.

    This function is used when loading presets from files.
    Preset files contain args but not strategy_id.
    We need to reverse-lookup the strategy_id by comparing args.

    Algorithm:
    1. Normalize input args
    2. Get all strategies for the category
    3. For each strategy:
       - Get strategy["args"] (pure args, without base_filter)
       - Normalize
       - Compare with input
    4. Return first match or "none" if not found

    Args:
        category_key: Category name (e.g., "youtube", "discord")
        args: Strategy arguments from preset file
        protocol: Protocol ("tcp" or "udp") - used only for logging
        strategy_set: Optional strategies catalog set name (e.g. "basic", "advanced", "orchestra").
            When provided, inference compares args against that catalog to keep UI
            selection stable across refreshes.

    Returns:
        strategy_id if found, "none" otherwise

    Edge cases:
    - Empty args → "none"
    - Unknown category → "none"
    - No strategies for category → "none"
    - No matching strategy → "none" (not an error, just no match)

    Example:
        >>> infer_strategy_id_from_args(
        ...     "youtube",
        ...     "--lua-desync=multisplit:pos=1,midsld",
        ...     "tcp"
        ... )
        "youtube_tcp_split"
    """
    # Normalize input args
    normalized_input = normalize_args(args)

    # Empty args = none
    if not normalized_input:
        return "none"

    strategy_type = _get_strategy_type_for_category(category_key) or ("udp" if protocol == "udp" else "tcp")
    # Search for matching strategy
    def _iter_candidate_strategy_types(primary_type: str) -> list[str]:
        """
        Strategy args may come from multiple builtin files.

        Example: TCP multi-phase UI loads additional strategies from `tcp_fake.txt`,
        and preset files can contain those args. When loading such presets, we want to
        resolve strategy_id to the real one (not "custom") so UI shows the name.

        Also: some categories have strategy_type='tcp' in categories.txt but appear
        in UDP blocks (e.g. ipset_zapretkvn). When the actual block protocol is 'udp'
        but the category says 'tcp', also search the udp catalog as a fallback.
        """
        st = (primary_type or "").strip()
        if not st:
            return []
        if st == "tcp":
            candidates = [st, "tcp_fake"]
            # When the actual block is UDP, also search the udp catalog in case
            # the category has a mismatched strategy_type.
            if protocol == "udp":
                candidates.append("udp")
            return candidates
        if st == "discord_voice":
            # Also check udp catalog for discord_voice_udp categories
            return [st, "udp"]
        return [st]

    any_strategies_loaded = False
    loaded_candidates: dict[str, dict] = {}

    for candidate_type in _iter_candidate_strategy_types(strategy_type):
        try:
            from .catalog import load_strategies

            # tcp_fake is a special catalog used by the multi-phase TCP UI.
            # In advanced mode it is loaded from advanced_strategies; in other
            # modes keep legacy untied behavior.
            candidate_type_key = (candidate_type or "").strip().lower()
            if candidate_type_key == "tcp_fake":
                set_for_candidate = "advanced" if (strategy_set == "advanced") else None
            else:
                set_for_candidate = strategy_set
            candidates = load_strategies(candidate_type, strategy_set=set_for_candidate)
        except Exception:
            candidates = {}

        if candidates:
            any_strategies_loaded = True
        loaded_candidates[candidate_type] = candidates or {}

        for strategy_id, strategy_data in (candidates or {}).items():
            strategy_args = (strategy_data or {}).get("args", "")
            if not strategy_args:
                continue

            # Normalize strategy args
            normalized_strategy = normalize_args(strategy_args)

            # Compare
            if normalized_strategy == normalized_input:
                return strategy_id

    if not any_strategies_loaded:
        # Strategies catalog isn't available (first-run extract/update/etc).
        # Keep the category enabled in UI when args are present.
        return "custom"

    # Fallback: strip non-identity transport helpers from both sides and retry.
    # In basic direct mode, extracted preset args may already omit send/syndata/out-range
    # lines while catalog entries still contain them.
    def _strip_syndata_lines(a: str) -> str:
        def _is_syndata_or_send(ln: str) -> bool:
            s = ln.strip().lower()
            is_syndata = s == "--lua-desync=syndata" or s.startswith("--lua-desync=syndata:")
            is_send = s == "--lua-desync=send" or s.startswith("--lua-desync=send:")
            is_out_range = s.startswith("--out-range") or s.startswith("--in-range")
            is_wssize = s == "--lua-desync=wssize:wsize=1:scale=6"
            return is_syndata or is_send or is_out_range or is_wssize
        return "\n".join(ln for ln in a.splitlines() if not _is_syndata_or_send(ln))

    normalized_input_stripped = normalize_args(_strip_syndata_lines(args))
    if normalized_input_stripped:
        for candidate_type in _iter_candidate_strategy_types(strategy_type):
            for strategy_id, strategy_data in loaded_candidates.get(candidate_type, {}).items():
                strategy_args = (strategy_data or {}).get("args", "")
                if not strategy_args:
                    continue
                normalized_strategy_stripped = normalize_args(_strip_syndata_lines(strategy_args))
                if normalized_strategy_stripped == normalized_input_stripped:
                    return strategy_id

    # Non-empty args that don't match any known strategy: keep category enabled in UI.
    return "custom"


def infer_strategy_ids_batch(
    categories: Dict[str, Dict[str, str]],
    strategy_set: Optional[str] = None,
) -> Dict[str, str]:
    """
    Infers strategy_ids for multiple categories at once.

    Useful for bulk operations (e.g., loading entire preset).

    Args:
        categories: Dict of {category_key: {"tcp_args": "...", "udp_args": "..."}}
        strategy_set: Optional strategies catalog set name to use for inference.

    Returns:
        Dict of {category_key: strategy_id}

    Note:
        For categories with both TCP and UDP, prefers TCP strategy_id.
        If TCP is empty or not found, tries UDP.
    """
    result = {}

    for cat_key, cat_data in categories.items():
        tcp_args = cat_data.get("tcp_args", "")
        udp_args = cat_data.get("udp_args", "")

        # Try TCP first
        if tcp_args:
            strategy_id = infer_strategy_id_from_args(cat_key, tcp_args, "tcp", strategy_set=strategy_set)
            if strategy_id != "none":
                result[cat_key] = strategy_id
                continue

        # Try UDP if TCP didn't work
        if udp_args:
            strategy_id = infer_strategy_id_from_args(cat_key, udp_args, "udp", strategy_set=strategy_set)
            result[cat_key] = strategy_id
        else:
            result[cat_key] = "none"

    return result
