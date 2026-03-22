from __future__ import annotations

"""Strategy id inference for Zapret 1 presets."""

from typing import Dict, Optional

from .strategies_loader import load_v1_strategies


def normalize_args(args: str) -> str:
    if not args:
        return ""

    blocks: list[list[str]] = [[]]
    for raw in args.strip().split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line == "--new":
            blocks.append([])
            continue
        blocks[-1].append(line)

    normalized_blocks: list[str] = []
    for block in blocks:
        if not block:
            continue
        normalized_blocks.append("\n".join(sorted(block)).lower())

    return "\n--new\n".join(normalized_blocks)


def infer_strategy_id_from_args(
    category_key: str,
    args: str,
    protocol: str = "tcp",
    strategy_set: Optional[str] = None,
) -> str:
    _ = (protocol, strategy_set)

    normalized_input = normalize_args(args)
    if not normalized_input:
        return "none"

    strategies = load_v1_strategies(category_key)
    if not strategies:
        return "custom"

    for strategy_id, strategy_data in (strategies or {}).items():
        strategy_args = (strategy_data or {}).get("args", "")
        if not strategy_args:
            continue
        if normalize_args(strategy_args) == normalized_input:
            return strategy_id

    def _strip_syndata_lines(value: str) -> str:
        return "\n".join(
            ln for ln in (value or "").splitlines()
            if not ln.strip().lower().startswith(("--lua-desync=syndata:", "--lua-desync=send:"))
        )

    normalized_input_stripped = normalize_args(_strip_syndata_lines(args))
    if normalized_input_stripped:
        for strategy_id, strategy_data in (strategies or {}).items():
            strategy_args = (strategy_data or {}).get("args", "")
            if not strategy_args:
                continue
            if normalize_args(_strip_syndata_lines(strategy_args)) == normalized_input_stripped:
                return strategy_id

    return "custom"


def infer_strategy_ids_batch(
    categories: Dict[str, Dict[str, str]],
    strategy_set: Optional[str] = None,
) -> Dict[str, str]:
    _ = strategy_set

    result: Dict[str, str] = {}
    for cat_key, cat_data in (categories or {}).items():
        tcp_args = (cat_data or {}).get("tcp_args", "")
        udp_args = (cat_data or {}).get("udp_args", "")

        if tcp_args:
            sid = infer_strategy_id_from_args(cat_key, tcp_args, "tcp")
            if sid != "none":
                result[cat_key] = sid
                continue

        if udp_args:
            result[cat_key] = infer_strategy_id_from_args(cat_key, udp_args, "udp")
        else:
            result[cat_key] = "none"

    return result
